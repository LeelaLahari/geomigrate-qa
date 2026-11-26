"""The plugin zip must follow the plugin repository's rules. Pure Python: runs without QGIS."""
import importlib.util
import shutil
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("package_plugin", ROOT / "scripts" / "package_plugin.py")
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


@pytest.fixture
def repo(tmp_path):
    """A throw-away copy of the plugin with a LICENSE, so tests never touch the real repo."""
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "geomigrate_qa", root / "geomigrate_qa",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (root / "LICENSE").write_text("licence text")
    return root


def build(repo, tmp_path):
    return packager.build_package(repo, tmp_path / "dist")


def test_zip_has_one_top_level_folder_and_the_mandatory_files(repo, tmp_path):
    target, _ = build(repo, tmp_path)
    names = zipfile.ZipFile(target).namelist()
    assert {n.split("/")[0] for n in names} == {"geomigrate_qa"}
    for required in ("metadata.txt", "__init__.py", "LICENSE", "icon.png"):
        assert f"geomigrate_qa/{required}" in names
    version = packager.read_metadata(repo / "geomigrate_qa" / "metadata.txt")["version"]
    assert target.name == f"geomigrate_qa-{version}.zip"


def test_zip_contains_the_bundled_templates_and_rules(repo, tmp_path):
    names = set(zipfile.ZipFile(build(repo, tmp_path)[0]).namelist())
    for folder in ("templates", "rules"):
        for path in (ROOT / "geomigrate_qa" / folder).glob("*.json"):
            assert f"geomigrate_qa/{folder}/{path.name}" in names


def test_zip_leaves_out_caches_and_junk(repo, tmp_path):
    (repo / "geomigrate_qa" / "__pycache__").mkdir()
    (repo / "geomigrate_qa" / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"x")
    (repo / "geomigrate_qa" / "core" / "stale.pyc").write_bytes(b"x")
    (repo / "geomigrate_qa" / ".gitignore").write_text("x")
    names = zipfile.ZipFile(build(repo, tmp_path)[0]).namelist()
    assert not [n for n in names if "__pycache__" in n or n.endswith(".pyc") or ".gitignore" in n]
    assert not [n for n in names if n.startswith("tests/") or "sample_data" in n]


def test_license_with_another_extension_is_saved_as_plain_license(repo, tmp_path):
    (repo / "LICENSE").rename(repo / "LICENSE.txt")
    names = zipfile.ZipFile(build(repo, tmp_path)[0]).namelist()
    assert "geomigrate_qa/LICENSE" in names and "geomigrate_qa/LICENSE.txt" not in names


def test_missing_license_is_a_clear_error(repo, tmp_path):
    (repo / "LICENSE").unlink()
    with pytest.raises(packager.PackagingError, match="LICENSE"):
        build(repo, tmp_path)


def test_real_metadata_passes_the_repository_checks():
    plugin = ROOT / "geomigrate_qa"
    meta = packager.read_metadata(plugin / "metadata.txt")
    errors, warnings = packager.check_metadata(meta, plugin)
    assert errors == [] and warnings == []
    assert meta["qgisMaximumVersion"] == "3.99"  # QGIS 4 is not claimed until it is tested
    assert "supportsQt6" not in meta


def test_metadata_problems_are_reported(tmp_path):
    folder = tmp_path / "1bad"
    folder.mkdir()
    errors, _ = packager.check_metadata(
        {"name": "X plugin", "version": "one", "icon": "nope.png", "experimental": "maybe"}, folder)
    text = "\n".join(errors)
    for expected in ("'about'", "'email'", "version 'one'", "Folder name", "icon file",
                     "experimental"):
        assert expected in text


def test_incomplete_plugin_is_refused(repo, tmp_path):
    metadata = repo / "geomigrate_qa" / "metadata.txt"
    metadata.write_text(metadata.read_text().replace("email=", "mail="))
    with pytest.raises(packager.PackagingError, match="email"):
        build(repo, tmp_path)
