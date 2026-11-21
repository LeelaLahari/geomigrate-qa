"""Mapping templates and value conversion. Pure Python: no QGIS imports, so CI can test it.

A template (JSON) describes how one source layer becomes one target layer:
the target CRS and geometry type, plus one entry per target field.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

GEOMETRY_TYPES = {"Point", "Line", "Polygon"}
FIELD_TYPES = {"string", "int", "double"}
COMPUTE_KINDS = {"length", "area"}
TRANSFORMS = {"strip": str.strip, "upper": str.upper, "lower": str.lower}
CRS_PATTERN = re.compile(r"^[A-Za-z]+:\d+$")

# Problem codes reported by convert_value
UNMAPPED = "unmapped_value"
CAST_FAILED = "cast_failed"


class MappingError(ValueError):
    """The template is malformed, or does not fit the source layer."""


@dataclass(frozen=True)
class FieldMap:
    target: str
    type: str
    source: str = None
    transforms: tuple = ()
    value_map: dict = None
    default: object = None
    compute: str = None


@dataclass(frozen=True)
class Template:
    name: str
    target_layer: str
    target_crs: str
    geometry_type: str
    fields: tuple
    assume_source_crs: str = None


def parse_template(data: dict) -> Template:
    if not isinstance(data, dict):
        raise MappingError("Template must be a JSON object.")
    for key in ("name", "target_layer", "target_crs", "geometry_type", "fields"):
        if key not in data:
            raise MappingError(f"Template is missing '{key}'.")
    for key in ("target_crs", "assume_source_crs"):
        if data.get(key) and not CRS_PATTERN.match(data[key]):
            raise MappingError(f"'{key}' must look like EPSG:32643, got {data[key]!r}.")
    if data["geometry_type"] not in GEOMETRY_TYPES:
        raise MappingError(f"geometry_type must be one of {sorted(GEOMETRY_TYPES)}.")
    if not data["fields"]:
        raise MappingError("Template needs at least one field.")

    fields, seen = [], set()
    for raw in data["fields"]:
        target = raw.get("target")
        if not target:
            raise MappingError("Every field needs a 'target' name.")
        if target in seen:
            raise MappingError(f"Duplicate target field '{target}'.")
        seen.add(target)
        if raw.get("type") not in FIELD_TYPES:
            raise MappingError(f"Field '{target}': type must be one of {sorted(FIELD_TYPES)}.")
        unknown = [t for t in raw.get("transforms", []) if t not in TRANSFORMS]
        if unknown:
            raise MappingError(f"Field '{target}': unknown transform(s) {unknown}.")
        if raw.get("compute") and raw["compute"] not in COMPUTE_KINDS:
            raise MappingError(f"Field '{target}': compute must be one of {sorted(COMPUTE_KINDS)}.")
        if raw.get("compute") and raw.get("source"):
            raise MappingError(f"Field '{target}': use either 'source' or 'compute', not both.")
        fields.append(FieldMap(
            target=target, type=raw["type"], source=raw.get("source"),
            transforms=tuple(raw.get("transforms", [])), value_map=raw.get("value_map"),
            default=raw.get("default"), compute=raw.get("compute")))

    return Template(
        name=data["name"], target_layer=data["target_layer"], target_crs=data["target_crs"],
        geometry_type=data["geometry_type"], fields=tuple(fields),
        assume_source_crs=data.get("assume_source_crs"))


def load_template(source) -> Template:
    """Load from a dict or a path to a JSON file."""
    if isinstance(source, dict):
        return parse_template(source)
    path = Path(source)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise MappingError(f"Template file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise MappingError(f"{path.name} is not valid JSON: {exc}") from None
    return parse_template(data)


def cast_value(value, type_name):
    """Return (converted_value, ok). None passes through as (None, True)."""
    if value is None:
        return None, True
    try:
        if type_name == "string":
            return str(value), True
        if type_name == "double":
            return float(value), True
        number = float(value)
        if number != int(number):
            return None, False
        return int(number), True
    except (TypeError, ValueError, OverflowError):
        return None, False


def convert_value(raw, field_map: FieldMap):
    """Clean, map, cast and default one value. Returns (value, problem_code_or_None)."""
    value = raw
    if isinstance(value, str):
        for name in field_map.transforms:
            value = TRANSFORMS[name](value)
        if value == "":
            value = None

    problem = None
    if value is not None and field_map.value_map is not None:
        key = str(value)
        if key in field_map.value_map:
            value = field_map.value_map[key]
        else:
            value, problem = None, UNMAPPED

    if value is not None and problem is None:
        value, ok = cast_value(value, field_map.type)
        if not ok:
            problem = CAST_FAILED

    if value is None and field_map.default is not None:
        value, _ = cast_value(field_map.default, field_map.type)
    return value, problem
