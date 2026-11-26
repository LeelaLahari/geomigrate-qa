"""Build the plugin zip for plugins.qgis.org (and for "Install from ZIP" in QGIS).

Run from the repo root:  python scripts/package_plugin.py
Checks the metadata against the repository's rules, copies LICENSE into the plugin folder,
leaves out caches and tests, and writes dist/<plugin>-<version>.zip. Needs no QGIS.
"""
import configparser
import re
import sys
import zipfile
from pathlib import Path

PLUGIN_DIR_NAME = "geomigrate_qa"
REQUIRED = ("name", "qgisMinimumVersion", "description", "about", "version", "author",
            "email", "repository")
RECOMMENDED = ("tracker", "homepage", "tags", "icon", "category")
EXCLUDED_DIRS = {"__pycache__", ".git", ".pytest_cache", ".ruff_cache", ".vscode"}
EXCLUDED_NAMES = {".gitignore", ".DS_Store", "Thumbs.db"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
LICENSE_CANDIDATES = ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING")
FOLDER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+(\.\d+)?([.+-][0-9A-Za-z.]+)?$")


class PackagingError(Exception):
    """The plugin cannot be packaged as it is; the message says what to fix."""


def read_metadata(path) -> dict:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # keep key capitalisation (qgisMinimumVersion)
    try:
        parser.read(path, encoding="utf-8")
        return dict(parser["general"])
    except (configparser.Error, KeyError, OSError) as exc:
        raise PackagingError(f"Cannot read {path}: {exc}") from exc


def check_metadata(meta: dict, plugin_dir: Path):
    """Return (errors, warnings) as lists of messages."""
    errors, warnings = [], []
    for key in REQUIRED:
        if not meta.get(key, "").strip():
            errors.append(f"metadata.txt is missing required field '{key}'.")
    if meta.get("version") and not VERSION_PATTERN.match(meta["version"]):
        errors.append(f"version {meta['version']!r} should look like 0.1.0.")
    if not FOLDER_PATTERN.match(plugin_dir.name):
        errors.append(f"Folder name {plugin_dir.name!r} may only use letters, digits, _ and -, "
                      "and cannot start with a digit.")
    if meta.get("icon") and not (plugin_dir / meta["icon"]).is_file():
        errors.append(f"icon file {meta['icon']!r} listed in metadata.txt does not exist.")
    if "plugin" in meta.get("name", "").lower():
        warnings.append("Avoid repeating 'plugin' in the plugin name.")
    for key in RECOMMENDED:
        if not meta.get(key, "").strip():
            warnings.append(f"metadata.txt has no '{key}' (recommended).")
    if meta.get("experimental", "").lower() not in ("true", "false", ""):
        errors.append("experimental must be True or False.")
    return errors, warnings


def find_license(repo_root: Path) -> Path:
    for name in LICENSE_CANDIDATES:
        candidate = repo_root / name
        if candidate.is_file():
            return candidate
    raise PackagingError("No LICENSE file found in the repository root. The plugin repository "
                         "requires one (saved as LICENSE, no extension, inside the zip).")


def _included(path: Path) -> bool:
    parts = set(path.parts)
    return not (parts & EXCLUDED_DIRS or path.name in EXCLUDED_NAMES
                or path.suffix in EXCLUDED_SUFFIXES)


def build_package(repo_root, out_dir=None) -> tuple:
    """Return (zip path, warnings). Raises PackagingError when the plugin is not ready."""
    repo_root = Path(repo_root)
    plugin_dir = repo_root / PLUGIN_DIR_NAME
    if not plugin_dir.is_dir():
        raise PackagingError(f"Plugin folder not found: {plugin_dir}")
    meta = read_metadata(plugin_dir / "metadata.txt")
    errors, warnings = check_metadata(meta, plugin_dir)
    if not (plugin_dir / "__init__.py").is_file():
        errors.append("__init__.py is missing from the plugin folder.")
    license_file = find_license(repo_root)
    if errors:
        raise PackagingError("\n".join(errors))

    out_dir = Path(out_dir) if out_dir else repo_root / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{PLUGIN_DIR_NAME}-{meta['version']}.zip"
    files = sorted(p for p in plugin_dir.rglob("*")
                   if p.is_file() and _included(p.relative_to(plugin_dir))
                   and p.name not in ("LICENSE",))
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, f"{PLUGIN_DIR_NAME}/{path.relative_to(plugin_dir).as_posix()}")
        archive.write(license_file, f"{PLUGIN_DIR_NAME}/LICENSE")
    return target, warnings


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        target, warnings = build_package(root)
    except PackagingError as exc:
        print(f"Cannot package the plugin:\n{exc}", file=sys.stderr)
        return 1
    for message in warnings:
        print(f"warning: {message}")
    with zipfile.ZipFile(target) as archive:
        print(f"Wrote {target} ({target.stat().st_size // 1024} KB, "
              f"{len(archive.namelist())} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
