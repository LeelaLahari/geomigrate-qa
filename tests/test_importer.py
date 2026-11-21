from pathlib import Path

import pytest

pytest.importorskip("qgis.core")

from geomigrate_qa.core.importer import (
    CRS_ASSIGNED,
    CRS_FILE,
    CRS_MISSING,
    open_dataset,
)

SAMPLE = Path(__file__).resolve().parents[1] / "sample_data"
pytestmark = pytest.mark.skipif(
    not (SAMPLE / "expected_errors.json").exists(),
    reason="run scripts/generate_sample_data.py first",
)


def test_gpkg_returns_three_layers_with_crs():
    result = open_dataset(SAMPLE / "clean" / "network.gpkg")
    counts = {item.name.split(" / ")[-1]: item.feature_count for item in result.layers}
    assert counts == {"poles": 48, "towers": 6, "cables": 42}
    assert all(item.authid == "EPSG:32643" for item in result.layers)
    assert not result.needs_crs


def test_shapefile_without_prj_needs_crs():
    result = open_dataset(SAMPLE / "defective" / "poles.shp")
    assert result.ok and result.needs_crs
    assert result.layers[0].crs_status == CRS_MISSING
    assert any("no CRS" in w for w in result.warnings)


def test_shapefile_with_assumed_crs():
    result = open_dataset(SAMPLE / "defective" / "poles.shp", assume_crs="EPSG:4326")
    assert result.layers[0].crs_status == CRS_ASSIGNED
    assert result.layers[0].authid == "EPSG:4326"
    assert not result.needs_crs


def test_dxf_has_no_crs_until_assigned():
    result = open_dataset(SAMPLE / "defective" / "cables.dxf")
    assert result.needs_crs
    assert sum(item.feature_count for item in result.layers) == 49
    assigned = open_dataset(SAMPLE / "defective" / "cables.dxf", assume_crs="EPSG:32643")
    assert all(item.authid == "EPSG:32643" for item in assigned.layers)


def test_kml_and_kmz_give_the_same_towers():
    kml = open_dataset(SAMPLE / "defective" / "towers.kml")
    kmz = open_dataset(SAMPLE / "defective" / "towers.kmz")
    assert kml.layers[0].crs_status == CRS_FILE
    assert kml.layers[0].authid == "EPSG:4326"
    assert kmz.layers[0].feature_count == kml.layers[0].feature_count == 7


def test_bad_inputs_give_warnings_not_crashes(tmp_path):
    missing = open_dataset(tmp_path / "nope.shp")
    assert not missing.ok and "not found" in missing.warnings[0]
    txt = tmp_path / "notes.txt"
    txt.write_text("hello")
    assert "unsupported" in open_dataset(txt).warnings[0]
    with pytest.raises(ValueError):
        open_dataset(SAMPLE / "defective" / "poles.shp", assume_crs="EPSG:nonsense")
