import json
from pathlib import Path

import pytest

pytest.importorskip("qgis.core")

from qgis.core import NULL, QgsVectorLayer

from geomigrate_qa.core.importer import open_dataset
from geomigrate_qa.core.mapping import MappingError, load_template
from geomigrate_qa.core.transform import check_template, import_and_transform, transform_layer

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_data"
TEMPLATES = ROOT / "geomigrate_qa" / "templates"
pytestmark = pytest.mark.skipif(
    not (SAMPLE / "expected_errors.json").exists(),
    reason="run scripts/generate_sample_data.py first",
)


def manifest():
    return json.loads((SAMPLE / "expected_errors.json").read_text())


def clean(layer_name):
    return QgsVectorLayer(f"{SAMPLE / 'clean' / 'network.gpkg'}|layername={layer_name}", "c", "ogr")


def codes(result):
    return sorted(i.code for i in result.issues)


def test_poles_reprojected_and_cleaned():
    result = import_and_transform(SAMPLE / "defective" / "poles.shp", TEMPLATES / "poles_shp.json")
    assert result.read == result.written == 48
    assert result.layer.crs().authid() == "EPSG:32643"
    assert [f.name() for f in result.layer.fields()] == [
        "pole_id", "material", "height_m", "status"]
    materials = {f["material"] for f in result.layer.getFeatures()}
    assert materials == {"RCC", "STEEL", "WOOD", "CONCRETE", "METAL"}  # "Rcc" was cleaned


def test_poles_land_where_the_clean_poles_are():
    info = manifest()["poles_shp"]
    moved = {item["row"] for item in info["duplicate_geometry_rows"]}
    result = import_and_transform(SAMPLE / "defective" / "poles.shp", TEMPLATES / "poles_shp.json")
    got = [f.geometry().asPoint() for f in result.layer.getFeatures()]
    want = [f.geometry().asPoint() for f in clean("poles").getFeatures()]
    for row, (a, b) in enumerate(zip(got, want, strict=True)):
        if row not in moved:
            assert a.distance(b) < 0.01, f"row {row} is {a.distance(b):.3f} m off"


def test_towers_renamed_and_flattened_to_2d():
    result = import_and_transform(SAMPLE / "defective" / "towers.kml", TEMPLATES / "towers_kml.json")
    assert result.written == 7
    assert "site_name" in [f.name() for f in result.layer.fields()]
    assert not any(f.geometry().constGet().is3D() for f in result.layer.getFeatures())
    names = [f["site_name"] for f in result.layer.getFeatures()]
    assert names[4] == NULL  # the tower with a missing name stays empty, nothing is invented


def test_swapped_tower_is_not_hidden_by_the_transform():
    result = import_and_transform(SAMPLE / "defective" / "towers.kml", TEMPLATES / "towers_kml.json")
    good = [f.geometry().asPoint() for i, f in enumerate(result.layer.getFeatures()) if i != 2]
    bad = list(result.layer.getFeatures())[2].geometry().asPoint()
    assert min(bad.distance(p) for p in good) > 100_000  # far outside the area: Stage 5 flags it


def test_cables_value_map_length_and_issues():
    result = import_and_transform(SAMPLE / "defective" / "cables.dxf", TEMPLATES / "cables_dxf.json")
    assert result.written == 49
    types = [f["cable_type"] for f in result.layer.getFeatures()]
    assert {t for t in types if t != NULL} == {"AERIAL", "UG"}
    assert types.count(NULL) == 2  # the two cables drawn on DXF layer "0"
    assert codes(result) == ["repair_failed"] * 2 + ["unmapped_value"] * 2  # zero-length, layer "0"
    lengths = [f["length_m"] for f in result.layer.getFeatures()]
    assert min(lengths) == 0.0 and max(lengths) < 100


def test_wrong_template_fails_with_a_clear_message():
    opened = open_dataset(SAMPLE / "defective" / "poles.shp", assume_crs="EPSG:4326")
    template = load_template(TEMPLATES / "cables_dxf.json")  # Line template on a Point layer
    problems = check_template(opened.layers[0].layer, template)
    assert any("EntityHandle" in p for p in problems)
    assert any("geometry" in p for p in problems)
    with pytest.raises(MappingError):
        transform_layer(opened.layers[0].layer, template)


def test_layer_without_crs_is_refused():
    opened = open_dataset(SAMPLE / "defective" / "poles.shp")  # no assumed CRS
    template = load_template(TEMPLATES / "poles_shp.json")
    with pytest.raises(MappingError, match="no CRS"):
        transform_layer(opened.layers[0].layer, template)
