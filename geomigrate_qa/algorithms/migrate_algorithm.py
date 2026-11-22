"""Processing algorithm: runs a saved run configuration (toolbox, batch, or qgis_process)."""
from pathlib import Path

from qgis.core import (
    Qgis,
    QgsDataSourceUri,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFile,
    QgsProcessingParameterProviderConnection,
    QgsProcessingParameterString,
    QgsProviderRegistry,
)

from ..core.mapping import MappingError
from ..core.postgis_loader import LoadError, PgConnection
from ..core.rule_config import RuleConfigError
from ..core.runconfig import RunConfigError, load_run_config
from ..core.service import run_from_config, summarize


class MigrateAlgorithm(QgsProcessingAlgorithm):
    CONFIG = "CONFIG"
    CONNECTION = "CONNECTION"
    SCHEMA = "SCHEMA"
    ERRORS = "ERRORS"

    def name(self):
        return "migrate_validate"

    def displayName(self):
        return "Migrate and validate spatial data"

    def group(self):
        return "Migration"

    def groupId(self):
        return "migration"

    def shortHelpString(self):
        return ("Imports the files listed in a run configuration, maps them to the target "
                "schema, checks them against the rule set, and writes the clean features to "
                "PostGIS. Features with errors are quarantined and listed in the errors "
                "output. Leave the connection empty for a dry run (validate only).")

    def createInstance(self):
        return MigrateAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.CONFIG, "Run configuration (JSON)", extension="json"))
        self.addParameter(QgsProcessingParameterProviderConnection(
            self.CONNECTION, "PostGIS connection (empty = dry run)", "postgres", optional=True))
        self.addParameter(QgsProcessingParameterString(
            self.SCHEMA, "Target schema (overrides the configuration)", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.ERRORS, "Validation errors", QgsProcessing.TypeVectorPoint))
        self.addOutput(QgsProcessingOutputNumber("FINDINGS", "Number of findings"))
        self.addOutput(QgsProcessingOutputNumber("LOADED", "Features loaded to PostGIS"))

    def _connection(self, name):
        metadata = QgsProviderRegistry.instance().providerMetadata("postgres")
        stored = metadata.findConnection(name) if metadata else None
        if stored is None:
            raise QgsProcessingException(f"PostgreSQL connection '{name}' was not found.")
        uri = QgsDataSourceUri(stored.uri())
        return PgConnection(host=uri.host(), port=int(uri.port() or 5432),
                            dbname=uri.database(), user=uri.username(),
                            password=uri.password())

    def processAlgorithm(self, parameters, context, feedback):
        path = self.parameterAsFile(parameters, self.CONFIG, context)
        name = self.parameterAsConnectionName(parameters, self.CONNECTION, context)
        schema = self.parameterAsString(parameters, self.SCHEMA, context) or None
        try:
            config = load_run_config(path)
            pg = self._connection(name) if name else None
            if pg and not (schema or config.schema):
                raise QgsProcessingException(
                    "A target schema is needed to load to PostGIS: set it here or in "
                    f"{Path(path).name}.")
            result = run_from_config(config, pg, schema)
        except (RunConfigError, MappingError, RuleConfigError, LoadError, ValueError) as exc:
            raise QgsProcessingException(str(exc)) from exc

        feedback.pushInfo(summarize(result))
        errors = result.error_layer
        sink, dest_id = self.parameterAsSink(
            parameters, self.ERRORS, context, errors.fields(), Qgis.WkbType.Point, errors.crs())
        for feature in errors.getFeatures():
            sink.addFeature(feature)
        loaded = sum(result.load.loaded.values()) if result.load else 0
        return {self.ERRORS: dest_id, "FINDINGS": len(result.report.findings), "LOADED": loaded}
