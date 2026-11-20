from geomigrate_qa.core import is_supported


def test_supported_formats():
    for name in ["a.dxf", "b.KML", "c.kmz", "d.shp", "e.geojson", "f.gpkg"]:
        assert is_supported(name)


def test_unsupported_format():
    assert not is_supported("notes.txt")
    assert not is_supported("noextension")