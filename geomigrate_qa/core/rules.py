"""Rule engine: run configured checks over layers and report every finding.

Rules only report; they never change data. Each Finding carries the layer, the QGIS feature
id, the business id (e.g. pole_id) and a human-readable message, so the error layer and the
PDF/CSV report can be built from the same list.
"""
import math
from collections import defaultdict
from dataclasses import dataclass, field

from qgis.core import NULL, QgsRectangle

from .rule_config import RuleConfigError, load_rule_config


@dataclass
class Finding:
    rule: str
    severity: str
    layer: str
    fid: int
    feature_id: object
    message: str
    field: str = None
    location: tuple = None  # (x, y) in the layer's CRS, for the error layer


@dataclass
class ValidationReport:
    findings: list = field(default_factory=list)
    checked: dict = field(default_factory=dict)  # layer name -> features checked
    skipped: list = field(default_factory=list)  # layers named in the config but not supplied

    def of(self, rule=None, layer=None, field_name=None):
        return [f for f in self.findings
                if (rule is None or f.rule == rule)
                and (layer is None or f.layer == layer)
                and (field_name is None or f.field == field_name)]

    def fids(self, rule, layer, field_name=None):
        return {f.fid for f in self.of(rule, layer, field_name)}

    def feature_ids(self, rule, layer, field_name=None):
        return {f.feature_id for f in self.of(rule, layer, field_name)}

    def count_by_rule(self):
        counts = defaultdict(int)
        for f in self.findings:
            counts[(f.layer, f.rule)] += 1
        return dict(counts)

    @property
    def error_count(self):
        return sum(1 for f in self.findings if f.severity == "error")


class _Context:
    def __init__(self, layers, tolerance, reference=None):
        self.layers = layers
        # Node and extent lookups prefer a trusted reference inventory over the data being checked.
        self.lookup = {**layers, **(reference or {})}
        self.tolerance = tolerance
        self.decimals = max(0, round(-math.log10(tolerance)))


def _blank(value):
    return value is None or value == NULL or (isinstance(value, str) and not value.strip())


def _business_id(feature, id_field):
    if not id_field:
        return None
    value = feature[id_field]
    return None if _blank(value) else value


def _make(spec, layer_name, feature, id_field, message, field_name=None, location=None):
    return Finding(rule=spec.rule, severity=spec.severity, layer=layer_name, fid=feature.id(),
                   feature_id=_business_id(feature, id_field), message=message,
                   field=field_name, location=location)


def _point_of(geometry):
    if geometry.isNull() or geometry.isEmpty():
        return None
    point = geometry.centroid().asPoint()
    return (point.x(), point.y())


def _line_ends(geometry):
    if geometry.isMultipart():
        parts = geometry.asMultiPolyline()
    else:
        parts = [geometry.asPolyline()]
    return [p for part in parts if part for p in (part[0], part[-1])]


def _geometry_key(geometry, decimals):
    kind = geometry.type().name
    if kind == "Point" and not geometry.isMultipart():
        p = geometry.asPoint()
        return (round(p.x(), decimals), round(p.y(), decimals))
    if kind == "Line" and not geometry.isMultipart():
        pts = tuple((round(p.x(), decimals), round(p.y(), decimals))
                    for p in geometry.asPolyline())
        return min(pts, pts[::-1])  # a cable drawn the other way round is still a duplicate
    return geometry.asWkt(decimals)


# ---- rules: each returns a list of Finding ----

def rule_null_required(ctx, name, layer, spec, id_field):
    out = []
    for feature in layer.getFeatures():
        for fname in spec.params["fields"]:
            if _blank(feature[fname]):
                out.append(_make(spec, name, feature, id_field,
                                 f"Required field '{fname}' is empty.", fname,
                                 _point_of(feature.geometry())))
    return out


def rule_duplicate_id(ctx, name, layer, spec, id_field):
    fname = spec.params["field"]
    groups = defaultdict(list)
    for feature in layer.getFeatures():
        if not _blank(feature[fname]):
            groups[feature[fname]].append(feature)
    return [_make(spec, name, f, id_field, f"{fname} '{value}' is used by {len(members)} features.",
                  fname, _point_of(f.geometry()))
            for value, members in groups.items() if len(members) > 1 for f in members]


def rule_domain(ctx, name, layer, spec, id_field):
    fname, allowed = spec.params["field"], set(spec.params["allowed"])
    return [_make(spec, name, f, id_field,
                  f"'{f[fname]}' is not an allowed {fname} (allowed: {sorted(allowed)}).",
                  fname, _point_of(f.geometry()))
            for f in layer.getFeatures() if not _blank(f[fname]) and f[fname] not in allowed]


def rule_range(ctx, name, layer, spec, id_field):
    p = spec.params
    fname = p["field"]
    lo, hi = p.get("min"), p.get("max")
    lo_in, hi_in = p.get("min_inclusive", True), p.get("max_inclusive", True)
    out = []
    for f in layer.getFeatures():
        value = f[fname]
        if _blank(value):
            continue
        too_low = lo is not None and (value < lo or (value == lo and not lo_in))
        too_high = hi is not None and (value > hi or (value == hi and not hi_in))
        if too_low or too_high:
            out.append(_make(spec, name, f, id_field, f"{fname}={value} is outside the allowed "
                             f"range (min {lo}, max {hi}).", fname, _point_of(f.geometry())))
    return out


def rule_duplicate_geometry(ctx, name, layer, spec, id_field):
    groups = defaultdict(list)
    for f in layer.getFeatures():
        if not f.geometry().isNull() and not f.geometry().isEmpty():
            groups[_geometry_key(f.geometry(), ctx.decimals)].append(f)
    return [_make(spec, name, f, id_field,
                  f"Same geometry as {len(members) - 1} other feature(s).", None,
                  _point_of(f.geometry()))
            for members in groups.values() if len(members) > 1 for f in members]


def rule_zero_length(ctx, name, layer, spec, id_field):
    return [_make(spec, name, f, id_field, "Line has zero length.", None, _point_of(f.geometry()))
            for f in layer.getFeatures()
            if not f.geometry().isNull() and f.geometry().length() <= ctx.tolerance]


def rule_invalid_geometry(ctx, name, layer, spec, id_field):
    out = []
    for f in layer.getFeatures():
        g = f.geometry()
        if g.isNull() or g.isEmpty():
            out.append(_make(spec, name, f, id_field, "Feature has no geometry."))
        elif g.type().name == "Line" and g.length() <= ctx.tolerance:
            continue  # reported by zero_length
        elif not g.isGeosValid():
            out.append(_make(spec, name, f, id_field, "Geometry is invalid.", None,
                             _point_of(g)))
    return out


def _node_grid(ctx, node_layers, cell):
    grid = defaultdict(list)
    for node_name in node_layers:
        if node_name not in ctx.lookup:
            raise RuleConfigError(f"Layer '{node_name}' is needed as a node layer but was "
                                  "not supplied.")
        for f in ctx.lookup[node_name].getFeatures():
            if f.geometry().isNull():
                continue
            p = f.geometry().asPoint()
            grid[(math.floor(p.x() / cell), math.floor(p.y() / cell))].append(p)
    return grid


def _near_node(grid, point, cell, tolerance):
    cx, cy = math.floor(point.x() / cell), math.floor(point.y() / cell)
    return any(point.distance(n) <= tolerance
               for dx in (-1, 0, 1) for dy in (-1, 0, 1)
               for n in grid.get((cx + dx, cy + dy), ()))


def rule_dangling_end(ctx, name, layer, spec, id_field):
    tolerance = spec.params.get("tolerance_m", 0.05)
    cell = max(tolerance, 1e-6)
    grid = _node_grid(ctx, spec.params["nodes"], cell)
    out = []
    for f in layer.getFeatures():
        if f.geometry().isNull():
            continue
        loose = [p for p in _line_ends(f.geometry()) if not _near_node(grid, p, cell, tolerance)]
        if loose:
            out.append(_make(spec, name, f, id_field,
                             f"{len(loose)} line end(s) not connected to any "
                             f"{'/'.join(spec.params['nodes'])} node.", None,
                             (loose[0].x(), loose[0].y())))
    return out


def rule_out_of_extent(ctx, name, layer, spec, id_field):
    ref = spec.params["reference_layer"]
    if ref not in ctx.lookup:
        raise RuleConfigError(f"Reference layer '{ref}' was not supplied.")
    box = QgsRectangle()
    for f in ctx.lookup[ref].getFeatures():
        if not f.geometry().isNull():
            box.combineExtentWith(f.geometry().boundingBox())
    if box.isNull():
        raise RuleConfigError(f"Reference layer '{ref}' has no geometry to build an extent from.")
    box = box.buffered(spec.params.get("buffer_m", 500))
    return [_make(spec, name, f, id_field, f"Located outside the expected area around '{ref}'.",
                  None, _point_of(f.geometry()))
            for f in layer.getFeatures()
            if not f.geometry().isNull() and not box.contains(f.geometry().boundingBox())]


def rule_length_mismatch(ctx, name, layer, spec, id_field):
    fname = spec.params["field"]
    tolerance = spec.params.get("tolerance_m", 0.05)
    out = []
    for f in layer.getFeatures():
        if _blank(f[fname]) or f.geometry().isNull():
            continue
        actual = f.geometry().length()
        if abs(f[fname] - actual) > tolerance:
            out.append(_make(spec, name, f, id_field,
                             f"{fname}={f[fname]} but the geometry is {actual:.2f} m long.",
                             fname, _point_of(f.geometry())))
    return out


RULES = {
    "null_required": rule_null_required,
    "duplicate_id": rule_duplicate_id,
    "domain": rule_domain,
    "range": rule_range,
    "duplicate_geometry": rule_duplicate_geometry,
    "zero_length": rule_zero_length,
    "invalid_geometry": rule_invalid_geometry,
    "dangling_end": rule_dangling_end,
    "out_of_extent": rule_out_of_extent,
    "length_mismatch": rule_length_mismatch,
}


def validate(layers: dict, config, only=None, reference=None) -> ValidationReport:
    """Run the configured rules.

    layers: {layer name: QgsVectorLayer}. only: restrict checking to these layer names
    (other supplied layers can still be used as node or reference layers).
    reference: optional {layer name: QgsVectorLayer} trusted inventory used for node and
    extent lookups instead of the layers being checked.
    """
    config = load_rule_config(config)
    ctx = _Context(layers, config.tolerance_m, reference)
    report = ValidationReport()
    for layer_rules in config.layers:
        name = layer_rules.layer
        if only is not None and name not in only:
            continue
        if name not in layers:
            report.skipped.append(name)
            continue
        report.checked[name] = layers[name].featureCount()
        for spec in layer_rules.rules:
            report.findings.extend(
                RULES[spec.rule](ctx, name, layers[name], spec, layer_rules.id_field))
    return report
