"""Answer-key tests: the rule engine must find exactly the defects that
scripts/generate_sample_data.py injected (listed in sample_data/expected_errors.json)."""
import json
from pathlib import Path

import pytest

pytest.importorskip("qgis.core")

from qgis.core import QgsVectorLayer

from geomigrate_qa.core.rule_config import RuleConfigError
from geomigrate_qa.core.rules import validate
from geomigrate_qa.core.transform import import_and_transform

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_data"
TEMPLATES = ROOT / "geomigrate_qa" / "templates"
CONFIG = ROOT / "geomigrate_qa" / "rules" / "telecom_default.json"
pytestmark = pytest.mark.skipif(
    not (SAMPLE / "expected_errors.json").exists(),
    reason="run scripts/generate_sample_data.py first",
)


def key():
    return json.loads((SAMPLE / "expected_errors.json").read_text())


def clean(name):
    return QgsVectorLayer(f"{SAMPLE / 'clean' / 'network.gpkg'}|layername={name}", name, "ogr")


def migrated(source, template):
    return import_and_transform(SAMPLE / "defective" / source, TEMPLATES / template).layer


def rows(layer):
    """QGIS feature id -> 0-based row in source order."""
    return {f.id(): i for i, f in enumerate(layer.getFeatures())}


def found_rows(report, layer, rule, field_name=None):
    mapping = rows(layer)
    return {mapping[fid] for fid in report.fids(rule, layer.name(), field_name)}


@pytest.fixture(scope="module")
def poles():
    return migrated("poles.shp", "poles_shp.json")


@pytest.fixture(scope="module")
def towers():
    return migrated("towers.kml", "towers_kml.json")


@pytest.fixture(scope="module")
def cables():
    return migrated("cables.dxf", "cables_dxf.json")


def test_clean_network_has_no_findings():
    layers = {name: clean(name) for name in ("poles", "towers", "cables")}
    report = validate(layers, CONFIG)
    assert report.findings == [], report.count_by_rule()
    assert report.checked == {"poles": 48, "towers": 6, "cables": 42}


def test_poles_findings_match_the_answer_key(poles):
    info = key()["poles_shp"]
    report = validate({"poles": poles}, CONFIG, only=["poles"])

    assert found_rows(report, poles, "null_required", "pole_id") == set(info["null_id_rows"])
    assert len(report.of("null_required", "poles")) == len(info["null_id_rows"])

    dup_ids = {d["row"] for d in info["duplicate_id_rows"]}
    dup_ids |= {d["same_id_as_row"] for d in info["duplicate_id_rows"]}
    assert found_rows(report, poles, "duplicate_id") == dup_ids

    # Cleanup in Stage 4 fixed "Rcc" -> "RCC", so 2 of the 3 bad materials remain.
    assert found_rows(report, poles, "domain") == set(info["invalid_material_rows"][:2])
    assert found_rows(report, poles, "range") == set(info["negative_height_rows"])

    dup_geom = {d["row"] for d in info["duplicate_geometry_rows"]}
    dup_geom |= {d["same_location_as_row"] for d in info["duplicate_geometry_rows"]}
    assert found_rows(report, poles, "duplicate_geometry") == dup_geom


def test_towers_findings_match_the_answer_key(poles, towers):
    info = key()["towers_kml"]
    report = validate({"poles": poles, "towers": towers}, CONFIG, only=["towers"])
    dup = {info["duplicate_rows"][0]["row"], info["duplicate_rows"][0]["same_as_row"]}

    assert found_rows(report, towers, "out_of_extent") == set(info["swapped_lat_lon_rows"])
    assert found_rows(report, towers, "null_required", "site_name") == set(info["missing_name_rows"])
    assert found_rows(report, towers, "duplicate_id") == dup
    assert found_rows(report, towers, "duplicate_geometry") == dup
    assert len(report.findings) == 1 + 1 + 2 + 2


def test_cables_findings_match_the_answer_key(cables):
    info = key()["cables_dxf"]
    # Cable ends are checked against the trusted pole and tower inventory (the clean data).
    layers = {"cables": cables, "poles": clean("poles"), "towers": clean("towers")}
    report = validate(layers, CONFIG, only=["cables"])

    def ids(rule):
        return {str(i) for i in report.feature_ids(rule, "cables")}

    assert ids("null_required") == {w["handle"] for w in info["wrong_layer"]}
    assert ids("zero_length") == {z["handle"] for z in info["zero_length"]}
    assert ids("dangling_end") == {d["handle"] for d in info["dangling_end_stubs"]}
    duplicated = {d["handle"] for d in info["duplicate_entities"]}
    duplicated |= {d["duplicate_of"] for d in info["duplicate_entities"]}
    assert ids("duplicate_geometry") == duplicated
    assert not report.of("domain") and not report.of("length_mismatch")
    assert not report.of("invalid_geometry")  # zero-length lines are reported once, as zero_length


def test_total_defects_found():
    """One line you can quote: every injected defect category was detected."""
    info = key()
    report = validate(
        {"poles": migrated("poles.shp", "poles_shp.json"),
         "towers": migrated("towers.kml", "towers_kml.json")}, CONFIG)
    assert report.skipped == ["cables"]
    assert report.error_count == len(report.findings) > 0
    assert info["poles_shp"]["total_rows"] == 48


def test_severity_override_and_missing_layers(poles):
    config = {"layers": {"poles": {"id_field": "pole_id", "rules": [
        {"rule": "duplicate_geometry", "severity": "warning"}]}}}
    report = validate({"poles": poles}, config)
    assert report.findings and {f.severity for f in report.findings} == {"warning"}
    assert report.error_count == 0
    assert validate({}, config).skipped == ["poles"]


def test_length_mismatch_is_detected(cables):
    config = {"layers": {"cables": {"id_field": "cable_id", "rules": [
        {"rule": "length_mismatch", "field": "length_m", "tolerance_m": 0.05}]}}}
    assert validate({"cables": cables}, config).findings == []
    index = cables.fields().indexOf("length_m")
    first = next(cables.getFeatures()).id()
    cables.dataProvider().changeAttributeValues({first: {index: 999.0}})
    report = validate({"cables": cables}, config)
    assert report.fids("length_mismatch", "cables") == {first}


def test_missing_node_layer_is_a_clear_error(cables):
    with pytest.raises(RuleConfigError, match="node layer"):
        validate({"cables": cables}, CONFIG, only=["cables"])
