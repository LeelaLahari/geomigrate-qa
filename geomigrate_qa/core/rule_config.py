"""Rule configuration: load and validate. Pure Python (no QGIS), so CI can test it.

A config says which rules run on which layer, with which parameters and severity.
Typos in rule names or parameter names are errors, not silent no-ops.
"""
import json
from dataclasses import dataclass
from pathlib import Path

SEVERITIES = ("error", "warning", "info")

# rule name -> (required params, optional params). "severity" is allowed on every rule.
RULE_PARAMS = {
    "null_required": (("fields",), ()),
    "duplicate_id": (("field",), ()),
    "domain": (("field", "allowed"), ()),
    "range": (("field",), ("min", "max", "min_inclusive", "max_inclusive")),
    "duplicate_geometry": ((), ()),
    "zero_length": ((), ()),
    "invalid_geometry": ((), ()),
    "dangling_end": (("nodes",), ("tolerance_m",)),
    "out_of_extent": (("reference_layer",), ("buffer_m",)),
    "length_mismatch": (("field",), ("tolerance_m",)),
}


class RuleConfigError(ValueError):
    """The rule configuration is malformed or refers to something that does not exist."""


@dataclass(frozen=True)
class RuleSpec:
    rule: str
    severity: str
    params: dict


@dataclass(frozen=True)
class LayerRules:
    layer: str
    id_field: str
    rules: tuple


@dataclass(frozen=True)
class RuleConfig:
    name: str
    tolerance_m: float
    layers: tuple


def parse_rule_config(data: dict) -> RuleConfig:
    if not isinstance(data, dict) or "layers" not in data:
        raise RuleConfigError("Rule config must be an object with a 'layers' section.")
    tolerance = data.get("tolerance_m", 0.01)
    if not isinstance(tolerance, (int, float)) or tolerance <= 0:
        raise RuleConfigError("'tolerance_m' must be a positive number.")

    layers = []
    for layer_name, body in data["layers"].items():
        specs = []
        for raw in body.get("rules", []):
            name = raw.get("rule")
            if name not in RULE_PARAMS:
                raise RuleConfigError(
                    f"Layer '{layer_name}': unknown rule {name!r}. Known: {sorted(RULE_PARAMS)}.")
            required, optional = RULE_PARAMS[name]
            params = {k: v for k, v in raw.items() if k not in ("rule", "severity")}
            missing = [p for p in required if p not in params]
            if missing:
                raise RuleConfigError(f"Layer '{layer_name}', rule '{name}': missing {missing}.")
            unknown = [p for p in params if p not in required and p not in optional]
            if unknown:
                raise RuleConfigError(
                    f"Layer '{layer_name}', rule '{name}': unknown parameter(s) {unknown}.")
            severity = raw.get("severity", "error")
            if severity not in SEVERITIES:
                raise RuleConfigError(f"Layer '{layer_name}', rule '{name}': "
                                      f"severity must be one of {SEVERITIES}.")
            specs.append(RuleSpec(rule=name, severity=severity, params=params))
        layers.append(LayerRules(layer=layer_name, id_field=body.get("id_field"),
                                 rules=tuple(specs)))
    return RuleConfig(name=data.get("name", "unnamed"), tolerance_m=float(tolerance),
                      layers=tuple(layers))


def load_rule_config(source) -> RuleConfig:
    """Load from a dict or a path to a JSON file."""
    if isinstance(source, RuleConfig):
        return source
    if isinstance(source, dict):
        return parse_rule_config(source)
    path = Path(source)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuleConfigError(f"Rule config not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise RuleConfigError(f"{path.name} is not valid JSON: {exc}") from None
    return parse_rule_config(data)
