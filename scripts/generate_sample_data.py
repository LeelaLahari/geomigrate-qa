"""Generate synthetic telecom GIS sample data with deliberate, recorded defects.

Output (in sample_data/):
  clean/network.gpkg        poles, towers, cables (EPSG:32643), the "correct" data
  defective/poles.shp       EPSG:4326, .prj removed, attribute + geometry defects
  defective/towers.kml/.kmz EPSG:4326, swapped coordinates, duplicate, missing name
  defective/cables.dxf      local metres (no CRS), dangling/zero-length/duplicate/layer defects
  expected_errors.json      ground truth used by tests to check the rule engine

Run from the repo root:  python scripts/generate_sample_data.py
"""
import json
import random
import zipfile
from pathlib import Path

import ezdxf
import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, Point

SEED = 42
CRS_PROJECTED = "EPSG:32643"  # UTM zone 43N
CENTRE_LON, CENTRE_LAT = 73.86, 18.52
ROWS, COLS, SPACING = 6, 8, 60.0
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "sample_data"


def _origin():
    t = Transformer.from_crs("EPSG:4326", CRS_PROJECTED, always_xy=True)
    x, y = t.transform(CENTRE_LON, CENTRE_LAT)
    return round(x, 3), round(y, 3)


def make_clean(rng):
    ox, oy = _origin()
    materials = ["RCC", "STEEL", "WOOD"]
    poles = []
    for r in range(ROWS):
        for c in range(COLS):
            poles.append({
                "pole_id": f"P{r * COLS + c + 1:03d}",
                "material": rng.choice(materials),
                "height_m": rng.choice([9.0, 11.0, 12.0]),
                "status": "ACTIVE",
                "geometry": Point(round(ox + c * SPACING + rng.uniform(-3, 3), 3),
                                  round(oy + r * SPACING + rng.uniform(-3, 3), 3)),
            })
    poles = gpd.GeoDataFrame(poles, crs=CRS_PROJECTED)

    towers = []
    for i in range(6):
        towers.append({
            "tower_id": f"T{i + 1:02d}",
            "site_name": f"Site-{i + 1:02d}",
            "height_m": round(rng.uniform(30, 45), 1),
            "owner": rng.choice(["OperatorA", "OperatorB"]),
            "geometry": Point(round(ox + rng.uniform(0, (COLS - 1) * SPACING), 3),
                              round(oy + rng.uniform(0, (ROWS - 1) * SPACING), 3)),
        })
    towers = gpd.GeoDataFrame(towers, crs=CRS_PROJECTED)

    cables = []
    n = 0
    for r in range(ROWS):
        for c in range(COLS - 1):
            i = r * COLS + c
            line = LineString([poles.geometry[i], poles.geometry[i + 1]])
            n += 1
            cables.append({
                "cable_id": f"C{n:03d}",
                "cable_type": "AERIAL" if r % 2 == 0 else "UG",
                "fiber_count": rng.choice([12, 24, 48]),
                "length_m": round(line.length, 2),
                "status": "ACTIVE",
                "geometry": line,
            })
    cables = gpd.GeoDataFrame(cables, crs=CRS_PROJECTED)
    return poles, towers, cables


def make_defective_poles(poles, rng, path):
    dp = poles.to_crs("EPSG:4326").copy()
    n = len(dp)
    injected = rng.sample(range(n), 10)
    donors = [i for i in range(n) if i not in injected][:4]
    dup_id_rows, null_rows, bad_mat_rows = injected[0:2], injected[2:4], injected[4:7]
    neg_rows, dup_geom_rows = injected[7:8], injected[8:10]

    for row, donor in zip(dup_id_rows, donors[0:2]):
        dp.loc[row, "pole_id"] = dp.loc[donor, "pole_id"]
    dp.loc[null_rows, "pole_id"] = None
    for row, bad in zip(bad_mat_rows, ["CONCRETE", "METAL", "Rcc"]):
        dp.loc[row, "material"] = bad
    dp.loc[neg_rows, "height_m"] = -5.0
    for row, donor in zip(dup_geom_rows, donors[2:4]):
        dp.loc[row, "geometry"] = dp.loc[donor, "geometry"]

    dp.to_file(path, driver="ESRI Shapefile")
    path.with_suffix(".prj").unlink()
    return {
        "file": "defective/poles.shp",
        "true_crs": "EPSG:4326",
        "missing_prj": True,
        "duplicate_id_rows": [{"row": r, "same_id_as_row": d}
                              for r, d in zip(dup_id_rows, donors[0:2])],
        "null_id_rows": null_rows,
        "invalid_material_rows": bad_mat_rows,
        "negative_height_rows": neg_rows,
        "duplicate_geometry_rows": [{"row": r, "same_location_as_row": d}
                                    for r, d in zip(dup_geom_rows, donors[2:4])],
        "total_rows": n,
    }


def make_defective_towers(towers, out_dir):
    dt = towers.to_crs("EPSG:4326").copy()
    dt = dt.rename(columns={"site_name": "Name"})
    swap = dt.geometry[2]
    dt.loc[2, "geometry"] = Point(swap.y, swap.x)  # lat/lon swapped
    dt.loc[4, "Name"] = None                        # missing name
    dup = dt.iloc[[0]].copy()                       # exact duplicate of row 0
    dt = pd.concat([dt, dup], ignore_index=True)

    kml = out_dir / "defective" / "towers.kml"
    dt.to_file(kml, driver="KML")
    with zipfile.ZipFile(out_dir / "defective" / "towers.kmz", "w", zipfile.ZIP_DEFLATED) as z:
        z.write(kml, "doc.kml")
    return {
        "file": "defective/towers.kml (and towers.kmz)",
        "true_crs": "EPSG:4326",
        "swapped_lat_lon_rows": [2],
        "missing_name_rows": [4],
        "duplicate_rows": [{"row": len(dt) - 1, "same_as_row": 0}],
        "total_rows": len(dt),
    }


def make_defective_dxf(poles, cables, rng, path):
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6  # metres
    for name in ("CABLE_AERIAL", "CABLE_UG"):
        doc.layers.add(name)
    msp = doc.modelspace()

    def add(coords, layer):
        e = msp.add_lwpolyline([(x, y) for x, y in coords], dxfattribs={"layer": layer})
        return e.dxf.handle

    layer_of = {"AERIAL": "CABLE_AERIAL", "UG": "CABLE_UG"}
    wrong_layer_idx = rng.sample(range(len(cables)), 2)
    dup_idx = rng.sample([i for i in range(len(cables)) if i not in wrong_layer_idx], 2)

    wrong_layer, duplicates = [], []
    for i, row in cables.iterrows():
        layer = "0" if i in wrong_layer_idx else layer_of[row.cable_type]
        h = add(row.geometry.coords, layer)
        if i in wrong_layer_idx:
            wrong_layer.append({"handle": h, "cable_id": row.cable_id, "layer": "0"})
        if i in dup_idx:
            h2 = add(row.geometry.coords, layer)
            duplicates.append({"handle": h2, "duplicate_of": h, "cable_id": row.cable_id})

    zero_len = []
    for i in (5, 20):
        p = poles.geometry[i]
        zero_len.append({"handle": add([(p.x, p.y), (p.x, p.y)], "CABLE_AERIAL")})

    dangling = []
    for i in (0, 16, 40):  # stubs from a pole to an empty spot, 25 m outside the grid
        p = poles.geometry[i]
        end = (round(p.x - 25, 3), round(p.y - 25, 3))
        dangling.append({"handle": add([(p.x, p.y), end], "CABLE_AERIAL"),
                         "starts_at_pole_row": i, "dangling_end": list(end)})

    doc.saveas(path)
    return {
        "file": "defective/cables.dxf",
        "true_crs": CRS_PROJECTED + " (not stored in the DXF; units = metres)",
        "wrong_layer": wrong_layer,
        "duplicate_entities": duplicates,
        "zero_length": zero_len,
        "dangling_end_stubs": dangling,
        "total_entities": len(cables) + len(duplicates) + len(zero_len) + len(dangling),
    }


def build(out_dir=DEFAULT_OUT, seed=SEED):
    out_dir = Path(out_dir)
    (out_dir / "clean").mkdir(parents=True, exist_ok=True)
    (out_dir / "defective").mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    poles, towers, cables = make_clean(rng)
    gpkg = out_dir / "clean" / "network.gpkg"
    gpkg.unlink(missing_ok=True)
    for name, gdf in (("poles", poles), ("towers", towers), ("cables", cables)):
        gdf.to_file(gpkg, layer=name, driver="GPKG")

    manifest = {
        "seed": seed,
        "clean_gpkg": {"file": "clean/network.gpkg", "crs": CRS_PROJECTED,
                       "poles": len(poles), "towers": len(towers), "cables": len(cables)},
        "poles_shp": make_defective_poles(poles, rng, out_dir / "defective" / "poles.shp"),
        "towers_kml": make_defective_towers(towers, out_dir),
        "cables_dxf": make_defective_dxf(poles, cables, rng, out_dir / "defective" / "cables.dxf"),
    }
    (out_dir / "expected_errors.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    m = build()
    print("Sample data written to", DEFAULT_OUT)
    print(json.dumps(m["clean_gpkg"], indent=2))
