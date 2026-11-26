"""The plugin entry point wires up the menu action and the Processing provider."""
from unittest.mock import MagicMock

import pytest

pytest.importorskip("qgis.core")

from qgis.core import QgsApplication
from qgis.PyQt.QtWidgets import QWidget

from geomigrate_qa import classFactory


def test_plugin_registers_and_unregisters_cleanly(qgis_app):
    iface = MagicMock()
    window = QWidget()
    iface.mainWindow.return_value = window

    plugin = classFactory(iface)
    plugin.initGui()
    registry = QgsApplication.processingRegistry()
    assert registry.algorithmById("geomigrate:migrate_validate") is not None
    iface.addPluginToDatabaseMenu.assert_called_once()  # DB tool: Database menu

    plugin.unload()
    assert registry.algorithmById("geomigrate:migrate_validate") is None
    iface.removePluginDatabaseMenu.assert_called_once()


def test_processing_provider_is_registered_only_once(qgis_app):
    iface = MagicMock()
    iface.mainWindow.return_value = QWidget()
    plugin = classFactory(iface)
    plugin.initProcessing()  # QGIS calls this early, then initGui calls it again
    first = plugin.provider
    plugin.initGui()
    assert plugin.provider is first
    plugin.unload()
    assert QgsApplication.processingRegistry().algorithmById("geomigrate:migrate_validate") is None
