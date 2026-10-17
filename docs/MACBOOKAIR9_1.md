# MacBookAir9,1: bridgeOS 23P2048

This contributor report records a Linux-only setup on a 2020 Intel MacBook Air
on 2026-10-13. Identity creation and activation completed with creation version
4; the user subsequently confirmed fingerprint enrollment, verification, and
sudo authentication. The default version 5 attempt had stopped with an
ambiguous creation outcome.

This is evidence for one machine and firmware combination. It does not establish
support for all MacBook Air models, qualify the complete installation wrapper,
or provide a general recovery procedure.

## Tested configuration

| Component | Observed value |
| --- | --- |
| Mac model | MacBookAir9,1 (2020 Intel MacBook Air) |
| Bridge product type | iBridge2,15 |
| bridgeOS version / build | 10.2 / 23P2048 |
| Distribution | Omarchy / Arch Linux |
| Kernel | `7.2.7-arch1-Watanare-T2-2-t2` |
| T2Touch source revision | `748dd2de695413334e178c2304da7b9fa5e927f1` |
| Completed identity-create version | 4 |
| macOS installation / exported macOS state | Neither present nor used |

Firmware version and build came from the live Remote Service Discovery peer
properties. The report includes only public platform metadata, not the peer's
private identifiers.

## Installation and creation-version observations

The core `install.sh` was invoked for the desktop account using graphical
privilege elevation. The Omarchy wrapper's optional QML and display changes
were not applied. The installer staged the packaged `applesmc-t2touch` DKMS
prerequisite and regenerated the Limine boot image. After restart, the live
boot-state publisher reported `response-received:1`.

With the default loaded `identity_create_version=5`:

- Two read-only primary-inventory observations returned SEP status `-3`,
  satisfying the driver's stable-empty preflight.
- AKS creation operation `0x01` returned SEP status `-13`.
- The first-run service stopped with `AKS create outcome is ambiguous; the
  operation must not be retried`.
- The validated provisioning journal had phase `outcome-unknown`, with no
  recorded live handle, exported keybag, or committed account mapping.

Status `-13` alone did not establish that the request had no effect. Automatic
biometric setup was held and the transaction record was preserved. No creation
request was replayed in that boot, and the SEP-pinned transport was not unloaded.

After another restart, the recovery-capable transport produced fresh stable
primary-absence evidence. A separate local helper checked that the boot and
transport generation differed, the failed transaction was limited to initial
creation, and no saved authority existed. It archived the original journal
alongside the new no-change evidence while leaving automatic setup held.
This helper is **not part of T2Touch** and is not included in this contribution;
the result does not validate a supported recovery CLI or recommend moving or
editing journals manually.

Creation version 4 was explicitly configured in
`/etc/modprobe.d/t2-sep-create-version.conf`, following the configuration described
in the [MacBookPro16,2 report](MACBOOKPRO16_2.md). After rebuilding the boot image
and restarting, the live module parameter reported `4`. The unchanged core
installer then completed identity creation, activation, service startup, and PAM
installation with exit status 0.

A privacy-safe doctor report passed the configuration, loaded/installed module,
AKS device, native-first-run, biometric readiness, post-reboot reconciliation,
fprintd, encrypted credential, and cached BridgeXPC reachability checks. Its
remaining warning concerned unqualified suspend/resume; sleep policy was not
changed.

Version 4 success on this Air extends the reported hardware evidence for
bridgeOS 23P2048. It does not establish why version 5 failed or justify automatic
protocol fallback based on a Mac model or creation error.

## Authentication evidence and remaining limits

After the installer requested logout/login, the user was instructed to run
`t2-touchid-enroll` followed by `t2-touchid-verify` and confirmed that it worked.
The user then tested sudo authentication and also reported success. These are
user-reported positive controls; no raw authentication transcript or biometric
capture is published.

The installed sudo and Omarchy password PAM paths retained password fallback,
and the installer saved the original managed PAM files. An explicit password
fallback authentication control was not recorded.

The following remain unverified in this report:

- Rejection of an unenrolled finger.
- Fingerprint persistence and authentication after a subsequent reboot or cold
  T2 reset. The setup restarts occurred before enrollment.
- Separate graphical lock-screen and PolicyKit authentication transactions.
- Return to a responsive desktop after fingerprint unlock.
- Additional fingerprints, fingerprint deletion, and recovery of an enrolled
  inventory.
- Suspend/resume and other firmware builds.
- The complete `install-omarchy.sh` wrapper, including its optional desktop
  integrations.

The report qualifies initial Linux-native setup and the reported positive
authentication controls only. It does not constitute a security audit or full
end-to-end hardware qualification.
