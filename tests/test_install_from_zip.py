"""Install the built zip into a clean folder and run the demo from it, as a user would."""
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("qgis.core")

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "sample_data" / "demo_run.json"
pytestmark = pytest.mark.skipif(not DEMO.exists(), reason="sample_data/demo_run.json is missing")


def test_the_zip_runs_the_demo_on_its_own(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "package_plugin", ROOT / "scripts" / "package_plugin.py")
    packager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packager)

    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "geomigrate_qa", repo / "geomigrate_qa",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (repo / "LICENSE").write_text("licence text")
    target, _ = packager.build_package(repo, tmp_path / "dist")

    plugins = tmp_path / "profile" / "python" / "plugins"
    zipfile.ZipFile(target).extractall(plugins)

    script = f"""
import sys
sys.path.insert(0, {str(plugins)!r})
from qgis.core import QgsApplication
app = QgsApplication([], False)
app.initQgis()
import geomigrate_qa
assert geomigrate_qa.__file__.startswith({str(plugins)!r}), geomigrate_qa.__file__
from geomigrate_qa.core.runconfig import load_run_config
from geomigrate_qa.core.service import run_from_config
result = run_from_config(load_run_config({str(DEMO)!r}))
print("FINDINGS", len(result.report.findings))
"""
    # Keep the caller's environment intact (on Windows the QGIS launcher sets PYTHONPATH and
    # PATH for QGIS); the zip's folder is put on sys.path inside the script instead.
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    done = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=180, check=False)
    assert done.returncode == 0, done.stderr[-1500:]
    assert "FINDINGS 30" in done.stdout
