# SPDX-License-Identifier: GPL-2.0-only
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BiometricPortRefreshAssetTests(unittest.TestCase):
    def test_installer_and_uninstaller_own_service_and_helper(self):
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        uninstaller = (ROOT / "uninstall.sh").read_text(encoding="utf-8")
        for asset in (
            "t2-biometric-port-refresh.service",
            "t2-biometric-port-refresh",
        ):
            self.assertIn(asset, installer)
            self.assertIn(asset, uninstaller)


if __name__ == "__main__":
    unittest.main()
