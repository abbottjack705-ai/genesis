from __future__ import annotations

import json
import multiprocessing
import os
import unittest
from pathlib import Path

from genesis.registry import AppendOnlyJsonl, RegistryConflict
from genesis.repro import canonical_json, sha256_bytes
from ._support import scratch_directory


def _append_worker(path: str, start, worker: int, count: int) -> None:
    log = AppendOnlyJsonl(path)
    start.wait()
    for item in range(count):
        log.append({"record_type": "stress", "worker": worker, "item": item})


def _conditional_worker(path: str, start, worker: int) -> None:
    log = AppendOnlyJsonl(path)
    start.wait()

    def build(records):
        if any(row.get("record_type") == "unique" for row in records):
            raise RegistryConflict("logical event already exists")
        return {"record_type": "unique", "worker": worker}

    try:
        log.transaction(build)
        os._exit(0)
    except RegistryConflict:
        os._exit(2)


class R1PersistenceTests(unittest.TestCase):
    def test_multiprocess_append_is_one_linear_chain(self):
        with scratch_directory() as root:
            path = root / "stress.jsonl"
            context = multiprocessing.get_context("spawn")
            start = context.Event()
            processes = [
                context.Process(target=_append_worker, args=(str(path), start, worker, 10))
                for worker in range(8)
            ]
            for process in processes:
                process.start()
            start.set()
            for process in processes:
                process.join(30)
                self.assertEqual(process.exitcode, 0)
            log = AppendOnlyJsonl(path)
            self.assertEqual(log.verify(), 80)
            records = log.records()
            self.assertEqual([row["sequence"] for row in records], list(range(1, 81)))
            self.assertEqual(len({(row["worker"], row["item"]) for row in records}), 80)

    def test_safety_precondition_and_append_share_one_transaction(self):
        with scratch_directory() as root:
            path = root / "conditional.jsonl"
            context = multiprocessing.get_context("spawn")
            start = context.Event()
            processes = [
                context.Process(target=_conditional_worker, args=(str(path), start, worker))
                for worker in range(2)
            ]
            for process in processes:
                process.start()
            start.set()
            for process in processes:
                process.join(30)
            self.assertEqual(sorted(process.exitcode for process in processes), [0, 2])
            self.assertEqual(AppendOnlyJsonl(path).verify(), 1)

    def test_truncated_or_tampered_log_fails_closed(self):
        with scratch_directory() as root:
            path = root / "broken.jsonl"
            log = AppendOnlyJsonl(path)
            log.append({"record_type": "one"})
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaisesRegex(RegistryConflict, "truncated"):
                log.verify()

    def test_valid_legacy_chain_remains_authoritative(self):
        with scratch_directory() as root:
            path = root / "legacy.jsonl"
            body = {"previous_hash": "0" * 64, "record_type": "legacy", "value": 1}
            path.write_bytes(canonical_json({**body, "record_hash": sha256_bytes(canonical_json(body))}))
            log = AppendOnlyJsonl(path)
            self.assertEqual(log.verify(), 1)
            log.append({"record_type": "new", "value": 2})
            self.assertEqual(log.verify(), 2)
            self.assertNotIn("sequence", json.loads(path.read_text().splitlines()[0]))
            self.assertEqual(json.loads(path.read_text().splitlines()[1])["sequence"], 2)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    unittest.main()
