from qgis.core import QgsApplication
from qgis.PyQt.QtWidgets import QAction

MENU = "&GeoMigrate QA"


class GeoMigratePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.provider = None
        self.dialog = None

    def initGui(self):
        self.action = QAction("Migrate and validate...", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(MENU, self.action)
        self._init_processing()

    def _init_processing(self):
        from .algorithms.provider import GeoMigrateProvider
        self.provider = GeoMigrateProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        self.iface.removePluginMenu(MENU, self.action)
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
        self.dialog = None

    def run(self):
        from .gui.dialog import MigrationDialog
        self.dialog = MigrationDialog(self.iface.mainWindow(), self.iface)
        self.dialog.show()
