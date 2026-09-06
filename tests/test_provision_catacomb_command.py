# SPDX-License-Identifier: GPL-2.0-only
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_catacomb_local import write_archive


SOURCE = Path(__file__).resolve().parents[1] / "src"
SPEC = importlib.util.spec_from_file_location(
    "t2_touchid_provision_catacomb", SOURCE / "t2-touchid-provision-catacomb.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProvisionCatacombCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.state = root / "state"
        self.runtime = root / "run"
        self.state.mkdir(mode=0o700)
        self.runtime.mkdir(mode=0o700)
        self.config = root / "config"
        self.config.write_text("T2_TOUCHID_MACOS_USER_ID=501\n")
        self.config.chmod(0o600)
        self.archive = root / "catacomb.tar.gz"
        write_archive(self.archive)
        self.archive.chmod(0o600)
        MODULE.CONFIG = self.config
        MODULE.STATE_ROOT = self.state
        MODULE.STORE_ROOT = self.state / "catacomb"
        MODULE.OPERATION_LOCK = self.runtime / "operation.lock"

    def tearDown(self):
        self.temp.cleanup()

    def test_provisions_once_and_then_verifies_equal_store(self):
        first = MODULE.provision(self.archive, os.getuid())
        second = MODULE.provision(self.archive, os.getuid())
        self.assertTrue(first["local_store_provisioned"])
        self.assertFalse(second["local_store_provisioned"])
        self.assertEqual(first["identity_count"], 1)
        self.assertFalse(list(self.state.glob(".catacomb-import-*")))

    def test_rejects_archive_symlink_without_creating_store(self):
        link = self.archive.with_name("link.tar.gz")
        link.symlink_to(self.archive)
        with self.assertRaises(MODULE.ProvisionCommandError):
            MODULE.provision(link, os.getuid())
        self.assertFalse(MODULE.STORE_ROOT.exists())

    def test_copy_is_bounded_if_archive_grows_after_initial_stat(self):
        actual_fstat = MODULE.os.fstat
        first = True

        def stale_size(descriptor):
            nonlocal first
            info = actual_fstat(descriptor)
            if first:
                first = False
                values = list(info)
                values[6] = 1
                return os.stat_result(values)
            return info

        with (
            mock.patch.object(MODULE.os, "fstat", side_effect=stale_size),
            mock.patch.object(MODULE.t2_catacomb_local, "MAX_ARCHIVE_SIZE", 16),
            self.assertRaises(MODULE.ProvisionCommandError),
        ):
            MODULE.private_archive_copy(self.archive, self.state, os.getuid())
        self.assertFalse(list(self.state.glob(".catacomb-import-*")))


if __name__ == "__main__":
    unittest.main()
