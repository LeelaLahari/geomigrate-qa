import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("geopandas")
pytest.importorskip("ezdxf")

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from generate_sample_data import build


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    out = tmp_path_factory.mktemp("sample_data")
    return out, build(out)


def test_manifest_written(data):
    out, manifest = data
    assert json.loads((out / "expected_errors.json").read_text())["seed"] == manifest["seed"]


def test_clean_gpkg_counts(data):
    out, _ = data
    for layer, n in (("poles", 48), ("towers", 6), ("cables", 42)):
        gdf = gpd.read_file(out / "clean" / "network.gpkg", layer=layer)
        assert len(gdf) == n
        assert gdf.crs.to_epsg() == 32643


def test_shapefile_defects_match_manifest(data):
    out, manifest = data
    poles = gpd.read_file(out / "defective" / "poles.shp")
    info = manifest["poles_shp"]
    assert poles.crs is None  # .prj removed on purpose
    assert poles.pole_id.isna().sum() == len(info["null_id_rows"])
    assert set(poles.material) - {"RCC", "STEEL", "WOOD"} == {"CONCRETE", "METAL", "Rcc"}
    assert (poles.height_m < 0).sum() == len(info["negative_height_rows"])


def test_kml_defects_match_manifest(data):
    out, manifest = data
    towers = gpd.read_file(out / "defective" / "towers.kml")
    assert len(towers) == manifest["towers_kml"]["total_rows"]
    assert towers.Name.isna().sum() == 1
    assert (towers.geometry.y > 60).sum() == 1  # the swapped lat/lon tower


def test_dxf_entity_count(data):
    out, manifest = data
    cables = gpd.read_file(out / "defective" / "cables.dxf")
    assert len(cables) == manifest["cables_dxf"]["total_entities"]
    assert (cables.Layer == "0").sum() == 2
