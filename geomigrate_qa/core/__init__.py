SUPPORTED_EXTENSIONS = {".dxf", ".kml", ".kmz", ".shp", ".geojson", ".gpkg"}


def is_supported(path: str) -> bool:
    return "." in path and "." + path.rsplit(".", 1)[1].lower() in SUPPORTED_EXTENSIONS