from pathlib import Path

from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

MENU = "&GeoMigrate QA"
ICON = Path(__file__).with_name("icon.png")


class GeoMigratePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.provider = None
        self.dialog = None

    def initProcessing(self):
        """Register the Processing provider (QGIS calls this early for hasProcessingProvider)."""
        if self.provider is None:
            from .algorithms.provider import GeoMigrateProvider
            self.provider = GeoMigrateProvider()
            QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()
        self.action = QAction(QIcon(str(ICON)), "Migrate and validate...", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToDatabaseMenu(MENU, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginDatabaseMenu(MENU, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
        self.dialog = None

    def run(self):
        from .gui.dialog import MigrationDialog
        self.dialog = MigrationDialog(self.iface.mainWindow(), self.iface)
        self.dialog.show()
