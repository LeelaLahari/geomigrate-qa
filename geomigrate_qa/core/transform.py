"""Apply a mapping template to a QGIS layer: rename/clean/cast fields, reproject, repair.

Policy: transform is faithful. It never drops a feature silently and never invents data.
Features are rejected only when they cannot be placed (no geometry, reprojection failure,
wrong geometry type); every rejection and every changed value is reported as an Issue.
Judging data quality (duplicates, domains, zero-length lines) is left to the rule engine.
"""
import math
from dataclasses import dataclass, field

from qgis.core import (
    NULL,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsFeature,
    QgsField,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QMetaType, QVariant

from .importer import open_dataset
from .mapping import MappingError, convert_value, load_template

WARNING = "warning"
REJECTED = "rejected"

_MEMORY_GEOMETRY = {"Point": "Point", "Line": "LineString", "Polygon": "Polygon"}


def _make_field(name, kind):
    """Build a QgsField without deprecation warnings on new QGIS, and still work on 3.34."""
    meta = getattr(QMetaType, "Type", QMetaType)
    try:  # QGIS 3.38+ and QGIS 4
        return QgsField(name, {"string": meta.QString, "int": meta.Int,
                               "double": meta.Double}[kind])
    except TypeError:  # QGIS 3.34 LTR only accepts QVariant types
        return QgsField(name, {"string": QVariant.String, "int": QVariant.Int,
                               "double": QVariant.Double}[kind])


@dataclass
class Issue:
    severity: str
    source_fid: int
    code: str
    message: str
    field: str = None


@dataclass
class TransformResult:
    layer: QgsVectorLayer
    issues: list = field(default_factory=list)
    read: int = 0
    written: int = 0
    repaired: int = 0

    @property
    def rejected(self):
        return [i for i in self.issues if i.severity == REJECTED]

    @property
    def warnings(self):
        return [i for i in self.issues if i.severity == WARNING]


def check_template(source_layer: QgsVectorLayer, template):
    """Return a list of problems that stop this template from fitting the layer."""
    problems = []
    names = {f.name() for f in source_layer.fields()}
    for fm in template.fields:
        if fm.source and fm.source not in names:
            problems.append(f"source field '{fm.source}' (for '{fm.target}') not found; "
                            f"available: {sorted(names)}")
    if not source_layer.crs().isValid():
        problems.append("source layer has no CRS; assign one before transforming")
    if source_layer.geometryType().name != template.geometry_type:
        problems.append(f"template expects {template.geometry_type} geometry but the layer "
                        f"is {source_layer.geometryType().name}")
    return problems


def _is_null(value):
    return value is None or value == NULL


def _finite(geometry):
    box = geometry.boundingBox()
    return all(math.isfinite(v) for v in (
        box.xMinimum(), box.xMaximum(), box.yMinimum(), box.yMaximum()))


def transform_layer(source_layer: QgsVectorLayer, template) -> TransformResult:
    template = load_template(template) if not hasattr(template, "fields") else template
    problems = check_template(source_layer, template)
    if problems:
        raise MappingError("; ".join(problems))

    target_crs = QgsCoordinateReferenceSystem(template.target_crs)
    if not target_crs.isValid():
        raise MappingError(f"Unknown target CRS {template.target_crs}.")

    out = QgsVectorLayer(
        f"{_MEMORY_GEOMETRY[template.geometry_type]}?crs={template.target_crs}",
        template.target_layer, "memory")
    provider = out.dataProvider()
    provider.addAttributes([_make_field(fm.target, fm.type) for fm in template.fields])
    out.updateFields()

    transform = QgsCoordinateTransform(
        source_layer.crs(), target_crs, QgsProject.instance().transformContext())
    result = TransformResult(layer=out)
    new_features = []

    for src in source_layer.getFeatures():
        result.read += 1
        fid = src.id()
        geometry = src.geometry()

        if geometry.isNull() or geometry.isEmpty():
            result.issues.append(Issue(REJECTED, fid, "no_geometry", "Feature has no geometry."))
            continue
        if geometry.type().name != template.geometry_type:
            result.issues.append(Issue(REJECTED, fid, "geometry_type_mismatch",
                                       f"Expected {template.geometry_type}, got "
                                       f"{geometry.type().name}."))
            continue

        try:
            geometry.transform(transform)
        except QgsCsException:
            result.issues.append(Issue(REJECTED, fid, "reprojection_failed",
                                       "Coordinates could not be reprojected."))
            continue
        if not _finite(geometry):
            result.issues.append(Issue(REJECTED, fid, "reprojection_failed",
                                       "Reprojection produced invalid coordinates."))
            continue

        raw_geometry = geometry.get()
        if raw_geometry.is3D():
            raw_geometry.dropZValue()
        if raw_geometry.isMeasure():
            raw_geometry.dropMValue()

        if not geometry.isGeosValid():
            fixed = geometry.makeValid()
            if (fixed and not fixed.isEmpty() and fixed.type() == geometry.type()
                    and fixed.isGeosValid()):
                geometry = fixed
                result.repaired += 1
                result.issues.append(Issue(WARNING, fid, "geometry_repaired",
                                           "Invalid geometry was repaired."))
            else:
                result.issues.append(Issue(WARNING, fid, "repair_failed",
                                           "Invalid geometry could not be repaired; kept as is."))

        values = []
        for fm in template.fields:
            if fm.compute == "length":
                raw = round(geometry.length(), 2)
            elif fm.compute == "area":
                raw = round(geometry.area(), 2)
            elif fm.source:
                raw = src[fm.source]
                raw = None if _is_null(raw) else raw
            else:
                raw = None
            value, problem = convert_value(raw, fm)
            if problem:
                result.issues.append(Issue(WARNING, fid, problem,
                                           f"Value {raw!r} could not be used for '{fm.target}'.",
                                           fm.target))
            values.append(value)

        feature = QgsFeature(out.fields())
        feature.setGeometry(geometry)
        feature.setAttributes(values)
        new_features.append(feature)

    provider.addFeatures(new_features)
    out.updateExtents()
    result.written = len(new_features)
    return result


def import_and_transform(path, template) -> TransformResult:
    """Open a file, assume the template's source CRS if the file has none, transform layer 1."""
    template = load_template(template) if not hasattr(template, "fields") else template
    opened = open_dataset(path, assume_crs=template.assume_source_crs)
    if not opened.ok:
        raise MappingError("; ".join(opened.warnings) or f"Could not read {path}.")
    return transform_layer(opened.layers[0].layer, template)