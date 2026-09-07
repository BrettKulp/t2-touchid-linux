#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }

tool=/usr/local/sbin/t2-aks-tool
state_file=/run/t2-touchid/keybag.env
ready_file=/run/t2-touchid/keybags-unlocked
[[ -x $tool && -r $state_file ]] || { echo "Keybag runtime state is unavailable." >&2; exit 1; }

rm -f -- "$ready_file"
snapshot=$(mktemp "${ready_file}.XXXXXX")
trap 'rm -f -- "$snapshot"' EXIT
install -o root -g root -m 0600 "$state_file" "$snapshot"

session=$(sed -n 's/^T2_KEYBAG_SESSION=\([0-9][0-9]*\)$/\1/p' "$snapshot")
handle=$(sed -n 's/^T2_KEYBAG_HANDLE=\(-\{0,1\}[0-9][0-9]*\)$/\1/p' "$snapshot")
special=$(sed -n 's/^T2_KEYBAG_SPECIAL=\(-\{0,1\}[0-9][0-9]*\)$/\1/p' "$snapshot")
[[ -n $session && -n $handle && -n $special ]] || { echo "Keybag runtime state is invalid." >&2; exit 1; }

"$tool" unlock-keybag "$session" "$handle"
"$tool" unlock-keybag "$session" "$special"
cmp -s -- "$snapshot" "$state_file" || { echo "Keybag runtime state changed during unlock." >&2; exit 1; }
mv -f -- "$snapshot" "$ready_file"
trap - EXIT
echo "Both keybags are unlocked for this boot."
