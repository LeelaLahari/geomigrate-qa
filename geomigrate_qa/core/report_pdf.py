"""PDF report with a map of the findings, using only Qt (no extra Python packages)."""
from pathlib import Path

from qgis.core import (
    QgsLineSymbol,
    QgsMapRendererCustomPainterJob,
    QgsMapSettings,
    QgsMarkerSymbol,
    QgsRectangle,
    QgsSingleSymbolRenderer,
)
from qgis.PyQt.QtCore import QMarginsF, QSize, QUrl
from qgis.PyQt.QtGui import (
    QColor,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QTextDocument,
)

from .report import render_report_html, report_data_from_result, write_csv_reports

MAP_RESOURCE = "findings_map.png"


def _symbol(layer, kind):
    if layer.geometryType().name == "Line":
        return QgsLineSymbol.createSimple({"color": "#8a8a8a", "width": "0.4"})
    if kind == "error":
        return QgsMarkerSymbol.createSimple(
            {"color": "#d62728", "size": "3", "outline_color": "white"})
    return QgsMarkerSymbol.createSimple({"color": "#555555", "size": "1.6", "outline_style": "no"})


def render_map_image(result, size=None):
    """Return (QImage, number of findings outside the picture)."""
    size = size or QSize(900, 560)
    clean = [layer for layer in result.clean.values() if layer.featureCount() > 0]
    errors = result.error_layer
    extent = QgsRectangle()
    for layer in clean:
        extent.combineExtentWith(layer.extent())
    if extent.isNull():
        extent = errors.extent()
    # Include findings near the data (e.g. a dangling end just past the edge), but not far
    # outliers such as a swapped-coordinate point, which would shrink everything else to a dot.
    reach = extent.buffered(max(extent.width(), extent.height()))
    for feature in errors.getFeatures():
        if feature.hasGeometry() and reach.contains(feature.geometry().boundingBox()):
            extent.combineExtentWith(feature.geometry().boundingBox())
    extent.scale(1.1)

    layers = [errors, *[layer for layer in clean if layer.geometryType().name != "Line"],
              *[layer for layer in clean if layer.geometryType().name == "Line"]]
    saved = [(layer, layer.renderer().clone()) for layer in layers]
    try:
        for layer in layers:
            kind = "error" if layer is errors else "clean"
            layer.setRenderer(QgsSingleSymbolRenderer(_symbol(layer, kind)))
        settings = QgsMapSettings()
        settings.setLayers(layers)
        settings.setDestinationCrs(errors.crs())
        settings.setExtent(extent)
        settings.setOutputSize(size)
        settings.setBackgroundColor(QColor("white"))
        image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("white"))
        painter = QPainter(image)
        QgsMapRendererCustomPainterJob(settings, painter).renderSynchronously()
        painter.end()
    finally:
        for layer, renderer in saved:
            layer.setRenderer(renderer)

    outside = sum(1 for f in errors.getFeatures()
                  if f.hasGeometry() and not extent.contains(f.geometry().boundingBox()))
    return image, outside


def write_pdf_report(data, path, map_image=None) -> Path:
    document = QTextDocument()
    if map_image is not None:
        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl(MAP_RESOURCE),
                             map_image)
    document.setHtml(render_report_html(data, MAP_RESOURCE if map_image is not None else None))
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    writer.setTitle(data.title)
    (getattr(document, "print_", None) or document.print)(writer)
    return Path(path)


def export_reports(result, folder, stem="geomigrate_report", label="") -> list:
    """Write the PDF and both CSV files into folder. Returns the paths written."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    data = report_data_from_result(result, label)
    image, outside = render_map_image(result)
    if outside:
        data.map_note = (f"{outside} finding(s) lie outside the area shown "
                         "(see the CSV for their coordinates).")
    pdf = write_pdf_report(data, folder / f"{stem}.pdf", image)
    return [pdf, *write_csv_reports(data, folder, stem)]
