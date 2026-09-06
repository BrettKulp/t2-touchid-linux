#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Provision the root-private local Catacomb from a macOS export."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path


INSTALLED_SOURCE = Path("/opt/t2-touchid/src")
LOCAL_SOURCE = Path(__file__).resolve().parent
SOURCE = LOCAL_SOURCE if (LOCAL_SOURCE / "t2_catacomb_local.py").is_file() else INSTALLED_SOURCE
sys.path.insert(0, str(SOURCE))

import t2_catacomb_local


CONFIG = Path("/etc/t2-touchid.conf")
STATE_ROOT = Path("/var/lib/t2-touchid")
STORE_ROOT = STATE_ROOT / "catacomb"
OPERATION_LOCK = Path("/run/t2-touchid/operation.lock")


class ProvisionCommandError(RuntimeError):
    pass


def apple_user_id(path: Path) -> int:
    info = path.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
    ):
        raise ProvisionCommandError("configuration is not private and root-owned")
    matches = re.findall(
        rb"^T2_TOUCHID_MACOS_USER_ID=([0-9]+)$", path.read_bytes(), re.MULTILINE
    )
    if len(matches) != 1:
        raise ProvisionCommandError("configured Apple UID is missing or duplicated")
    value = int(matches[0])
    if value > 0xFFFFFFFF:
        raise ProvisionCommandError("configured Apple UID is invalid")
    return value


def private_archive_copy(source: Path, destination_dir: Path, caller_uid: int) -> Path:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        source_fd = os.open(source, flags)
    except OSError as error:
        raise ProvisionCommandError("Catacomb archive cannot be opened safely") from error
    temporary: Path | None = None
    try:
        info = os.fstat(source_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid not in (0, caller_uid)
            or info.st_mode & 0o077
            or not 0 < info.st_size <= t2_catacomb_local.MAX_ARCHIVE_SIZE
        ):
            raise ProvisionCommandError(
                "Catacomb archive must be private and owned by root or the sudo caller"
            )
        descriptor, name = tempfile.mkstemp(
            prefix=".catacomb-import-", dir=destination_dir
        )
        temporary = Path(name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(os.dup(source_fd), "rb") as source_stream, os.fdopen(
                descriptor, "wb"
            ) as destination_stream:
                remaining = t2_catacomb_local.MAX_ARCHIVE_SIZE + 1
                while remaining:
                    chunk = source_stream.read(min(65536, remaining))
                    if not chunk:
                        break
                    destination_stream.write(chunk)
                    remaining -= len(chunk)
                if destination_stream.tell() > t2_catacomb_local.MAX_ARCHIVE_SIZE:
                    raise ProvisionCommandError(
                        "Catacomb archive grew beyond the size limit while copying"
                    )
                destination_stream.flush()
                os.fsync(destination_stream.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return temporary
    finally:
        os.close(source_fd)


def provision(source: Path, caller_uid: int) -> dict[str, object]:
    state_info = STATE_ROOT.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(state_info.st_mode)
        or state_info.st_uid != os.geteuid()
        or state_info.st_mode & 0o077
    ):
        raise ProvisionCommandError("state directory is not private and root-owned")
    runtime_info = OPERATION_LOCK.parent.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(runtime_info.st_mode)
        or runtime_info.st_uid != os.geteuid()
        or runtime_info.st_mode & 0o077
    ):
        raise ProvisionCommandError("runtime directory is not private and root-owned")

    lock_flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        lock_flags |= os.O_NOFOLLOW
    lock_fd = os.open(OPERATION_LOCK, lock_flags, 0o600)
    temporary: Path | None = None
    try:
        lock_info = os.fstat(lock_fd)
        if (
            not stat.S_ISREG(lock_info.st_mode)
            or lock_info.st_uid != os.geteuid()
            or lock_info.st_nlink != 1
            or lock_info.st_mode & 0o077
        ):
            raise ProvisionCommandError("operation lock is unsafe")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        temporary = private_archive_copy(source, STATE_ROOT, caller_uid)
        existed = os.path.lexists(STORE_ROOT)
        host, _store = t2_catacomb_local.provision_from_backup(
            temporary, STORE_ROOT, apple_user_id(CONFIG)
        )
        return {
            "identifiers_redacted": True,
            "identity_count": len(host["identity_records"]),
            "local_store_provisioned": not existed,
            "schema_version": 1,
        }
    except BlockingIOError as error:
        raise ProvisionCommandError("another Touch ID operation is active") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        os.close(lock_fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="private macOS Catacomb export")
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise ProvisionCommandError("run through sudo from the configured user")
        caller = os.environ.get("SUDO_UID", "")
        if not caller.isdecimal() or int(caller) == 0:
            raise ProvisionCommandError("sudo caller identity is unavailable")
        result = provision(args.archive, int(caller))
    except (
        KeyError,
        OSError,
        ProvisionCommandError,
        t2_catacomb_local.LocalCatacombError,
    ) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
