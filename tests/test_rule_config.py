from pathlib import Path

import pytest

from geomigrate_qa.core.rule_config import RuleConfigError, load_rule_config, parse_rule_config

DEFAULT = Path(__file__).resolve().parents[1] / "geomigrate_qa" / "rules" / "telecom_default.json"


def config(rule):
    return {"layers": {"poles": {"rules": [rule]}}}


def test_default_config_loads():
    cfg = load_rule_config(DEFAULT)
    assert {layer.layer for layer in cfg.layers} == {"poles", "towers", "cables"}
    assert cfg.tolerance_m == 0.01
    assert all(spec.severity == "error" for layer in cfg.layers for spec in layer.rules)


def test_unknown_rule_is_an_error():
    with pytest.raises(RuleConfigError, match="unknown rule"):
        parse_rule_config(config({"rule": "domian", "field": "x", "allowed": []}))


def test_missing_and_unknown_parameters_are_errors():
    with pytest.raises(RuleConfigError, match="missing"):
        parse_rule_config(config({"rule": "domain", "field": "material"}))
    with pytest.raises(RuleConfigError, match="unknown parameter"):
        parse_rule_config(config({"rule": "null_required", "feilds": ["a"], "fields": ["a"]}))


def test_severity_override_and_validation():
    cfg = parse_rule_config(config({"rule": "zero_length", "severity": "warning"}))
    assert cfg.layers[0].rules[0].severity == "warning"
    with pytest.raises(RuleConfigError, match="severity"):
        parse_rule_config(config({"rule": "zero_length", "severity": "fatal"}))


def test_bad_tolerance_and_bad_files(tmp_path):
    with pytest.raises(RuleConfigError, match="tolerance_m"):
        parse_rule_config({"tolerance_m": 0, "layers": {}})
    with pytest.raises(RuleConfigError, match="layers"):
        parse_rule_config({"name": "x"})
    bad = tmp_path / "bad.json"
    bad.write_text("{oops")
    with pytest.raises(RuleConfigError, match="not valid JSON"):
        load_rule_config(bad)
    with pytest.raises(RuleConfigError, match="not found"):
        load_rule_config(tmp_path / "missing.json")
