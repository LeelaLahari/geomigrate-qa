"""End to end: import -> transform -> validate -> quarantine -> load clean data to PostGIS."""
from dataclasses import dataclass, field

from .error_layer import build_error_layer, split_by_findings
from .postgis_loader import load_layers
from .rules import validate
from .transform import import_and_transform

ERROR_TABLE = "validation_errors"


@dataclass
class MigrationResult:
    report: object
    transforms: dict = field(default_factory=dict)    # layer name -> TransformResult
    clean: dict = field(default_factory=dict)         # layer name -> clean memory layer
    quarantined: dict = field(default_factory=dict)   # layer name -> set of feature ids
    error_layer: object = None
    load: object = None                               # LoadResult, or None if not loaded


def run_migration(sources: dict, rules_config, pg=None, schema=None, *, reference=None,
                  source_label="") -> MigrationResult:
    """sources: {layer name: (file path, mapping template)}.

    reference: trusted {layer name: layer} inventory for node and extent checks.
    pg and schema: when given, clean layers and the error table are loaded to PostGIS.
    """
    transforms = {name: import_and_transform(path, template)
                  for name, (path, template) in sources.items()}
    layers = {name: result.layer for name, result in transforms.items()}
    report = validate(layers, rules_config, reference=reference)

    outcome = MigrationResult(report=report, transforms=transforms)
    for name, layer in layers.items():
        outcome.clean[name], outcome.quarantined[name] = split_by_findings(layer, report, name)

    crs = next(iter(layers.values())).crs().authid()
    outcome.error_layer = build_error_layer(report, crs, ERROR_TABLE)

    if pg is not None and schema:
        stats = {name: {"read": transforms[name].read} for name in layers}
        to_load = {**outcome.clean, ERROR_TABLE: outcome.error_layer}
        outcome.load = load_layers(to_load, pg, schema, source=source_label, stats=stats)
    return outcome
