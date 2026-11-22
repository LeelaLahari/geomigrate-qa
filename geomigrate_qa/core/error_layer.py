"""Turn validation findings into a QGIS layer, and split layers into clean vs quarantined."""
from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer

from .transform import _MEMORY_GEOMETRY, _make_field

ERROR_FIELDS = (
    ("rule", "string"), ("severity", "string"), ("source_layer", "string"),
    ("feature_id", "string"), ("qgis_fid", "int"), ("field_name", "string"),
    ("message", "string"),
)


def build_error_layer(report, crs_authid: str, name="validation_errors") -> QgsVectorLayer:
    """One point per finding (null geometry when a finding has no location)."""
    layer = QgsVectorLayer(f"Point?crs={crs_authid}", name, "memory")
    layer.dataProvider().addAttributes([_make_field(n, k) for n, k in ERROR_FIELDS])
    layer.updateFields()
    features = []
    for finding in report.findings:
        feature = QgsFeature(layer.fields())
        if finding.location:
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*finding.location)))
        feature.setAttributes([
            finding.rule, finding.severity, finding.layer,
            None if finding.feature_id is None else str(finding.feature_id),
            finding.fid, finding.field, finding.message])
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    layer.updateExtents()
    return layer


def split_by_findings(layer: QgsVectorLayer, report, layer_name: str, severities=("error",)):
    """Return (clean layer, set of quarantined feature ids).

    Every feature with a finding of the given severities is quarantined, including all copies
    of a duplicate: we cannot know which copy is the right one, so a person decides.
    """
    bad = {f.fid for f in report.findings if f.layer == layer_name and f.severity in severities}
    clean = QgsVectorLayer(
        f"{_MEMORY_GEOMETRY[layer.geometryType().name]}?crs={layer.crs().authid()}",
        layer_name, "memory")
    clean.dataProvider().addAttributes(list(layer.fields()))
    clean.updateFields()
    kept = []
    for source in layer.getFeatures():
        if source.id() in bad:
            continue
        feature = QgsFeature(clean.fields())
        feature.setGeometry(source.geometry())
        feature.setAttributes(source.attributes())
        kept.append(feature)
    clean.dataProvider().addFeatures(kept)
    clean.updateExtents()
    return clean, bad
