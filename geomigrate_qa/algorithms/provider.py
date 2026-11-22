from qgis.core import QgsProcessingProvider

from .migrate_algorithm import MigrateAlgorithm


class GeoMigrateProvider(QgsProcessingProvider):
    def id(self):
        return "geomigrate"

    def name(self):
        return "GeoMigrate QA"

    def loadAlgorithms(self):
        self.addAlgorithm(MigrateAlgorithm())
