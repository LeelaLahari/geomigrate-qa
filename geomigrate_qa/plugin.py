from qgis.PyQt.QtWidgets import QAction
from qgis.core import Qgis

MENU = "&GeoMigrate QA"


class GeoMigratePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):
        self.action = QAction("Open GeoMigrate QA", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(MENU, self.action)

    def unload(self):
        self.iface.removePluginMenu(MENU, self.action)

    def run(self):
        self.iface.messageBar().pushMessage(
            "GeoMigrate QA", "Plugin loaded, v2.", level=Qgis.Info, duration=5)