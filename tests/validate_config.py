# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 vakio-kiv-ha contributors

"""Run the real HA configuration checker against the distributed files."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import custom_components.yandex_smart_home as yaha

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="vakio-config-check-") as directory:
        target = Path(directory)
        shutil.copytree(ROOT / "manual/blueprints", target / "blueprints")
        shutil.copytree(ROOT / "manual/includes", target / "includes")
        shutil.copytree(Path(yaha.__file__).parent,
                        target / "custom_components/yandex_smart_home",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(ROOT / "manual/configuration_vakio_additions.yaml",
                        target / "configuration.yaml")
        subprocess.run([sys.executable, "-m", "homeassistant", "--script",
                        "check_config", "-c", str(target)], check=True, timeout=60)
    print("PASS: Home Assistant configuration check for packaged blueprint, helpers, automation and YaHA")


if __name__ == "__main__":
    main()
