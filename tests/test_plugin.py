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
    iface.addPluginToMenu.assert_called_once()

    plugin.unload()
    assert registry.algorithmById("geomigrate:migrate_validate") is None
    iface.removePluginMenu.assert_called_once()
