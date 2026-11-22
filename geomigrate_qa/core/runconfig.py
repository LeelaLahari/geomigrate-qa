"""Run configuration: which files, templates and rules make up one migration run.

Pure Python (no QGIS), so CI can test it. Saved as JSON so a run can be repeated, shared,
or started from the command line. Paths in a file are relative to that file, and
"bundled:name.json" points at a template or rule set shipped with the plugin. Passwords are
never stored here.
"""
import json
from dataclasses import dataclass
from pathlib import Path

from .sqlutil import quote_ident

PACKAGE_DIR = Path(__file__).resolve().parents[1]
BUNDLED = "bundled:"
_FOLDERS = {"template": "templates", "rules": "rules"}
DEFAULT_RULES = BUNDLED + "telecom_default.json"


class RunConfigError(ValueError):
    """The run configuration is malformed or points at files that do not exist."""


@dataclass(frozen=True)
class SourceEntry:
    name: str
    file: str
    template: str


@dataclass(frozen=True)
class RunConfig:
    sources: tuple
    rules: str = DEFAULT_RULES
    reference_gpkg: str = None
    schema: str = None
    label: str = ""


def bundled_names(kind: str) -> list:
    folder = PACKAGE_DIR / _FOLDERS[kind]
    return sorted(BUNDLED + p.name for p in folder.glob("*.json"))


def resolve_path(value: str, base: Path, kind: str = "template") -> Path:
    if value.startswith(BUNDLED):
        return PACKAGE_DIR / _FOLDERS[kind] / value[len(BUNDLED):]
    path = Path(value)
    return path if path.is_absolute() else Path(base) / path


def portable_path(path, base: Path, kind: str = "template") -> str:
    """Shortest stable way to write a path into a saved config."""
    path = Path(path)
    bundled_dir = PACKAGE_DIR / _FOLDERS[kind]
    if path.parent == bundled_dir:
        return BUNDLED + path.name
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return str(path)


def check_config(config: RunConfig) -> list:
    """Return a list of human-readable problems (empty when the config is usable)."""
    problems = []
    if not config.sources:
        problems.append("Add at least one source file.")
    seen = set()
    for source in config.sources:
        try:
            quote_ident(source.name)
        except ValueError:
            problems.append(f"Layer name {source.name!r} must use letters, digits and "
                            "underscores only (it becomes the table name).")
        if source.name in seen:
            problems.append(f"Layer name '{source.name}' is used twice.")
        seen.add(source.name)
        if not Path(source.file).is_file():
            problems.append(f"{source.name}: data file not found: {source.file}")
        if not Path(source.template).is_file():
            problems.append(f"{source.name}: mapping template not found: {source.template}")
    if not Path(config.rules).is_file():
        problems.append(f"Rule set not found: {config.rules}")
    if config.reference_gpkg and not Path(config.reference_gpkg).is_file():
        problems.append(f"Reference GeoPackage not found: {config.reference_gpkg}")
    if config.schema:
        try:
            quote_ident(config.schema)
        except ValueError:
            problems.append(f"Schema name {config.schema!r} must use letters, digits and "
                            "underscores only.")
    return problems


def parse_run_config(data: dict, base: Path, check=True) -> RunConfig:
    if not isinstance(data, dict) or not isinstance(data.get("sources"), dict):
        raise RunConfigError("A run configuration needs a 'sources' section.")
    sources = []
    for name, entry in data["sources"].items():
        if not isinstance(entry, dict) or "file" not in entry or "template" not in entry:
            raise RunConfigError(f"Source '{name}' needs both 'file' and 'template'.")
        sources.append(SourceEntry(
            name=name,
            file=str(resolve_path(entry["file"], base, "template")),
            template=str(resolve_path(entry["template"], base, "template"))))
    reference = data.get("reference_gpkg")
    config = RunConfig(
        sources=tuple(sources),
        rules=str(resolve_path(data.get("rules", DEFAULT_RULES), base, "rules")),
        reference_gpkg=str(resolve_path(reference, base)) if reference else None,
        schema=data.get("schema") or None,
        label=data.get("label", ""))
    if check:
        problems = check_config(config)
        if problems:
            raise RunConfigError("\n".join(problems))
    return config


def load_run_config(path, check=True) -> RunConfig:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RunConfigError(f"Run configuration not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise RunConfigError(f"{path.name} is not valid JSON: {exc}") from None
    return parse_run_config(data, path.parent.resolve(), check)


def save_run_config(config: RunConfig, path) -> None:
    path = Path(path)
    base = path.parent.resolve()
    data = {
        "label": config.label,
        "sources": {
            s.name: {"file": portable_path(s.file, base), "template": portable_path(s.template, base)}
            for s in config.sources},
        "rules": portable_path(config.rules, base, "rules"),
    }
    if config.reference_gpkg:
        data["reference_gpkg"] = portable_path(config.reference_gpkg, base)
    if config.schema:
        data["schema"] = config.schema
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
