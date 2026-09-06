# Linux bring-up troubleshooting

This guide records a successful manual bring-up on a MacBookPro15,2 running
Omarchy, `linux-t2` 6.19.11, bridgeOS 23P350, and fprintd 1.94.5. Both an
enrolled-finger `verify-match` and an unenrolled-finger `verify-no-match` were
confirmed. It supplements the main installation guide with failure recovery
learned during that bring-up.

Do not publish values substituted for placeholders below. In particular, keep
account names, serials, UUIDs, MAC addresses, link-local addresses, keybags,
Catacomb files, and exported archives private.

## Safety rules

- Treat a full transport load as a one-attempt operation for the current boot.
- If capability negotiation fails, do not retry, unload, unbind, or replace the
  module. Its SEP DMA registration pins it until reboot.
- Do not install PAM until both positive and negative fingerprint controls pass.
- Keep macOS bootable. It is the proven recovery environment for stale SEP
  endpoint-7 state.
- Do not repeatedly restart BiometricKit port discovery. A repeated
  high-concurrency RemoteXPC scan triggered a `cdc_ncm` watchdog followed by an
  `apple_bce` kernel failure on the tested MacBookPro15,2.

## Prevent an early transport attempt

The transport must remain observation-only on an incidental PCI-modalias load.
Do not put `register_ool=1` or `probe_capabilities=1` in modprobe defaults. The
service loader supplies both parameters explicitly for the controlled load.

During manual bring-up, disable every service that can pull the transport
through a dependency:

```sh
sudo systemctl disable fprintd.service t2-sep-transport.service \
  t2-keybag-load.service t2-credential-unlock.service \
  t2-biometric-ready.service
```

Disabling a unit only prevents boot activation. Another active unit can still
pull a disabled service through `Requires=`. In particular, fprintd requires
the keybag chain and wants the static post-reboot reconciler. Confirm the five
units above are disabled before a recovery boot.

If PCI autoload must also be suppressed on the affected machine, use a module
blacklist and the active bootloader's kernel command line. A blacklist does not
block the service's explicit `modprobe`. Verify which bootloader is actually in
use before rebuilding an initramfs or editing a command line; do not assume a
generated UKI is the selected boot entry.

## Recover stale AppleKeyStore state

On the tested MacBookPro15,2, repeated Linux reboots and full shutdowns did not
recover AppleKeyStore after a capability timeout. Waiting longer in Linux also
did not help. The proven recovery was:

1. Boot macOS and log in.
2. Confirm the existing enrolled finger works in macOS Touch ID.
3. Do not add, delete, or rename fingerprints.
4. Shut macOS down, wait about 30 seconds, and boot Linux.
5. Before loading transport, confirm the module and `/dev/t2-aks` are absent and
   the transport service has no journal entries for the new boot.

After this sequence, capability negotiation succeeded within three minutes of
Linux uptime. This indicates the recovery action was macOS reinitializing SEP,
not elapsed Linux uptime.

## Stabilize BridgeOS networking

The T2 `cdc_ncm` interface may be repeatedly managed and disconnected by
NetworkManager because BridgeOS does not provide normal DHCP. Substitute the
interface and Linux link-local address determined for the machine:

```sh
nmcli device set <T2_INTERFACE> managed no
sudo sysctl -w net.ipv6.conf.<T2_INTERFACE>.autoconf=1
sudo ip -6 addr add <LINUX_LINK_LOCAL>/64 dev <T2_INTERFACE> scope link
```

Wait for IPv6 duplicate-address detection to finish. The address must no longer
be marked `tentative`. Discover the BridgeOS peer separately:

```sh
ping -6 -c 2 -I <T2_INTERFACE> 'ff02::1%<T2_INTERFACE>'
ip -6 neigh show dev <T2_INTERFACE>
```

The Linux address and BridgeOS peer address are different. Configure
`T2_TOUCHID_HOST` with the responding BridgeOS peer, not Linux's own address.
Using the local address can leave the port cache missing and later surface as
`fingerprint inventory unavailable`.

## Provision the local reconciliation baseline

Before preflight, provision the root-private local Catacomb once from the
private macOS export:

```sh
sudo t2-touchid-provision-catacomb \
  /private/path/t2-touchid-catacomb.tar.gz
```

This step was missing from the earlier installation flow. Without the local
baseline, fprintd correctly fails closed with `fingerprint inventory
unavailable`. The command validates the three expected components, creates the
store atomically, and accepts an existing store only when it is byte-equal.

Early versions of the dedicated macOS exporter omitted `source-stat.txt` while
preserving `root:wheel` metadata in tar headers. The baseline parser supports
those persisted exports only after validating the header metadata. New exports
include the sidecar.

## Run the read-only preflight

The repository includes a manual bring-up check that does not load transport,
refresh the port, or change networking:

```sh
sudo tools/check-t2-linux-readiness.sh
```

Before the one controlled transport attempt, require:

```text
RESULT: READY
```

`NOT_READY` means a prerequisite must be fixed first. `BLOCKED` means transport
was attempted without a healthy `/dev/t2-aks`; do not retry during that boot.

## Start transport exactly once

```sh
sudo systemctl start t2-sep-transport.service
sudo systemctl status t2-sep-transport.service --no-pager -l
ls -l /dev/t2-aks
sudo tools/check-t2-linux-readiness.sh
```

Success requires a root-only `/dev/t2-aks`, an integrity-checked capability
reply in the kernel log, and:

```text
RESULT: INITIALIZED
```

If the service takes about 12 seconds and reports capability error `-110`, the
state is pinned for that boot. Use the macOS recovery sequence before another
attempt.

## Provision and unlock the local state

Start the keybag service only after transport is proven:

```sh
sudo systemctl start t2-keybag-load.service
sudo cat /run/t2-touchid/keybag.env
```

The runtime handle is boot-specific. Never hardcode it.

Unlock both boot-specific handles with the macOS login password:

```sh
sudo sh -c 'set -e
  . /run/t2-touchid/keybag.env
  /usr/local/sbin/t2-aks-tool unlock-keybag "$T2_KEYBAG_SESSION" "$T2_KEYBAG_HANDLE"
  /usr/local/sbin/t2-aks-tool unlock-keybag "$T2_KEYBAG_SESSION" "$T2_KEYBAG_SPECIAL"'
```

Both operations must return `status=0`. SEP status `-5`, displayed by the tool
as `Remote I/O error`, is ordinary password rejection. If the normal handle
already succeeded and the second password was mistyped, retry only the special
handle carefully rather than reloading the keybag.

## Verify before PAM

Reuse a successful numeric port cache. Do not restart discovery merely to make
the cache newer.

```sh
sudo systemctl start fprintd.service
sudo t2-touchid-identities
sudo t2-touchid-fprint-status
fprintd-list "$USER"
```

Then run two separate controls:

```sh
fprintd-verify -f any "$USER"  # present an enrolled finger
fprintd-verify -f any "$USER"  # present only an unenrolled finger
```

Require `verify-match` for the enrolled finger and `verify-no-match` for the
unenrolled finger. The negative command exits nonzero by design.

Finally run:

```sh
sudo t2-touchid-doctor
```

In manual keybag-unlock mode, the encrypted credential is intentionally absent,
and the conditional credential-unlock and warm-up services are not required.
The warning means keybags must be unlocked manually after every boot. If the
kernel currently displays `deep` but the installed systemd policy specifies
`MemorySleepMode=s2idle`, systemd selects s2idle immediately before suspend.

Only after all of these checks and both physical controls pass should PAM be
installed, with an existing root shell kept open and password fallback tested.
