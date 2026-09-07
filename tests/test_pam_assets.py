#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PamAssetTests(unittest.TestCase):
    def test_installer_manages_both_omarchy_lock_stacks(self):
        installer = (ROOT / "tools/install-pam.sh").read_text()

        self.assertIn("install_one omarchy-lock-password", installer)
        self.assertIn("install_one omarchy-lock-fingerprint", installer)
        self.assertIn("$backup_dir/$1.absent", installer)

    def test_rollback_restores_or_removes_every_managed_stack(self):
        rollback = (ROOT / "tools/rollback-pam.sh").read_text()

        self.assertIn(
            "sudo omarchy-lock-password omarchy-lock-fingerprint", rollback
        )
        self.assertIn("$backup_dir/$name.absent", rollback)
        self.assertIn('rm -f -- "/etc/pam.d/$name"', rollback)
        self.assertIn('rm -f -- "$backup" "$absent"', rollback)
        self.assertIn('rm -f -- "$absent"', rollback)

    def test_unprivileged_omarchy_password_stack_has_no_root_helper(self):
        password_stack = (ROOT / "pam/omarchy-lock-password").read_text()

        self.assertNotIn("t2-pam-unlock", password_stack)
        self.assertIn("pam_unix.so try_first_pass", password_stack)

    def test_sudo_skips_fingerprint_until_keybags_are_ready(self):
        sudo_stack = (ROOT / "pam/sudo").read_text()

        self.assertIn("[success=3 default=ignore]", sudo_stack)
        self.assertIn("[success=ignore default=2]", sudo_stack)
        self.assertIn("t2-pam-fingerprint-ready", sudo_stack)

    def test_sudo_prompt_warns_against_early_password_input(self):
        prompt = (ROOT / "src/t2-pam-fingerprint-prompt.c").read_text()

        self.assertIn("Do not type your password until", prompt)

    def test_every_successful_unlock_path_publishes_readiness(self):
        for name in (
            "t2-keybag-unlock.sh",
            "t2-pam-unlock.sh",
            "t2-credential-unlock.sh",
        ):
            source = (ROOT / "src" / name).read_text()
            self.assertIn("keybags-unlocked", source)
            self.assertIn("install -o root -g root -m 0600", source)
            normalized = source.upper()
            self.assertIn('CMP -S -- "$SNAPSHOT" "$STATE_FILE"', normalized)
            self.assertIn('MV -F -- "$SNAPSHOT" "$READY_FILE"', normalized)

        loader = (ROOT / "src/t2-keybag-load.sh").read_text()
        self.assertIn('rm -f -- "$READY_FILE"', loader)


if __name__ == "__main__":
    unittest.main()
