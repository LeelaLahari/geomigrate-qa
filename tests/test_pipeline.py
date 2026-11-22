"""End-to-end: defective files in, clean tables and an error table out (needs QGIS + PostGIS)."""
import os
import uuid
from pathlib import Path

import pytest

pytest.importorskip("qgis.core")

from qgis.core import QgsProviderConnectionException, QgsVectorLayer

from geomigrate_qa.core.error_layer import build_error_layer, split_by_findings
from geomigrate_qa.core.pipeline import ERROR_TABLE, run_migration
from geomigrate_qa.core.postgis_loader import PgConnection, count_rows
from geomigrate_qa.core.rules import validate

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_data"
TEMPLATES = ROOT / "geomigrate_qa" / "templates"
CONFIG = ROOT / "geomigrate_qa" / "rules" / "telecom_default.json"
pytestmark = pytest.mark.skipif(
    not (SAMPLE / "expected_errors.json").exists(),
    reason="run scripts/generate_sample_data.py first",
)

SOURCES = {
    "poles": (SAMPLE / "defective" / "poles.shp", TEMPLATES / "poles_shp.json"),
    "towers": (SAMPLE / "defective" / "towers.kml", TEMPLATES / "towers_kml.json"),
    "cables": (SAMPLE / "defective" / "cables.dxf", TEMPLATES / "cables_dxf.json"),
}


def clean(name):
    return QgsVectorLayer(f"{SAMPLE / 'clean' / 'network.gpkg'}|layername={name}", name, "ogr")


def reference():
    return {"poles": clean("poles"), "towers": clean("towers")}


@pytest.fixture(scope="module")
def pg():
    params = PgConnection(
        host=os.environ.get("GEOMIGRATE_PG_HOST", "localhost"),
        port=int(os.environ.get("GEOMIGRATE_PG_PORT", "5432")),
        dbname=os.environ.get("GEOMIGRATE_PG_DB", "geomigrate"),
        user=os.environ.get("GEOMIGRATE_PG_USER", "postgres"),
        password=os.environ.get("GEOMIGRATE_PG_PASSWORD", "postgres"))
    try:
        params.connect().executeSql("SELECT 1")
    except QgsProviderConnectionException as exc:
        pytest.skip(f"PostGIS not available: {exc}")
    return params


@pytest.fixture
def schema(pg):
    name = f"gm_test_{uuid.uuid4().hex[:8]}"
    yield name
    conn = pg.connect()
    conn.executeSql(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
    conn.executeSql(f'DROP SCHEMA IF EXISTS "{name}_stg" CASCADE')


def test_error_layer_has_one_row_per_finding():
    out = run_migration(SOURCES, CONFIG, reference=reference())
    layer = out.error_layer
    assert layer.featureCount() == len(out.report.findings) == 30
    assert layer.crs().authid() == "EPSG:32643"
    assert [f.name() for f in layer.fields()] == [
        "rule", "severity", "source_layer", "feature_id", "qgis_fid", "field_name", "message"]
    assert all(not f.geometry().isNull() for f in layer.getFeatures())


def test_clean_layers_exclude_every_flagged_feature():
    out = run_migration(SOURCES, CONFIG, reference=reference())
    for name, layer in out.clean.items():
        total = out.transforms[name].written
        flagged = {f.fid for f in out.report.findings if f.layer == name}
        assert layer.featureCount() == total - len(flagged)
        assert out.quarantined[name] == flagged
    # The strongest check: what we keep passes the same rules with zero findings.
    again = validate(out.clean, CONFIG, reference=reference())
    assert again.findings == [], again.count_by_rule()


def test_full_run_into_postgis(pg, schema):
    out = run_migration(SOURCES, CONFIG, pg, schema, reference=reference(), source_label="demo")
    assert out.load.ok
    for name, layer in out.clean.items():
        assert count_rows(pg, schema, name) == layer.featureCount()
    assert count_rows(pg, schema, ERROR_TABLE) == 30

    log = pg.connect().executeSql(
        f'SELECT table_name, features_read, features_loaded, features_quarantined '
        f'FROM "{schema}".geomigrate_run_log ORDER BY table_name')
    by_name = {row[0]: row[1:] for row in log}
    for name in ("poles", "towers", "cables"):
        read = out.transforms[name].read
        loaded = out.clean[name].featureCount()
        assert by_name[name] == [read, loaded, read - loaded]
    assert by_name[ERROR_TABLE][0] == 30


def test_split_with_nothing_wrong_keeps_everything():
    layer = clean("poles")
    report = validate({"poles": layer}, CONFIG, only=["poles"])
    kept, bad = split_by_findings(layer, report, "poles")
    assert kept.featureCount() == 48 and not bad
    assert build_error_layer(report, "EPSG:32643").featureCount() == 0
