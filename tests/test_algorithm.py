"""The Processing algorithm, run headless (dry run: no database needed)."""
import json
from pathlib import Path

import pytest

pytest.importorskip("qgis.core")

from qgis.core import (
    QgsApplication,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingUtils,
)

from geomigrate_qa.algorithms.migrate_algorithm import MigrateAlgorithm
from geomigrate_qa.algorithms.provider import GeoMigrateProvider

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_data"
pytestmark = pytest.mark.skipif(
    not (SAMPLE / "demo_run.json").exists(),
    reason="run scripts/generate_sample_data.py and keep sample_data/demo_run.json",
)


def run(params):
    algorithm = MigrateAlgorithm()
    algorithm.initAlgorithm()
    context = QgsProcessingContext()
    feedback = QgsProcessingFeedback()
    results, ok = algorithm.run(params, context, feedback)
    return results, ok, context


def test_provider_registers_the_algorithm():
    registry = QgsApplication.processingRegistry()
    provider = GeoMigrateProvider()
    assert registry.addProvider(provider)
    try:
        assert registry.algorithmById("geomigrate:migrate_validate") is not None
    finally:
        registry.removeProvider(provider)


def test_dry_run_reports_the_known_findings():
    results, ok, context = run({"CONFIG": str(SAMPLE / "demo_run.json"), "ERRORS": "memory:"})
    assert ok and results["FINDINGS"] == 30 and results["LOADED"] == 0
    errors = QgsProcessingUtils.mapLayerFromString(results["ERRORS"], context)
    assert errors.featureCount() == 30


def test_bad_configuration_is_a_clean_failure(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"sources": {"poles": {"file": "nope.shp",
                                                        "template": "bundled:poles_shp.json"}}}))
    algorithm = MigrateAlgorithm()
    algorithm.initAlgorithm()
    with pytest.raises(QgsProcessingException, match="data file not found"):
        algorithm.processAlgorithm({"CONFIG": str(broken), "ERRORS": "memory:"},
                                   QgsProcessingContext(), QgsProcessingFeedback())
