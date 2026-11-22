import json

import pytest

from geomigrate_qa.core.runconfig import (
    DEFAULT_RULES,
    PACKAGE_DIR,
    RunConfig,
    RunConfigError,
    SourceEntry,
    bundled_names,
    check_config,
    load_run_config,
    parse_run_config,
    save_run_config,
)


def write(tmp_path, data, name="run.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


@pytest.fixture
def files(tmp_path):
    (tmp_path / "poles.shp").write_text("x")
    (tmp_path / "ref.gpkg").write_text("x")
    return tmp_path


def config_data(**changes):
    data = {
        "label": "t",
        "sources": {"poles": {"file": "poles.shp", "template": "bundled:poles_shp.json"}},
        "rules": "bundled:telecom_default.json",
    }
    data.update(changes)
    return data


def test_bundled_names_exist():
    assert "bundled:poles_shp.json" in bundled_names("template")
    assert DEFAULT_RULES in bundled_names("rules")


def test_relative_and_bundled_paths_resolve(files):
    cfg = load_run_config(write(files, config_data(reference_gpkg="ref.gpkg", schema="demo")))
    source = cfg.sources[0]
    assert source.file == str(files / "poles.shp")
    assert source.template == str(PACKAGE_DIR / "templates" / "poles_shp.json")
    assert cfg.rules == str(PACKAGE_DIR / "rules" / "telecom_default.json")
    assert cfg.reference_gpkg == str(files / "ref.gpkg") and cfg.schema == "demo"


def test_save_then_load_round_trips(files):
    original = load_run_config(write(files, config_data(schema="demo")))
    out = files / "saved" / "again.json"
    out.parent.mkdir()
    (files / "saved" / "poles.shp").write_text("x")
    save_run_config(original, out)
    saved = json.loads(out.read_text())
    assert saved["sources"]["poles"]["template"] == "bundled:poles_shp.json"
    assert saved["rules"] == "bundled:telecom_default.json"
    assert "password" not in out.read_text().lower()


def test_problems_are_listed_together(tmp_path):
    cfg = RunConfig(
        sources=(SourceEntry("po les", "missing.shp", "missing.json"),
                 SourceEntry("po les", "missing2.shp", "missing2.json")),
        rules="nope.json", reference_gpkg="nope.gpkg", schema='bad"schema')
    problems = "\n".join(check_config(cfg))
    for expected in ("letters, digits", "used twice", "data file not found",
                     "template not found", "Rule set not found", "Reference GeoPackage",
                     "Schema name"):
        assert expected in problems


def test_empty_sources_and_malformed_files(tmp_path):
    assert check_config(RunConfig(sources=())) != []
    with pytest.raises(RunConfigError, match="'sources'"):
        parse_run_config({"rules": "x"}, tmp_path)
    with pytest.raises(RunConfigError, match="'file' and 'template'"):
        parse_run_config({"sources": {"a": {"file": "x"}}}, tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    with pytest.raises(RunConfigError, match="not valid JSON"):
        load_run_config(bad)
    with pytest.raises(RunConfigError, match="not found"):
        load_run_config(tmp_path / "missing.json")


def test_check_can_be_skipped_for_loading_into_a_dialog(tmp_path):
    path = write(tmp_path, config_data())
    cfg = load_run_config(path, check=False)  # poles.shp does not exist here
    assert cfg.sources[0].name == "poles"
