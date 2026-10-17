# SPDX-License-Identifier: GPL-2.0-only
"""Durable ordering and completion contracts for delete-all."""

import tempfile
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import t2_identity_delete_batch_journal as batch
import t2_mutation_journal as mutation
import t2_mutation_registry as registry
from tests.test_mutation_journal import baseline


def two_identity_baseline():
    value = baseline()
    value["identity_records"].append(
        {
            "user_id": value["apple_uid"],
            "uuid": "00000000-0000-0000-0000-000000000002",
            "entity": 1,
        }
    )
    value["capacity"]["used"] = 2
    return value


class DeleteBatchJournalTests(unittest.TestCase):
    def test_rejected_append_preserves_history_and_allows_valid_start(self):
        cases = (
            (
                "DELETE_BATCH_ITEM_INTENT",
                {"finger_name": "finger-1", "ordinal": 0},
            ),
            ("DELETE_BATCH_STARTED", {}),
        )
        for milestone, evidence in cases:
            with (
                self.subTest(milestone=milestone),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                root.chmod(0o700)
                operation_id = "00000000-0000-0000-0000-000000000081"
                path = root / f"{operation_id}.jsonl"
                mutation.create(
                    path, "delete-batch", two_identity_baseline(), operation_id
                )
                history = batch.read(path)
                before = path.read_bytes()
                with self.assertRaises(batch.IdentityDeleteBatchJournalError):
                    batch.append_checked(path, history, milestone, evidence)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(batch.read(path), history)
                self.assertFalse(registry.blocks_new_mutation(root))
                current = batch.append_checked(
                    path,
                    history,
                    "DELETE_BATCH_STARTED",
                    {
                        "finger_names": ["finger-1", "finger-3"],
                        "identity_count": 2,
                        "identifiers_redacted": True,
                    },
                )
                self.assertEqual(current.phase, batch.IdentityDeleteBatchPhase.STARTED)
                self.assertTrue(registry.blocks_new_mutation(root))

    def test_torn_tail_repair_rejects_candidate_and_requires_fresh_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            operation_id = "00000000-0000-0000-0000-000000000081"
            path = root / f"{operation_id}.jsonl"
            mutation.create(
                path, "delete-batch", two_identity_baseline(), operation_id
            )
            stale = batch.read(path)
            baseline_records = mutation.read(path)
            torn_tail = b'{"milestone":'
            with path.open("ab") as stream:
                stream.write(torn_tail)
            with self.assertRaises(batch.IdentityDeleteBatchJournalError):
                batch.append_checked(path, stale, "DELETE_BATCH_STARTED", {})

            records = mutation.validate_records(path.read_bytes().splitlines(keepends=True))
            self.assertEqual(records[:-1], baseline_records)
            self.assertEqual(records[-1]["milestone"], "TORN_TAIL_TRUNCATED")
            self.assertEqual(records[-1]["evidence"], {"truncated_bytes": len(torn_tail)})
            repaired = batch.read(path)
            self.assertEqual(repaired.phase, batch.IdentityDeleteBatchPhase.BASELINE)
            self.assertFalse(registry.blocks_new_mutation(root))

            valid = {
                "finger_names": ["finger-1", "finger-3"],
                "identity_count": 2,
                "identifiers_redacted": True,
            }
            before_retry = path.read_bytes()
            with self.assertRaisesRegex(mutation.JournalError, "guarded append"):
                batch.append_checked(path, stale, "DELETE_BATCH_STARTED", valid)
            self.assertEqual(path.read_bytes(), before_retry)
            current = batch.append_checked(
                path, repaired, "DELETE_BATCH_STARTED", valid
            )
            self.assertEqual(current.phase, batch.IdentityDeleteBatchPhase.STARTED)
            self.assertTrue(registry.blocks_new_mutation(root))

    def test_stale_caller_history_cannot_append_to_a_newer_valid_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            operation_id = "00000000-0000-0000-0000-000000000081"
            path = root / f"{operation_id}.jsonl"
            mutation.create(
                path, "delete-batch", two_identity_baseline(), operation_id
            )
            stale = batch.read(path)
            current = batch.append_checked(
                path,
                stale,
                "DELETE_BATCH_STARTED",
                {
                    "finger_names": ["finger-1", "finger-3"],
                    "identity_count": 2,
                    "identifiers_redacted": True,
                },
            )
            before = path.read_bytes()
            with self.assertRaisesRegex(mutation.JournalError, "guarded append"):
                batch.append_checked(
                    path,
                    stale,
                    "DELETE_BATCH_ITEM_INTENT",
                    {"finger_name": "finger-1", "ordinal": 0},
                )
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(batch.read(path), current)
            self.assertTrue(registry.blocks_new_mutation(root))

    def test_ordered_items_reconcile_and_release_mutation_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            operation_id = "00000000-0000-0000-0000-000000000081"
            path = root / f"{operation_id}.jsonl"
            mutation.create(
                path, "delete-batch", two_identity_baseline(), operation_id
            )
            history = batch.read(path)
            history = batch.append_checked(
                path,
                history,
                "DELETE_BATCH_STARTED",
                {
                    "finger_names": ["finger-1", "finger-3"],
                    "identity_count": 2,
                    "identifiers_redacted": True,
                },
            )
            for ordinal, name in enumerate(history.finger_names):
                history = batch.append_checked(
                    path,
                    history,
                    "DELETE_BATCH_ITEM_INTENT",
                    {"finger_name": name, "ordinal": ordinal},
                )
                self.assertEqual(history.pending, name)
                self.assertTrue(registry.blocks_new_mutation(root))
                history = batch.append_checked(
                    path,
                    history,
                    "DELETE_BATCH_ITEM_RECONCILED",
                    {
                        "finger_name": name,
                        "ordinal": ordinal,
                        "remaining_count": 1 - ordinal,
                    },
                )
            history = batch.append_checked(
                path,
                history,
                "DELETE_BATCH_RECONCILED",
                {
                    "deleted_count": 2,
                    "identity_count": 0,
                    "identifiers_redacted": True,
                },
            )
            self.assertEqual(history.completed, ("finger-1", "finger-3"))
            self.assertFalse(registry.blocks_new_mutation(root))

    def test_skipped_or_reordered_item_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            operation_id = "00000000-0000-0000-0000-000000000082"
            path = root / f"{operation_id}.jsonl"
            mutation.create(
                path, "delete-batch", two_identity_baseline(), operation_id
            )
            history = batch.read(path)
            history = batch.append_checked(
                path,
                history,
                "DELETE_BATCH_STARTED",
                {
                    "finger_names": ["finger-2", "finger-5"],
                    "identity_count": 2,
                    "identifiers_redacted": True,
                },
            )
            mutation.append(
                path,
                operation_id,
                "DELETE_BATCH_ITEM_INTENT",
                {"finger_name": "finger-5", "ordinal": 0},
            )
            with self.assertRaisesRegex(
                batch.IdentityDeleteBatchJournalError, "misbound"
            ):
                batch.read(path)


if __name__ == "__main__":
    unittest.main()
