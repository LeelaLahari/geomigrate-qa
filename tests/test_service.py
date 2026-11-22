"""run_from_config with a real database (skipped when PostGIS is not reachable)."""
import os
import uuid
from pathlib import Path

import pytest

pytest.importorskip("qgis.core")

from qgis.core import QgsProviderConnectionException

from geomigrate_qa.core.postgis_loader import PgConnection, count_rows
from geomigrate_qa.core.runconfig import load_run_config
from geomigrate_qa.core.service import run_from_config, summarize

SAMPLE = Path(__file__).resolve().parents[1] / "sample_data"
pytestmark = pytest.mark.skipif(
    not (SAMPLE / "demo_run.json").exists(),
    reason="run scripts/generate_sample_data.py and keep sample_data/demo_run.json",
)


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


def test_dry_run_summary_has_the_headline_numbers():
    result = run_from_config(load_run_config(SAMPLE / "demo_run.json"))
    text = summarize(result)
    assert "poles: read 48, clean 35, quarantined 13" in text
    assert "towers: read 7, clean 3, quarantined 4" in text
    assert "cables: read 49, clean 38, quarantined 11" in text
    assert "Findings: 30" in text and "Dry run" in text and result.load is None


def test_run_with_a_database_loads_and_reports(pg):
    schema = f"gm_test_{uuid.uuid4().hex[:8]}"
    try:
        result = run_from_config(load_run_config(SAMPLE / "demo_run.json"), pg, schema)
        assert result.load.ok and count_rows(pg, schema, "poles") == 35
        text = summarize(result)
        assert f"Loaded to PostGIS schema '{schema}'" in text and "OK" in text
    finally:
        conn = pg.connect()
        conn.executeSql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        conn.executeSql(f'DROP SCHEMA IF EXISTS "{schema}_stg" CASCADE')
