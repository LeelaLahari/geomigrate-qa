"""Report content: summary data, HTML for the PDF, and CSV export. Pure Python (no QGIS).

All text that comes from the user's data is HTML-escaped in the PDF, and CSV cells that could
be run as formulas by a spreadsheet are defused, because feature ids come from untrusted files.
"""
import configparser
import csv
import html
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1]
MAX_DETAIL_ROWS = 200
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def plugin_version() -> str:
    parser = configparser.ConfigParser()
    try:
        parser.read(PACKAGE_DIR / "metadata.txt", encoding="utf-8")
        return parser.get("general", "version")
    except (configparser.Error, OSError):
        return "unknown"


@dataclass
class LayerSummary:
    name: str
    read: int
    clean: int
    quarantined: int
    rejected: int = 0


@dataclass
class FindingRow:
    layer: str
    rule: str
    severity: str
    feature_id: str
    field: str
    message: str
    x: float = None
    y: float = None


@dataclass
class ReportData:
    title: str
    generated_at: str
    layers: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    load_note: str = ""
    skipped: list = field(default_factory=list)
    map_note: str = ""


def report_data_from_result(result, label="", generated_at=None) -> ReportData:
    """Build report data from a MigrationResult (read-only; works with any matching object)."""
    stamp = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    data = ReportData(title=f"GeoMigrate QA report{': ' + label if label else ''}",
                      generated_at=stamp, skipped=list(result.report.skipped))
    for name, transform in result.transforms.items():
        data.layers.append(LayerSummary(
            name=name, read=transform.read, clean=result.clean[name].featureCount(),
            quarantined=len(result.quarantined[name]), rejected=len(transform.rejected)))
    for f in result.report.findings:
        x, y = f.location if f.location else (None, None)
        data.findings.append(FindingRow(
            layer=f.layer, rule=f.rule, severity=f.severity,
            feature_id="" if f.feature_id is None else str(f.feature_id),
            field=f.field or "", message=f.message, x=x, y=y))
    if result.load is not None:
        data.load_note = (f"Clean data loaded to PostGIS schema '{result.load.schema}' "
                          f"(run {result.load.run_id}, {'OK' if result.load.ok else 'MISMATCH'}).")
    else:
        data.load_note = "Dry run: nothing was written to PostGIS."
    return data


def _count_by(findings, *keys):
    counts = {}
    for row in findings:
        key = tuple(getattr(row, k) for k in keys)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _table(headers, rows, widths=None):
    head = "".join(f'<th bgcolor="#e8eef5" align="left">{_e(h)}</th>' for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>" for row in rows)
    return (f'<table border="1" cellspacing="0" cellpadding="4" width="100%">'
            f"<tr>{head}</tr>{body}</table>")


def render_report_html(data: ReportData, map_resource=None) -> str:
    errors = sum(1 for f in data.findings if f.severity == "error")
    parts = [
        f"<h1>{_e(data.title)}</h1>",
        (f"<p>Generated {_e(data.generated_at)} by GeoMigrate QA {_e(plugin_version())}.<br/>"
         f"{_e(data.load_note)}</p>"),
        "<h2>Summary</h2>",
        (f"<p><b>{len(data.findings)}</b> findings ({errors} errors). Features with errors are "
         "quarantined and not loaded; every copy of a duplicate is held back for review.</p>"),
        _table(["Layer", "Read", "Loaded clean", "Quarantined", "Rejected on import"],
               [(s.name, s.read, s.clean, s.quarantined, s.rejected) for s in data.layers]),
    ]
    if data.skipped:
        parts.append(f"<p>Not checked (no data supplied): {_e(', '.join(data.skipped))}</p>")

    parts.append("<h2>Findings by rule</h2>")
    by_rule = _count_by(data.findings, "layer", "rule", "severity")
    parts.append(_table(["Layer", "Rule", "Severity", "Count"],
                        [(*key, count) for key, count in by_rule.items()])
                 if by_rule else "<p>No findings.</p>")

    if map_resource:
        parts.append('<h2 style="page-break-before: always">Map</h2>')
        parts.append(f'<p><img src="{_e(map_resource)}" width="640"/></p>')
        parts.append("<p>Grey: clean features. Red: validation findings."
                     f"{' ' + _e(data.map_note) if data.map_note else ''}</p>")

    parts.append("<h2>Finding details</h2>")
    shown = data.findings[:MAX_DETAIL_ROWS]
    if shown:
        parts.append(_table(["Layer", "Rule", "Feature", "Field", "Message"],
                            [(f.layer, f.rule, f.feature_id, f.field, f.message)
                             for f in shown]))
        if len(data.findings) > len(shown):
            parts.append(f"<p>Showing the first {len(shown)} of {len(data.findings)}. "
                         "The CSV file has all of them.</p>")
    else:
        parts.append("<p>None.</p>")
    return "<html><body>" + "".join(parts) + "</body></html>"


def safe_cell(value):
    """Defuse text that a spreadsheet would run as a formula."""
    if isinstance(value, str) and value.startswith(_FORMULA_STARTS):
        return "'" + value
    return value


def write_csv_reports(data: ReportData, folder, stem="geomigrate_report") -> list:
    """Write <stem>_summary.csv and <stem>_findings.csv (UTF-8 with BOM so Excel opens them)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    summary_path = folder / f"{stem}_summary.csv"
    findings_path = folder / f"{stem}_findings.csv"

    with summary_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["layer", "read", "loaded_clean", "quarantined", "rejected_on_import"])
        for s in data.layers:
            writer.writerow([safe_cell(s.name), s.read, s.clean, s.quarantined, s.rejected])

    with findings_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["layer", "rule", "severity", "feature_id", "field", "message", "x", "y"])
        for f in data.findings:
            writer.writerow([safe_cell(f.layer), f.rule, f.severity, safe_cell(f.feature_id),
                             safe_cell(f.field), safe_cell(f.message),
                             "" if f.x is None else f.x, "" if f.y is None else f.y])
    return [summary_path, findings_path]
