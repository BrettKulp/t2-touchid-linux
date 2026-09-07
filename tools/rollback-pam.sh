#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
backup_dir=/var/lib/t2-touchid/pam-backups
restored=0
for name in sudo omarchy-lock-password omarchy-lock-fingerprint; do
  backup=$backup_dir/$name.original
  absent=$backup_dir/$name.absent
  if [[ -f $backup ]]; then
    install -o root -g root -m 0644 "$backup" "/etc/pam.d/$name"
    rm -f -- "$backup" "$absent"
    restored=1
  elif [[ -f $absent ]]; then
    rm -f -- "/etc/pam.d/$name"
    rm -f -- "$absent"
    restored=1
  fi
done
[[ $restored == 1 ]] || { echo "No PAM backups found." >&2; exit 1; }
rm -f -- /etc/security/t2-touchid-sudo-prompt
echo "Original PAM files restored."
