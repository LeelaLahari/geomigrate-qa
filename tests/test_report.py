"""Report text, CSV safety and escaping. Pure Python: runs without QGIS."""
import csv

from geomigrate_qa.core.report import (
    MAX_DETAIL_ROWS,
    FindingRow,
    LayerSummary,
    ReportData,
    plugin_version,
    render_report_html,
    safe_cell,
    write_csv_reports,
)


def sample(findings=None):
    return ReportData(
        title="GeoMigrate QA report: demo", generated_at="2026-11-22 10:00",
        layers=[LayerSummary("poles", 48, 35, 13), LayerSummary("cables", 49, 38, 11, 1)],
        findings=findings if findings is not None else [
            FindingRow("poles", "duplicate_id", "error", "P001", "pole_id", "used twice", 1.5, 2.5),
            FindingRow("poles", "duplicate_id", "error", "P001", "pole_id", "used twice", 3.0, 4.0),
            FindingRow("cables", "zero_length", "warning", "55", "", "Line has zero length.")],
        load_note="Dry run: nothing was written to PostGIS.")


def test_html_has_the_headline_numbers():
    html = render_report_html(sample())
    assert "3</b> findings (2 errors)" in html
    assert "<td>poles</td><td>48</td><td>35</td><td>13</td><td>0</td>" in html
    assert "zero_length" in html and "Dry run" in html


def test_html_escapes_untrusted_text():
    nasty = FindingRow("poles", "domain", "error", "<script>alert(1)</script>", "f", "a & b <i>")
    html = render_report_html(sample([nasty]))
    assert "<script>" not in html and "&lt;script&gt;" in html and "a &amp; b &lt;i&gt;" in html


def test_empty_report_and_map_note():
    html = render_report_html(sample([]), map_resource="map.png")
    assert "No findings." in html and 'src="map.png"' in html


def test_detail_table_is_capped():
    many = [FindingRow("poles", "range", "error", str(i), "h", "bad") for i in range(MAX_DETAIL_ROWS + 5)]
    html = render_report_html(sample(many))
    assert f"first {MAX_DETAIL_ROWS} of {MAX_DETAIL_ROWS + 5}" in html


def test_safe_cell_defuses_formulas():
    assert safe_cell("=1+1") == "'=1+1"
    assert safe_cell("@SUM(A1)") == "'@SUM(A1)"
    assert safe_cell("-2+3") == "'-2+3"
    assert safe_cell("P001") == "P001" and safe_cell(5) == 5


def test_csv_files_are_written_and_safe(tmp_path):
    data = sample([FindingRow("poles", "domain", "error", "=cmd|' /C calc'!A0", "m", "bad", 1.0, 2.0)])
    summary, findings = write_csv_reports(data, tmp_path / "out", "run1")
    assert summary.name == "run1_summary.csv" and findings.name == "run1_findings.csv"
    assert findings.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM for Excel
    rows = list(csv.reader(findings.open(encoding="utf-8-sig")))
    assert rows[0] == ["layer", "rule", "severity", "feature_id", "field", "message", "x", "y"]
    assert rows[1][3].startswith("'=")
    assert list(csv.reader(summary.open(encoding="utf-8-sig")))[2] == ["cables", "49", "38", "11", "1"]


def test_plugin_version_is_a_string():
    assert isinstance(plugin_version(), str) and plugin_version()
