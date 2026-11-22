"""Needs QGIS and a PostGIS database. Skipped when either is missing.

Connection settings come from GEOMIGRATE_PG_HOST / _PORT / _DB / _USER / _PASSWORD
(defaults match the Docker command in the README: localhost:5432, geomigrate, postgres/postgres).
"""
import os
import uuid
from pathlib import Path

import pytest

pytest.importorskip("qgis.core")

from qgis.core import QgsFeatureRequest, QgsProviderConnectionException, QgsVectorLayer

from geomigrate_qa.core import postgis_loader
from geomigrate_qa.core.postgis_loader import LoadError, PgConnection, count_rows, load_layers

SAMPLE = Path(__file__).resolve().parents[1] / "sample_data"
pytestmark = pytest.mark.skipif(
    not (SAMPLE / "expected_errors.json").exists(),
    reason="run scripts/generate_sample_data.py first",
)


def settings():
    return PgConnection(
        host=os.environ.get("GEOMIGRATE_PG_HOST", "localhost"),
        port=int(os.environ.get("GEOMIGRATE_PG_PORT", "5432")),
        dbname=os.environ.get("GEOMIGRATE_PG_DB", "geomigrate"),
        user=os.environ.get("GEOMIGRATE_PG_USER", "postgres"),
        password=os.environ.get("GEOMIGRATE_PG_PASSWORD", "postgres"))


@pytest.fixture(scope="module")
def pg():
    params = settings()
    try:
        params.connect().executeSql("SELECT 1")
    except QgsProviderConnectionException as exc:  # no server running: skip, do not fail
        pytest.skip(f"PostGIS not available: {exc}")
    return params


@pytest.fixture
def schema(pg):
    name = f"gm_test_{uuid.uuid4().hex[:8]}"
    yield name
    conn = pg.connect()
    conn.executeSql(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
    conn.executeSql(f'DROP SCHEMA IF EXISTS "{name}_stg" CASCADE')


def clean(name):
    return QgsVectorLayer(f"{SAMPLE / 'clean' / 'network.gpkg'}|layername={name}", name, "ogr")


def clean_layers():
    return {n: clean(n) for n in ("poles", "towers", "cables")}


def sql(pg, query):
    return pg.connect().executeSql(query)


def test_clean_layers_load_with_index_srid_and_log(pg, schema):
    result = load_layers(clean_layers(), pg, schema, source="unit test")
    assert result.ok and result.loaded == {"poles": 48, "towers": 6, "cables": 42}

    srids = sql(pg, f'SELECT DISTINCT ST_SRID(geom) FROM "{schema}".cables')
    assert srids == [[32643]]
    indexes = sql(pg, f"SELECT indexdef FROM pg_indexes WHERE schemaname = '{schema}' "
                      "AND tablename = 'poles'")
    assert any("USING gist" in row[0] for row in indexes)
    assert any("PRIMARY" in row[0].upper() or "pkey" in row[0] for row in indexes)

    log = sql(pg, f'SELECT table_name, features_loaded, status FROM "{schema}".geomigrate_run_log '
                  "ORDER BY table_name")
    assert log == [["cables", 42, "loaded"], ["poles", 48, "loaded"], ["towers", 6, "loaded"]]
    staging = sql(pg, f"SELECT count(*) FROM information_schema.tables "
                      f"WHERE table_schema = '{schema}_stg'")
    assert staging == [[0]]


def test_loaded_table_can_be_read_back_by_qgis(pg, schema):
    load_layers({"poles": clean("poles")}, pg, schema)
    layer = QgsVectorLayer(pg.data_source(schema, "poles").uri(False), "poles", "postgres")
    assert layer.isValid() and layer.featureCount() == 48
    assert layer.crs().authid() == "EPSG:32643"


def test_existing_tables_are_protected_without_overwrite(pg, schema):
    load_layers({"poles": clean("poles")}, pg, schema)
    with pytest.raises(LoadError, match="already exist"):
        load_layers({"poles": clean("poles")}, pg, schema, overwrite=False)
    assert count_rows(pg, schema, "poles") == 48


def test_overwrite_replaces_the_table(pg, schema):
    load_layers({"poles": clean("poles")}, pg, schema)
    ten = clean("poles").materialize(QgsFeatureRequest().setLimit(10))
    result = load_layers({"poles": ten}, pg, schema)
    assert result.loaded == {"poles": 10} and count_rows(pg, schema, "poles") == 10


def test_failed_load_changes_nothing(pg, schema, monkeypatch):
    load_layers(clean_layers(), pg, schema)
    original = postgis_loader._swap_sql
    monkeypatch.setattr(postgis_loader, "_swap_sql",
                        lambda *a, **k: original(*a, **k) + " SELECT 1/0;")
    ten = clean("poles").materialize(QgsFeatureRequest().setLimit(10))
    with pytest.raises(LoadError, match="not changed"):
        load_layers({"poles": ten, "towers": clean("towers")}, pg, schema)

    assert count_rows(pg, schema, "poles") == 48  # old data intact: the swap rolled back
    assert count_rows(pg, schema, "towers") == 6
    assert sql(pg, f'SELECT count(*) FROM "{schema}".geomigrate_run_log') == [[3]]
    assert sql(pg, f"SELECT count(*) FROM information_schema.tables "
                   f"WHERE table_schema = '{schema}_stg'") == [[0]]


def test_connection_failure_is_a_clear_error(schema):
    bad = PgConnection(host="localhost", port=1, dbname="nope", user="x", password="x")
    with pytest.raises(LoadError, match="Could not connect"):
        load_layers({"poles": clean("poles")}, bad, schema)


def test_unsafe_names_are_refused_before_any_sql(pg):
    with pytest.raises(ValueError):
        load_layers({"poles": clean("poles")}, pg, 'x"; DROP SCHEMA public; --')
    with pytest.raises(ValueError):
        load_layers({"po les": clean("poles")}, pg, "ok_schema")
