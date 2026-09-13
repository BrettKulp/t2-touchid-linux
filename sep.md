# SEP Endpoint-7 Recovery Notes

This document is the working handoff for diagnosing and eventually recovering
AppleKeyStore (AKS) endpoint 7 on the Apple T2. It focuses on the failure where
Linux registers out-of-line (OOL) DMA buffers but capability negotiation times
out, leaving `t2_sep_transport` loaded without `/dev/t2-aks`.

The current code detects and contains this state. It does **not** implement a
verified in-Linux endpoint reset. The only recovery proven on the tested
`MacBookPro15,2` is to boot macOS, log in, successfully use an already-enrolled
finger with Touch ID, shut down, and then boot Linux.

## Safety Rules

These rules apply before any investigation or code change:

1. Treat a full endpoint-7 transport load as a one-attempt operation per Linux
   boot.
2. Once a full `register_ool=1` attempt begins, never unload, unbind, replace,
   or retry the module during that boot, regardless of whether `/dev/t2-aks`
   exists. Reboot before replacing it. Only an observation-only instance with
   `register_ool=N` may be replaced by the installed loader.
3. In particular, `register_ool=Y` plus no `/dev/t2-aks` is a blocked boot. Stop.
4. A missing registration reply does not prove SEP failed to retain the DMA
   address. Keep all potentially exposed memory allocated until reboot.
5. Do not repeatedly restart biometric-port discovery. Repeated
   256-concurrent BridgeXPC scans caused a `cdc_ncm` watchdog and an
   `apple_bce` kernel failure on the tested machine.
6. Do not overlap BridgeXPC discovery traffic with endpoint-7 capability
   negotiation.
7. Use `s2idle`, not deep S3. Deep resume can break T2 communication until
   reboot.
8. Keep macOS bootable and preserve Linux password authentication.
9. Do not publish logs or captures containing keybags, Catacomb data, UUIDs,
   serials, MAC addresses, link-local addresses, DMA or physical addresses,
   raw payloads, or credentials.

Do not experiment with guessed reset mailbox commands on a normal installation.
A wrong reset sequence can free or replace memory that SEP may still access.

## Relevant Hardware and Protocol

The currently tested configuration is:

- Intel `MacBookPro15,2`
- Apple T2 SEP PCI device `106b:1802`
- bridgeOS `23P350`
- Linux T2 kernel `6.19.11-arch1-Watanare-T2-2-t2`

Important transport constants in `src/t2_sep_transport.c`:

| Item | Value | Purpose |
| --- | --- | --- |
| SEP PCI vendor/device | `0x106b:0x1802` | T2 SEP PCI function |
| Mailbox BAR | BAR 4 | Inbox/outbox MMIO |
| Control endpoint | 0 | OOL registration messages |
| AKS endpoint | 7 | AppleKeyStore operations |
| ACM endpoint | 10 | Separate optional research transport |
| OOL input registration | control message 2 | Register one 16 KiB DMA buffer |
| OOL output registration | control message 3 | Register the other 16 KiB DMA buffer |
| OOL buffer size | `0x4000` | 16 KiB each |
| DMA address width | 44 bits | Coherent DMA mask |
| Mailbox wait | 5 seconds per wait | A timeout is outcome-ambiguous |
| AKS capability operation | `0x4d` | Required startup negotiation |

The startup capability request uses the version-1 AKS envelope. Normal
`/dev/t2-aks` exchanges use the version-2 envelope and a nonzero transaction
identifier.

## Expected Boot Sequence

The intended boot order is:

1. `t2-bridge-network.service` prepares the private T2 IPv6 network.
2. `t2-biometric-port-refresh.service` performs one full BridgeXPC port scan in
   its normal boot invocation and stores the validated dynamic port. Its
   `RemainAfterExit=yes` state prevents another plain start after success, but
   the helper has no per-boot stamp: never restart the unit or invoke the helper
   directly after any scan attempt.
3. `t2-sep-transport.service` waits an additional five-second quiet period.
4. `t2-sep-transport-load` replaces only an observation-only module, if one was
   auto-loaded.
5. It explicitly loads full mode with:

   ```sh
   modprobe t2_sep_transport register_ool=1 probe_capabilities=1
   ```

6. The driver allocates both coherent OOL buffers, pins the module before the
   first registration dispatch, registers both buffers, and performs the
   capability query.
7. Only after successful capability negotiation does it create root-only
   `/dev/t2-aks`.
8. `t2-keybag-load.service` loads the private keybag and writes the boot-specific
   handle to `/run/t2-touchid/keybag.env`.

After the common startup, unlock behavior depends on configuration:

- With an encrypted system credential, `t2-credential-unlock.service` unlocks
  both handles, `t2-biometric-ready.service` performs the cache-only warm-up,
  and then `fprintd` starts.
- In the default manual mode, the credential and warm-up units are skipped.
  `fprintd` may start, but verification remains fail-closed until the first
  password-authenticated sudo or `sudo t2-keybag-unlock` unlocks both handles.
- `t2-interactive-unlock.service` is an optional password-agent path and is
  installed disabled by default.

A byte-identical root-only `/run/t2-touchid/keybags-unlocked` marker records
that a trusted unlock helper observed successful unlocks for both handles while
`keybag.env` remained unchanged. It is not an independent live SEP read-back.

The positive endpoint-7 kernel sequence is:

```text
registered 16 KiB endpoint-7 OOL input/output buffers
AppleKeyStore capability reply passed integrity check: value=0x2 length=92
root-only /dev/t2-aks exchange enabled for whitelisted operations
```

Healthy startup requires all of the following, not merely a loaded module:

- `register_ool=Y`
- an integrity-valid capability reply
- `/dev/t2-aks` present as a root-owned mode-`0600` character device
- `t2-sep-transport.service` completed successfully

The current kernel and readiness script classify any integrity-valid,
status-zero capability response as startup success and log its value. The
tested expected value is `0x2`; `t2-aks-tool capabilities` applies the stricter
requirement that the value equal `0x2`.

## State Matrix

| State | Module | `register_ool` | `/dev/t2-aks` | Meaning | Safe action |
| --- | --- | --- | --- | --- | --- |
| Pristine | absent | unavailable | absent | No transport attempt this boot | Read-only preflight; one controlled attempt may be allowed |
| Observation-only | loaded | `N` | absent | BAR mapped and status read; no OOL DMA exposed | The service loader may replace this instance |
| Healthy full transport | loaded | `Y` | present | OOL buffers registered and startup negotiation accepted | Continue with keybag loading |
| Blocked startup | loaded | `Y` | absent | DMA may be retained; registration or negotiation failed | Do not retry or unload; recover through macOS |
| Historical failed attempt | absent or loaded | unavailable or `Y` | absent | Current-boot journal proves a failed full attempt | Treat as blocked even if another action changed visible state |
| Later logical poison | loaded | `Y` | usually present | A normal exchange became ambiguous or malformed | Stop endpoint-7 exchanges and reboot; use macOS if the next clean Linux boot remains stale |
| Keybag loaded but locked | loaded | `Y` | present | `keybag.env` exists but ready marker is absent or different | Unlock both live handles carefully |
| Keybags ready | loaded | `Y` | present | Runtime and ready files are byte-identical | Fingerprint verification may proceed |
| Password rejected | loaded | `Y` | present | Empty root-only rejection marker exists | Retry `sudo t2-keybag-unlock`; do not reload transport |

### Observation-only is not failure

The module defaults to `register_ool=0`. An early PCI modalias load should only
map BAR4, report mailbox state, and log:

```text
observation-only mode; no DMA allocation or MMIO writes
```

It does not enable PCI bus mastering, allocate OOL memory, write to the mailbox,
or create `/dev/t2-aks`. This state is deliberately replaceable.

Module parameters are root-readable. An unprivileged empty read must never be
interpreted as `N`. Use:

```sh
sudo cat /sys/module/t2_sep_transport/parameters/register_ool
```

### Blocked startup is failure

The definitive live-state signature is:

```text
/sys/module/t2_sep_transport exists
register_ool is Y
/dev/t2-aks is absent
```

Common kernel messages are:

```text
OOL input registration failed or became ambiguous; retaining DMA memory until reboot
OOL input registered but output registration failed; reboot before retry
AppleKeyStore capability negotiation failed: -110; /dev/t2-aks disabled until reboot
```

The userspace loader may report:

```text
t2_sep_transport is active with register_ool=1 but /dev/t2-aks is absent; reboot required
t2_sep_transport loaded without creating /dev/t2-aks
```

The PCI probe deliberately returns with the driver resident after DMA exposure
errors. This is containment, not success: it keeps potentially SEP-referenced
memory alive. The loader detects the missing device and fails the service.

## Read-Only Diagnosis

Prefer the repository preflight first:

```sh
sudo tools/check-t2-linux-readiness.sh
```

Its transport outcomes are:

- `READY`: no transport attempt occurred and prerequisites permit one
  controlled attempt.
- `INITIALIZED`: capability negotiation passed and `/dev/t2-aks` exists.
- `BLOCKED`: transport was attempted without a healthy device. Do not retry.
- `NOT_READY`: another prerequisite is missing.

The preflight intentionally does not repair networking, scan ports, load the
module, or restart services.

Additional read-only commands:

```sh
sudo t2-touchid-doctor
sudo t2-touchid-doctor --json
systemctl status t2-sep-transport.service --no-pager -l
systemctl status t2-keybag-load.service --no-pager -l
systemctl status t2-biometric-port-refresh.service --no-pager -l
sudo journalctl -b -u t2-sep-transport.service --no-pager
sudo journalctl -b -k --no-pager
ls -l /dev/t2-aks
sudo cat /sys/module/t2_sep_transport/parameters/register_ool
```

Useful filtered kernel review:

```sh
sudo journalctl -b -k --no-pager | grep -E \
  't2_sep_transport|AppleKeyStore|endpoint-7|OOL|t2-aks|NETDEV WATCHDOG|apple_bce'
```

Do not publish the unreviewed output. Redact hardware identifiers and network
addresses first.

## Decision Tree

### `/dev/t2-aks` exists

1. Confirm `register_ool=Y` and the capability-success message exists.
2. Check `t2-keybag-load.service`.
3. If `/run/t2-touchid/keybag.env` exists but readiness does not, unlock the
   loaded handles; do not reload transport.
4. If the password was rejected, use `sudo t2-keybag-unlock` with the correct
   macOS login password.
5. If a later AKS ioctl returns shutdown after an ambiguous exchange, treat the
   logical endpoint as poisoned even though the device node remains present.

### `/dev/t2-aks` is absent and the module is absent

1. Inspect the current-boot journal before doing anything.
2. If there is no evidence of a prior attempt, run the read-only preflight.
3. Only `RESULT: READY` permits one controlled service start.
4. If the journal shows a prior failed full attempt, treat the boot as blocked;
   do not assume unloading already made it safe.

### `/dev/t2-aks` is absent and `register_ool=N`

This is normally observation-only. The installed service loader is designed to
unbind and replace only this mode. Do not manually duplicate the loader steps
without first confirming there was no earlier full attempt during the boot.

### `/dev/t2-aks` is absent and `register_ool=Y`

Stop immediately. Do not run any of these commands:

```text
systemctl restart t2-sep-transport.service
modprobe -r t2_sep_transport
rmmod t2_sep_transport
manual PCI unbind/rebind
another full modprobe
another endpoint-7 OOL registration
```

Linux sudo remains available. The PAM hook detects this exact state and prints:

```text
T2 Touch ID unavailable for this boot: SEP startup failed. Boot macOS and use Touch ID, then reboot into Linux.
```

It does not request a macOS password that SEP cannot consume.

## Proven Recovery

This means booting normal macOS, **not** entering macOS Recovery OS:

1. Stop Linux investigation without retrying or unloading the module.
2. For a controlled recovery boot, disable every unit that can pull the chain:

   ```sh
   sudo systemctl disable fprintd.service t2-sep-transport.service \
     t2-keybag-load.service t2-credential-unlock.service \
     t2-biometric-ready.service
   ```

   Confirm all five report `disabled`. Disabling only the transport unit is not
   sufficient because `fprintd` and downstream units have dependencies that can
   pull it in. Do not mask units installed directly under `/etc/systemd/system`.
3. Boot macOS and log in normally.
4. Confirm an existing enrolled finger works through macOS Touch ID.
5. Do not add, delete, rename, or re-enroll fingerprints as part of recovery.
6. Shut macOS down.
7. Wait about 30 seconds.
8. Boot Linux.
9. Before any transport operation, confirm the five units remain disabled and
   run the read-only preflight. Require `RESULT: READY` before one controlled
   start.

If the units are intentionally left enabled for normal automatic startup, the
boot may consume the one allowed full attempt before login. In that case inspect
the result and do not issue a second manual attempt. Re-enable the units only
after controlled recovery validation is complete.

Observed evidence on 2026-09-06:

- repeated Linux reboots did not recover endpoint 7
- full shutdowns from Linux did not reliably recover it
- waiting longer in Linux did not recover it
- after macOS login and successful Touch ID use, the next Linux capability
  probe succeeded at about 175 seconds uptime

This supports the conclusion that the complete macOS boot sequence
reinitialized relevant T2/SEP state and that elapsed Linux uptime was not the
recovery mechanism. The evidence does not isolate whether login, Touch ID use,
a daemon action, shutdown, or another bridgeOS transition was necessary.

## Why There Is No Current Linux Recovery

Linux presently knows how to allocate and register endpoint-7 OOL buffers, but
it does not implement the complete Apple endpoint lifecycle.

The critical ambiguity is this sequence:

1. Linux sends an OOL registration containing a DMA address.
2. SEP may consume and retain that address.
3. Linux times out before receiving the acknowledgement.
4. Linux cannot distinguish "SEP never registered it" from "SEP registered it
   and the reply was lost or stale."

Freeing the DMA memory, unloading the module, or registering replacement buffers
could therefore leave SEP accessing freed or repurposed host memory.

Matching Apple transport research in `enrollment_research/FINDINGS.md` shows
that OOL reset is more than clearing memory. Apple's lifecycle includes:

- acquiring the SEP endpoint and installing a callback
- enabling the endpoint
- maintaining separately allocated send and receive OOL descriptors
- disabling the endpoint around relevant power/lifecycle transitions
- re-enabling or reacquiring the endpoint during reset
- registering both existing OOL descriptors again
- replacing a stale host mapping if the receive mapping changed
- serializing commands and rejecting late or mismatched replies

The recovered detail is currently strongest for AppleCredentialManager endpoint
10, but it establishes the class of lifecycle that must be recovered exactly
for AppleKeyStore endpoint 7. It is not safe to assume endpoint 7 uses identical
commands or ordering without matching AppleKeyStore evidence.

## Requirements for a Linux Recovery Implementation

Do not expose automatic recovery until all of these are satisfied:

1. Recover from a matching AppleKeyStore driver whether endpoint 7 has disable,
   release/reacquire, enable, and OOL-reset operations, and determine their
   exact ordering. Do not assume the endpoint-10 lifecycle applies unchanged.
2. Identify the endpoint-manager APIs or wire messages involved in endpoint-7
   lifecycle transitions and their completion semantics. Do not assume disable
   or enable is an endpoint-0 mailbox control message.
3. Introduce an endpoint-7 generation counter.
4. Bind every request and reply to the active generation as well as operation
   and transaction identifier.
5. Mark any in-flight request outcome-unknown when reset starts.
6. Reject every late reply from the previous generation.
7. Keep old DMA mappings alive until SEP has definitively stopped referencing
   them.
8. Re-register both OOL directions after every generation change.
9. Do not expose `/dev/t2-aks` until capability negotiation passes on the new
   generation.
10. Expose endpoint-7 poison/generation state through a read-only info ioctl or
    sysfs diagnostic; current `aks_poisoned` is not externally observable.
11. Serialize reset against every AKS ioctl and all keybag operations.
12. Bound every wait and classify timeouts as ambiguous, never as proof that a
    command did not execute.
13. Preserve the root-only operation allowlist and secret-wiping guarantees.
14. Add fault injection for a lost first registration acknowledgement, lost
    second acknowledgement, late capability reply, malformed envelope, wrong
    transaction, and reply from an old generation.
15. Prove recovery first with read-only capability and keybag UUID operations.
16. Validate on hardware across cold boot, Linux reboot, Linux shutdown,
    macOS-to-Linux boot, suspend/resume, and an intentionally delayed reply.
17. Keep the current one-attempt, reboot-pinned behavior as the fallback until
    the complete lifecycle is proven.

Success is not merely recreating `/dev/t2-aks`. A valid recovery must preserve
DMA safety, reject stale replies, pass capability integrity, load and unlock the
correct boot-specific keybag handles, and complete positive and negative
fingerprint controls without mutating enrollment state.

## Logical Poison After Successful Startup

`src/t2_sep_transport.c` has a separate `aks_poisoned` flag for failures after
`/dev/t2-aks` was created. It is set when a normal exchange encounters:

- mailbox receive failure or timeout
- too many unrelated replies
- invalid envelope length
- invalid envelope version or metadata
- failed response integrity verification

Later endpoint-7 ioctls return `-ESHUTDOWN`. Ordinary nonzero SEP operation
status, including a wrong-password response, does not poison the endpoint.

Important limitation: there is no endpoint-7 info ioctl for `aks_poisoned` or a
generation number. `/dev/t2-aks` can remain present after poison. Device-node
presence proves startup succeeded, not that every later transaction is healthy.

Endpoint 10 has stronger generation and poison observability. Do not confuse its
`T2_ACM_IOC_GET_INFO` support with endpoint 7.

## Related but Distinct Failures

### Wrong macOS password

SEP status `-5` from AKS operation `0x04` means the macOS password was rejected.
This is not endpoint startup failure and does not require transport reload.

Expected response:

```text
macOS password was rejected; run sudo t2-keybag-unlock to retry.
```

The rejection marker is:

```text
/run/t2-touchid/keybag-password-rejected
```

### Loaded keybag is not an unlocked keybag

`/run/t2-touchid/keybag.env` records the current session, positive runtime
handle, and configured negative special alias. The positive handle can change
on every boot and must never be hardcoded.

Readiness requires a byte-identical private marker:

```text
/run/t2-touchid/keybags-unlocked
```

### BridgeXPC port-discovery failure

The dynamic biometric TCP port is separate from the PCI endpoint-7 mailbox.
Port discovery must finish before transport negotiation to avoid overlap, but a
working BridgeOS network does not prove endpoint 7 is healthy.

Never turn a discovery failure into repeated full-range scans. The normal boot
transaction invokes the refresh helper once and biometric readiness consumes
only the cache, but the helper itself has no per-boot stamp. Do not restart the
unit or invoke the helper directly after a scan attempt.

### `cdc_ncm` or `apple_bce` watchdog

If the current boot contains `NETDEV WATCHDOG`, repeated `apple_bce` cancellation
stacks, or `bad: scheduling from the idle thread!`, stop network and biometric
experiments. A crash or Linux-only reboot after SEP activity may leave endpoint
7 stale and require the macOS recovery sequence.

## Repository File Map

### Endpoint-7 kernel transport

- `src/t2_sep_transport.c`: PCI probe, mailbox I/O, coherent DMA allocation,
  endpoint-0 OOL registration, capability negotiation, operation allowlist,
  response validation, DMA pinning, and AKS poisoning.
- `src/t2_sep_transport_uapi.h`: ioctl ABI shared with userspace;
  `/dev/t2-aks` access is restricted by the driver-created mode-`0600` device.
- `src/t2_aks_protocol.h`: AKS wire constants and bounded request validation.
- `src/Makefile`: module and userspace helper builds.
- `dkms.conf`: installed DKMS module definition.

### Loading and boot ordering

- `src/t2-sep-transport-load.sh`: distinguishes observation-only from full
  state and performs the one explicit full load.
- `systemd/system/t2-sep-transport.service`: orders transport after discovery
  and adds the quiet delay.
- `systemd/system/t2-bridge-network.service`: prepares the T2 network before
  discovery.
- `src/t2-bridge-network-prepare.sh`: validates and prepares the private
  `cdc_ncm` path, including one narrowly gated delayed-bind recovery.
- `systemd/system/t2-biometric-port-refresh.service`: orders the one boot-time
  RemoteXPC discovery.
- `src/t2-biometric-port-refresh.sh`: one full dynamic-port scan per helper
  invocation; callers must not invoke it repeatedly during a boot.
- `src/t2-biometric-ready.sh`: cache-only BiometricKit warm-up; no rediscovery.
- `systemd/system/t2-biometric-ready.service`: credential-conditional warm-up
  ordering.
- `systemd/system/fprintd.service`: pulls the keybag chain and starts after its
  required readiness units.
- `systemd/system/t2-touchid-post-reboot.service`: read-only mutation
  reconciliation ordered before fprintd.
- `systemd/sleep.conf.d/90-t2-touchid-s2idle.conf`: applies the required
  `s2idle` suspend policy.
- `install.sh`: keeps modalias loading observation-only and installs/enables the
  ordered chain.

### AKS and keybag state

- `src/t2-aks-tool.c`: endpoint-7 userspace commands, capability query, keybag
  load/alias/unlock, SEP status handling, password memory protection, and
  read-only observations.
- `src/t2-keybag-load.sh`: loads the keybag and writes boot-specific runtime
  state.
- `src/t2-keybag-unlock.sh`: manual two-handle unlock.
- `src/t2-credential-unlock.sh`: encrypted system-credential unlock path.
- `src/t2-pam-unlock.sh`: post-Linux-password unlock, wrong-password marker,
  and blocked-transport terminal warning.
- `src/t2-pam-fingerprint-ready.sh`: root-only readiness gate.
- `src/t2_aks_transport.py`: bounded userspace adapter for whitelisted AKS
  operations.
- `src/t2_aks_observer.py`: stable double-read, private-file AKS observation.
- `src/t2_aks_state.py`: strict device/keybag state decoding and validation.
- `src/t2_system_credential.py`: protected system-credential handling used by
  higher-level authorization flows.
- `systemd/system/t2-keybag-load.service`: requires healthy transport.
- `systemd/system/t2-credential-unlock.service`: optional unattended unlock.
- `systemd/system/t2-interactive-unlock.service`: optional boot password-agent
  unlock; installed disabled by default.

### Diagnostics and authentication

- `tools/check-t2-linux-readiness.sh`: read-only `READY`, `INITIALIZED`,
  `NOT_READY`, or `BLOCKED` preflight.
- `src/t2-touchid-doctor.py`: module, device, service, keybag, build, network,
  sleep, and watchdog checks.
- `src/t2-fprintd.py`: refuses verification when keybags are not ready and
  reports recorded password rejection.
- `pam/sudo`: fingerprint readiness gate and password fallback.
- `tools/install-pam.sh`: guarded PAM installation.
- `tools/rollback-pam.sh`: restores project-managed PAM state.
- `tools/collect-suspend-diagnostics.sh`: redacted suspend/transport report.

### Evidence and research

- `docs/LINUX_BRINGUP_TROUBLESHOOTING.md`: concise safety and recovery guide.
- `linux-bringup-steps.md`: dated hardware observations and failure chronology.
- `README.md`: supported installation and recovery behavior.
- `ROADMAP.md`: endpoint-7 disable/reacquire and OOL reset work item.
- `enrollment_research/FINDINGS.md`: recovered Apple transport lifecycle and
  endpoint-10 evidence relevant to designing, but not guessing, endpoint-7
  recovery.
- `docs/SUSPEND_REPORT.md`: suspend-related transport constraints.

### Relevant tests

- `tests/test_biometric_port_refresh_assets.py`: ordering, delayed bind, and
  single-scan invariants.
- `tests/test_pam_assets.py`: unlock placement, rejection reporting, and
  blocked-transport warning.
- `tests/test_aks_tool.py` and `tests/t2_aks_tool_unit.c`: AKS helper hardening
  and wire construction.
- `tests/test_doctor.py`: readiness and transport diagnostics.
- `tests/test_t2_fprintd.py`: locked/rejected keybag behavior.
- `tests/test_suspend_policy.py`: observation-only defaults and sleep policy.

## Research Workflow

For future endpoint-7 recovery work:

1. Start from a known recovered macOS-to-Linux boot.
2. Disable every unit that can pull the keybag/transport chain while collecting
   controlled evidence.
3. Confirm a pristine Linux boot with the read-only preflight.
4. Record decoded field structure, tags, lengths, operation IDs, timing,
   endpoint state, and DMA descriptor lifetime. Keep raw captures private and
   redact DMA/physical addresses, UUIDs, payload bytes, and platform identifiers
   before committing or sharing them.
5. Compare a successful first registration, a failed/stale registration, sleep
   transition behavior, and macOS recovery behavior.
6. Recover endpoint-7 behavior from a matching AppleKeyStore binary before
   adding any reset command.
7. Implement generation tracking and fault injection before hardware reset
   experiments.
8. Test read-only operations first. Do not combine reset research with
   enrollment, rename, deletion, or Catacomb mutation.
9. After every ambiguous result, stop for the boot and preserve logs.
10. Run `tools/privacy-check.sh` before committing any new evidence.

The immediate engineering goal is not "retry until it works." It is to make the
endpoint lifecycle explicit enough that Linux can prove old DMA is no longer
referenced, establish a new generation, and reject every stale completion.
