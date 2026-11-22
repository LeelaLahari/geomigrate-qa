"""The dialog, driven in code on an offscreen Qt (no window is shown)."""
from pathlib import Path

import pytest

pytest.importorskip("qgis.core")

from qgis.core import QgsProject

from geomigrate_qa.core.runconfig import load_run_config
from geomigrate_qa.gui.dialog import MigrationDialog

SAMPLE = Path(__file__).resolve().parents[1] / "sample_data"
pytestmark = pytest.mark.skipif(
    not (SAMPLE / "demo_run.json").exists(),
    reason="run scripts/generate_sample_data.py and keep sample_data/demo_run.json",
)


@pytest.fixture
def dialog(qgis_app):
    project = QgsProject()
    dlg = MigrationDialog(project=project)
    yield dlg
    dlg.close()


def test_loading_a_configuration_fills_the_form(dialog):
    dialog.load_config_from(SAMPLE / "demo_run.json")
    assert dialog.table.rowCount() == 3
    assert dialog.table.item(0, 0).text() == "poles"
    assert dialog.table.cellWidget(0, 1).text().endswith("poles.shp")
    assert dialog.schema.text() == "demo"
    assert dialog.reference.text().endswith("network.gpkg")


def test_form_round_trips_through_a_saved_file(dialog, tmp_path):
    dialog.load_config_from(SAMPLE / "demo_run.json")
    out = tmp_path / "saved.json"
    dialog.save_config_to(out)
    assert out.exists() and "password" not in out.read_text().lower()
    original = load_run_config(SAMPLE / "demo_run.json")
    again = load_run_config(out, check=False)
    assert [s.name for s in again.sources] == [s.name for s in original.sources]
    assert again.schema == original.schema


def test_dry_run_shows_a_summary_and_adds_layers(dialog):
    dialog.load_config_from(SAMPLE / "demo_run.json")
    result = dialog.run()
    assert result is not None and len(result.report.findings) == 30
    text = dialog.output.toPlainText()
    assert "Findings: 30" in text and "Dry run" in text
    names = {layer.name() for layer in dialog.project.mapLayers().values()}
    assert names == {"poles (clean)", "towers (clean)", "cables (clean)", "validation_errors"}


def test_problems_are_shown_not_raised(dialog):
    dialog.add_row("bad name", "missing.shp", "bundled:poles_shp.json")
    assert dialog.run() is None
    text = dialog.output.toPlainText()
    assert text.startswith("ERROR") and "data file not found" in text


def test_postgis_needs_a_schema(dialog):
    dialog.load_config_from(SAMPLE / "demo_run.json")
    dialog.schema.setText("")
    dialog.load_box.setChecked(True)
    assert dialog.run() is None
    assert "target schema" in dialog.output.toPlainText()


def test_export_needs_a_run_first_then_writes_files(dialog, tmp_path):
    assert dialog.export_report_to(tmp_path) == []
    assert "Run a migration first" in dialog.output.toPlainText()
    assert not dialog.export_button.isEnabled()

    dialog.load_config_from(SAMPLE / "demo_run.json")
    dialog.run()
    assert dialog.export_button.isEnabled()
    paths = dialog.export_report_to(tmp_path)
    assert {p.suffix for p in paths} == {".pdf", ".csv"}
    assert "Report written" in dialog.output.toPlainText()
