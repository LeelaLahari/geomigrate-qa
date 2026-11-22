"""PDF and map rendering with real migration results (needs QGIS)."""
from pathlib import Path

import pytest

pytest.importorskip("qgis.core")

from qgis.core import QgsVectorLayer

from geomigrate_qa.core.pipeline import run_migration
from geomigrate_qa.core.report_pdf import export_reports, render_map_image

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_data"
TEMPLATES = ROOT / "geomigrate_qa" / "templates"
CONFIG = ROOT / "geomigrate_qa" / "rules" / "telecom_default.json"
pytestmark = pytest.mark.skipif(
    not (SAMPLE / "expected_errors.json").exists(),
    reason="run scripts/generate_sample_data.py first",
)


@pytest.fixture(scope="module")
def result():
    sources = {
        "poles": (SAMPLE / "defective" / "poles.shp", TEMPLATES / "poles_shp.json"),
        "towers": (SAMPLE / "defective" / "towers.kml", TEMPLATES / "towers_kml.json"),
        "cables": (SAMPLE / "defective" / "cables.dxf", TEMPLATES / "cables_dxf.json"),
    }
    gpkg = SAMPLE / "clean" / "network.gpkg"
    reference = {n: QgsVectorLayer(f"{gpkg}|layername={n}", n, "ogr") for n in ("poles", "towers")}
    return run_migration(sources, CONFIG, reference=reference)


def test_map_image_is_drawn_and_counts_off_map_findings(result):
    image, outside = render_map_image(result)
    assert image.width() == 900 and image.height() == 560
    colours = {image.pixelColor(x, y).name() for x in range(0, 900, 6) for y in range(0, 560, 6)}
    assert "#d62728" in colours and "#ffffff" in colours  # red findings on a white page
    assert outside == 1  # the lat/lon-swapped tower is hundreds of kilometres away


def test_map_rendering_leaves_layer_styles_untouched(result):
    before = result.error_layer.renderer().symbol().color().name()
    render_map_image(result)
    assert result.error_layer.renderer().symbol().color().name() == before


def test_export_writes_pdf_and_csvs(result, tmp_path):
    paths = export_reports(result, tmp_path / "reports", stem="demo", label="demo run")
    names = sorted(p.name for p in paths)
    assert names == ["demo.pdf", "demo_findings.csv", "demo_summary.csv"]
    pdf = (tmp_path / "reports" / "demo.pdf").read_bytes()
    assert pdf.startswith(b"%PDF") and len(pdf) > 5_000
    findings = (tmp_path / "reports" / "demo_findings.csv").read_text(encoding="utf-8-sig")
    assert len(findings.strip().splitlines()) == 31  # header + 30 findings
