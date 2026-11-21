import json

import pytest

from geomigrate_qa.core.mapping import (
    CAST_FAILED,
    UNMAPPED,
    FieldMap,
    MappingError,
    cast_value,
    convert_value,
    load_template,
    parse_template,
)

TEMPLATES = __import__("pathlib").Path(__file__).resolve().parents[1] / "geomigrate_qa" / "templates"


def minimal(**changes):
    data = {
        "name": "t", "target_layer": "poles", "target_crs": "EPSG:32643",
        "geometry_type": "Point",
        "fields": [{"target": "pole_id", "source": "id", "type": "string"}],
    }
    data.update(changes)
    return data


def test_shipped_templates_load():
    for path in TEMPLATES.glob("*.json"):
        template = load_template(path)
        assert template.target_crs == "EPSG:32643"
        assert template.fields


def test_missing_key_is_reported():
    data = minimal()
    del data["target_crs"]
    with pytest.raises(MappingError, match="target_crs"):
        parse_template(data)


@pytest.mark.parametrize("change, message", [
    ({"geometry_type": "Blob"}, "geometry_type"),
    ({"target_crs": "32643"}, "target_crs"),
    ({"fields": []}, "at least one field"),
    ({"fields": [{"target": "a", "type": "string"}, {"target": "a", "type": "string"}]},
     "Duplicate"),
    ({"fields": [{"target": "a", "type": "text"}]}, "type must be"),
    ({"fields": [{"target": "a", "type": "string", "transforms": ["shout"]}]}, "unknown transform"),
    ({"fields": [{"target": "a", "type": "double", "source": "x", "compute": "length"}]},
     "either"),
])
def test_invalid_templates_rejected(change, message):
    with pytest.raises(MappingError, match=message):
        parse_template(minimal(**change))


def test_bad_json_and_missing_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(MappingError, match="not valid JSON"):
        load_template(bad)
    with pytest.raises(MappingError, match="not found"):
        load_template(tmp_path / "nope.json")


def test_cast_value():
    assert cast_value("12", "int") == (12, True)
    assert cast_value("12.0", "int") == (12, True)
    assert cast_value("12.5", "int") == (None, False)
    assert cast_value("9.5", "double") == (9.5, True)
    assert cast_value("abc", "double") == (None, False)
    assert cast_value(None, "double") == (None, True)
    assert cast_value(5, "string") == ("5", True)


def test_convert_cleans_text():
    fm = FieldMap(target="m", type="string", transforms=("strip", "upper"))
    assert convert_value("  rcc ", fm) == ("RCC", None)
    assert convert_value("   ", fm) == (None, None)


def test_convert_value_map_and_unmapped():
    fm = FieldMap(target="t", type="string", value_map={"A": "AERIAL"})
    assert convert_value("A", fm) == ("AERIAL", None)
    assert convert_value("0", fm) == (None, UNMAPPED)


def test_convert_cast_failure_and_default():
    fm = FieldMap(target="h", type="double", default=10)
    assert convert_value("tall", fm) == (10.0, CAST_FAILED)
    assert convert_value(None, fm) == (10.0, None)


def test_template_is_plain_json():
    path = next(TEMPLATES.glob("*.json"))
    assert isinstance(json.loads(path.read_text()), dict)
