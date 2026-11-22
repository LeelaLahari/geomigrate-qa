"""The main dialog: pick files and templates, choose rules and a database, run, read the result.

Everything that can fail is turned into a message in the result box; the dialog never lets an
exception escape. The work runs in the main thread (fine for thousands of features); a
background task is the next improvement for very large files.
"""
from pathlib import Path

from qgis.core import QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.mapping import MappingError
from ..core.postgis_loader import LoadError, PgConnection
from ..core.report_pdf import export_reports
from ..core.rule_config import RuleConfigError
from ..core.runconfig import (
    DEFAULT_RULES,
    RunConfig,
    RunConfigError,
    SourceEntry,
    bundled_names,
    check_config,
    load_run_config,
    resolve_path,
    save_run_config,
)
from ..core.service import run_from_config, summarize

COL_NAME, COL_FILE, COL_TEMPLATE = 0, 1, 2
EXPECTED_ERRORS = (RunConfigError, MappingError, RuleConfigError, LoadError, ValueError)


class PathCell(QWidget):
    """A line edit with a Browse button."""

    def __init__(self, filters="All files (*)", parent=None):
        super().__init__(parent)
        self._filters = filters
        self.edit = QLineEdit()
        button = QToolButton()
        button.setText("...")
        button.clicked.connect(self._browse)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit)
        layout.addWidget(button)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose file", self.edit.text(),
                                              self._filters)
        if path:
            self.edit.setText(path)

    def text(self):
        return self.edit.text().strip()

    def setText(self, value):
        self.edit.setText(value or "")


class MigrationDialog(QDialog):
    def __init__(self, parent=None, iface=None, project=None):
        super().__init__(parent)
        self.iface = iface
        self.project = project or QgsProject.instance()
        self.last_result = None
        self.last_label = ""
        self.setWindowTitle("GeoMigrate QA: migrate and validate")
        self.resize(820, 700)
        self._build()

    # ---- layout ----
    def _build(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<b>1. Source files</b> (layer name becomes the table name)"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Layer name", "Data file", "Mapping template"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(COL_NAME, 110)
        self.table.setColumnWidth(COL_FILE, 330)
        layout.addWidget(self.table)
        row_buttons = QHBoxLayout()
        add = QPushButton("Add source")
        add.clicked.connect(lambda: self.add_row())
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self.remove_selected)
        row_buttons.addWidget(add)
        row_buttons.addWidget(remove)
        row_buttons.addStretch()
        layout.addLayout(row_buttons)

        layout.addWidget(QLabel("<b>2. Rules and reference data</b>"))
        form = QFormLayout()
        self.rules = QComboBox()
        self.rules.setEditable(True)
        self.rules.addItems(bundled_names("rules"))
        self.rules.setCurrentText(DEFAULT_RULES)
        self.reference = PathCell("GeoPackage (*.gpkg)")
        form.addRow("Rule set", self.rules)
        form.addRow("Trusted reference (optional .gpkg)", self.reference)
        layout.addLayout(form)

        self.load_box = QGroupBox("3. Load clean data to PostGIS (untick for a dry run)")
        self.load_box.setCheckable(True)
        self.load_box.setChecked(False)
        db = QFormLayout(self.load_box)
        self.host = QLineEdit("localhost")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(5432)
        self.dbname = QLineEdit("geomigrate")
        self.user = QLineEdit("postgres")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.schema = QLineEdit()
        for label, widget in (("Host", self.host), ("Port", self.port), ("Database", self.dbname),
                              ("User", self.user), ("Password (not saved)", self.password),
                              ("Target schema", self.schema)):
            db.addRow(label, widget)
        layout.addWidget(self.load_box)

        buttons = QHBoxLayout()
        for text, handler in (("Load configuration...", self.load_config_dialog),
                              ("Save configuration...", self.save_config_dialog)):
            button = QPushButton(text)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        buttons.addStretch()
        self.export_button = QPushButton("Export report...")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_report_dialog)
        buttons.addWidget(self.export_button)
        self.run_button = QPushButton("Run")
        self.run_button.setDefault(True)
        self.run_button.clicked.connect(self.run)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(self.run_button)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Results appear here.")
        layout.addWidget(self.output)

    # ---- table helpers ----
    def add_row(self, name="", file="", template=""):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, COL_NAME, QTableWidgetItem(name))
        cell = PathCell()
        cell.setText(file)
        self.table.setCellWidget(row, COL_FILE, cell)
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(bundled_names("template"))
        combo.setCurrentText(template)
        self.table.setCellWidget(row, COL_TEMPLATE, combo)

    def remove_selected(self):
        for index in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(index)

    # ---- config <-> widgets ----
    def build_config(self) -> RunConfig:
        sources = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COL_NAME)
            name = item.text().strip() if item else ""
            file = self.table.cellWidget(row, COL_FILE).text()
            template = self.table.cellWidget(row, COL_TEMPLATE).currentText().strip()
            sources.append(SourceEntry(
                name=name, file=file,
                template=str(resolve_path(template, Path.cwd(), "template")) if template else ""))
        rules = self.rules.currentText().strip() or DEFAULT_RULES
        reference = self.reference.text()
        return RunConfig(
            sources=tuple(sources),
            rules=str(resolve_path(rules, Path.cwd(), "rules")),
            reference_gpkg=reference or None,
            schema=self.schema.text().strip() or None,
            label="dialog run")

    def set_config(self, config: RunConfig):
        self.table.setRowCount(0)
        for source in config.sources:
            self.add_row(source.name, source.file, source.template)
        self.rules.setCurrentText(config.rules)
        self.reference.setText(config.reference_gpkg)
        self.schema.setText(config.schema or "")

    def load_config_from(self, path):
        try:
            self.set_config(load_run_config(path, check=False))
            self.show_message(f"Loaded configuration {Path(path).name}.")
        except RunConfigError as exc:
            self.show_message(str(exc), error=True)

    def save_config_to(self, path):
        try:
            config = self.build_config()
            problems = check_config(config)
            if problems:
                raise RunConfigError("\n".join(problems))
            save_run_config(config, path)
            self.show_message(f"Saved configuration to {path} (the password is not saved).")
        except RunConfigError as exc:
            self.show_message(str(exc), error=True)

    def load_config_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load run configuration", "",
                                              "Run configuration (*.json)")
        if path:
            self.load_config_from(path)

    def save_config_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save run configuration", "run.json",
                                              "Run configuration (*.json)")
        if path:
            self.save_config_to(path)

    # ---- running ----
    def show_message(self, text, error=False):
        self.output.setPlainText(("ERROR\n" if error else "") + text)

    def _connection(self):
        if not self.load_box.isChecked():
            return None
        if not self.schema.text().strip():
            raise RunConfigError("Enter a target schema, or untick the PostGIS box for a dry run.")
        return PgConnection(host=self.host.text().strip(), port=self.port.value(),
                            dbname=self.dbname.text().strip(), user=self.user.text().strip(),
                            password=self.password.text())

    def run(self):
        try:
            config = self.build_config()
            problems = check_config(config)
            if problems:
                raise RunConfigError("\n".join(problems))
            pg = self._connection()
        except EXPECTED_ERRORS as exc:
            self.show_message(str(exc), error=True)
            return None

        self.run_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = run_from_config(config, pg, config.schema if pg else None)
        except EXPECTED_ERRORS as exc:
            self.show_message(str(exc), error=True)
            return None
        finally:
            QApplication.restoreOverrideCursor()
            self.run_button.setEnabled(True)

        self.last_result = result
        self.last_label = config.sources[0].name if len(config.sources) == 1 else "migration run"
        self.export_button.setEnabled(True)
        self.show_message(summarize(result))
        self._add_layers(result)
        return result

    def export_report_to(self, folder):
        """Write the PDF and CSV reports for the last run into folder."""
        if self.last_result is None:
            self.show_message("Run a migration first, then export its report.", error=True)
            return []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            paths = export_reports(self.last_result, folder, label=self.last_label)
        except OSError as exc:
            self.show_message(f"Could not write the report: {exc}", error=True)
            return []
        finally:
            QApplication.restoreOverrideCursor()
        listing = "\n".join(f"  {p}" for p in paths)
        self.show_message(summarize(self.last_result) + f"\n\nReport written:\n{listing}")
        return paths

    def export_report_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder for the report")
        if folder:
            self.export_report_to(folder)

    def _add_layers(self, result):
        for name, layer in result.clean.items():
            layer.setName(f"{name} (clean)")
            self.project.addMapLayer(layer)
        result.error_layer.setName("validation_errors")
        self.project.addMapLayer(result.error_layer)
