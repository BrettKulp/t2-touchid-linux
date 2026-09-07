#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only

# PAM gate: success permits the following fingerprint modules; any failure
# skips directly to password authentication.
[[ $EUID -eq 0 ]] || exit 1
state_file=/run/t2-touchid/keybag.env
ready_file=/run/t2-touchid/keybags-unlocked
[[ -f $state_file && -f $ready_file ]] || exit 1
[[ $(stat -c '%a:%U:%G' "$state_file" 2>/dev/null) == 600:root:root ]] || exit 1
[[ $(stat -c '%a:%U:%G' "$ready_file" 2>/dev/null) == 600:root:root ]] || exit 1
cmp -s -- "$state_file" "$ready_file"
