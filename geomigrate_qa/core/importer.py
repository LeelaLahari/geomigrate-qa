"""Open supported GIS files through QGIS and report layers, CRS status and warnings.

Uses only qgis.core (no GUI), so it runs headless in tests. Formats are read by QGIS's
own OGR provider; KMZ is unzipped first because not every GDAL build reads it directly.
"""
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsProviderRegistry,
    QgsProviderSublayerDetails,
    QgsVectorLayer,
)

from . import is_supported

CRS_FILE = "file"          # CRS was stored in the source file
CRS_ASSIGNED = "assigned"  # source had no CRS; the caller supplied one
CRS_MISSING = "missing"    # source had no CRS and none was supplied


@dataclass
class ImportedLayer:
    name: str
    layer: QgsVectorLayer
    crs_status: str
    feature_count: int
    geometry_type: str

    @property
    def authid(self) -> str:
        crs = self.layer.crs()
        return crs.authid() if crs.isValid() else ""


@dataclass
class ImportResult:
    source: Path
    layers: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    _tmp: object = None  # keeps an unzipped KMZ alive as long as the result is

    @property
    def ok(self) -> bool:
        return bool(self.layers)

    @property
    def needs_crs(self) -> bool:
        return any(item.crs_status == CRS_MISSING for item in self.layers)


def _extract_kmz(path: Path, result: ImportResult):
    tmp = tempfile.TemporaryDirectory(prefix="geomigrate_kmz_")
    result._tmp = tmp
    try:
        with zipfile.ZipFile(path) as archive:
            kml_names = [n for n in archive.namelist() if n.lower().endswith(".kml")]
            if not kml_names:
                result.warnings.append(f"{path.name}: no .kml file inside the KMZ archive.")
                return None
            archive.extract(kml_names[0], tmp.name)
            return Path(tmp.name) / kml_names[0]
    except zipfile.BadZipFile:
        result.warnings.append(f"{path.name}: not a valid KMZ (zip) file.")
        return None


def open_dataset(path, assume_crs=None) -> ImportResult:
    """Open a file and return its non-empty vector layers.

    assume_crs: authid such as "EPSG:32643", applied only to layers that have no CRS.
    """
    path = Path(path)
    result = ImportResult(source=path)

    if not path.exists():
        result.warnings.append(f"{path.name}: file not found.")
        return result
    if not is_supported(path.name):
        result.warnings.append(f"{path.name}: unsupported file type.")
        return result

    assumed = None
    if assume_crs:
        assumed = QgsCoordinateReferenceSystem(assume_crs)
        if not assumed.isValid():
            raise ValueError(f"Invalid CRS: {assume_crs}")

    read_path = path
    if path.suffix.lower() == ".kmz":
        read_path = _extract_kmz(path, result)
        if read_path is None:
            return result

    details = QgsProviderRegistry.instance().querySublayers(str(read_path))
    if not details:
        result.warnings.append(f"{path.name}: QGIS could not read this file.")
        return result

    options = QgsProviderSublayerDetails.LayerOptions(QgsCoordinateTransformContext())
    for detail in details:
        layer = detail.toLayer(options)
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            continue
        count = layer.featureCount()
        if count == 0:
            continue  # e.g. empty point/polygon sublayers of a line-only DXF

        if layer.crs().isValid():
            status = CRS_FILE
        elif assumed is not None:
            layer.setCrs(assumed)
            status = CRS_ASSIGNED
        else:
            status = CRS_MISSING
            result.warnings.append(f"{path.name} / {detail.name()}: no CRS stored in the file.")

        name = detail.name() if detail.name() == path.stem else f"{path.stem} / {detail.name()}"
        result.layers.append(ImportedLayer(
            name=name, layer=layer, crs_status=status, feature_count=count,
            geometry_type=layer.geometryType().name))

    if not result.layers:
        result.warnings.append(f"{path.name}: no non-empty vector layers found.")
    return result
