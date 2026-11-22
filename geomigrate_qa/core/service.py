"""Run a RunConfig and describe the outcome. Shared by the dialog and the Processing algorithm."""
from .importer import open_dataset
from .pipeline import run_migration


def load_reference(gpkg_path) -> dict:
    """Layers of a trusted GeoPackage inventory, keyed by plain layer name."""
    opened = open_dataset(gpkg_path)
    return {item.name.split(" / ")[-1]: item.layer for item in opened.layers}


def run_from_config(config, pg=None, schema=None):
    """Run the whole migration. Loads to PostGIS only when pg and a schema are given."""
    sources = {s.name: (s.file, s.template) for s in config.sources}
    reference = load_reference(config.reference_gpkg) if config.reference_gpkg else None
    target = schema or config.schema
    return run_migration(sources, config.rules, pg if target else None, target,
                         reference=reference, source_label=config.label)


def summarize(result) -> str:
    lines = []
    for name, transform in result.transforms.items():
        clean = result.clean[name].featureCount()
        lines.append(f"{name}: read {transform.read}, clean {clean}, "
                     f"quarantined {len(result.quarantined[name])}"
                     + (f", rejected on import {len(transform.rejected)}" if transform.rejected
                        else ""))
    findings = result.report.findings
    errors = sum(1 for f in findings if f.severity == "error")
    lines.append(f"Findings: {len(findings)} ({errors} errors, {len(findings) - errors} other)")
    for (layer, rule), count in sorted(result.report.count_by_rule().items()):
        lines.append(f"  {layer} / {rule}: {count}")
    if result.report.skipped:
        lines.append(f"Not checked (no data supplied): {', '.join(result.report.skipped)}")
    if result.load is not None:
        loaded = ", ".join(f"{t} {n}" for t, n in result.load.loaded.items())
        status = "OK" if result.load.ok else "MISMATCH"
        lines.append(f"Loaded to PostGIS schema '{result.load.schema}' "
                     f"(run {result.load.run_id}, {status}): {loaded}")
    else:
        lines.append("Dry run: nothing was written to PostGIS.")
    return "\n".join(lines)
