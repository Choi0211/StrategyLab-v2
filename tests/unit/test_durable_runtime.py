import os
import tempfile
import unittest

from gaon.runtime.scheduler import DurableScheduler, ScheduledJob, ScheduleSpec
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.worker import DuplicateMessageGuard, DurableTaskQueue, QueueItemStatus


class DurableRuntimeTest(unittest.TestCase):
    def test_queue_enqueue_lease_retry_success_and_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStateStore(os.path.join(tmp, "runtime.sqlite"))
            queue = DurableTaskQueue(store._connection)

            self.assertTrue(queue.enqueue("item-1", "research:req-1", {"request": "ORB"}, priority=2, available_at="2026-07-17T00:00:00Z"))
            self.assertFalse(queue.enqueue("item-dup", "research:req-1", {"request": "ORB"}, priority=2, available_at="2026-07-17T00:00:00Z"))

            leased = queue.lease_next(now="2026-07-17T00:00:01Z", leased_until="2026-07-17T00:05:00Z")
            self.assertIsNotNone(leased)
            self.assertEqual(leased.status, QueueItemStatus.LEASED)  # type: ignore[union-attr]
            running = queue.mark_running("item-1", now="2026-07-17T00:00:02Z")
            self.assertEqual(running.status, QueueItemStatus.RUNNING)
            self.assertEqual(queue.recover_stale(now="2026-07-17T00:10:00Z"), 1)
            retry = queue.lease_next(now="2026-07-17T00:10:01Z", leased_until="2026-07-17T00:15:00Z")
            self.assertEqual(retry.item_id, "item-1")  # type: ignore[union-attr]
            queue.mark_running("item-1", now="2026-07-17T00:10:02Z")
            succeeded = queue.mark_succeeded("item-1", now="2026-07-17T00:10:03Z")
            self.assertEqual(succeeded.status, QueueItemStatus.SUCCEEDED)
            store.close()

    def test_queue_failed_retry_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStateStore(os.path.join(tmp, "runtime.sqlite"))
            queue = DurableTaskQueue(store._connection)
            queue.enqueue("item-1", "dedupe-1", {"x": "y"}, priority=1, available_at="2026-07-17T00:00:00Z", max_attempts=1)
            queue.lease_next(now="2026-07-17T00:00:01Z", leased_until="2026-07-17T00:05:00Z")
            queue.mark_running("item-1", now="2026-07-17T00:00:02Z")

            failed = queue.mark_failed("item-1", now="2026-07-17T00:00:03Z", retry_at="2026-07-17T00:01:00Z", error="synthetic")

            self.assertEqual(failed.status, QueueItemStatus.FAILED)
            store.close()

    def test_durable_scheduler_and_db_duplicate_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStateStore(os.path.join(tmp, "runtime.sqlite"))
            scheduler = DurableScheduler(
                store._connection,
                (ScheduledJob("daily", ScheduleSpec("daily_report", "UTC", "09:00"), "daily:2026-07-17"),),
            )

            first = scheduler.run_due("2026-07-17T09:00:00Z")
            second = scheduler.run_due("2026-07-17T09:00:00Z")
            guard = DuplicateMessageGuard(store, processed_at="2026-07-17T09:00:00Z")

            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 0)
            self.assertTrue(guard.mark("telegram:100:1"))
            self.assertFalse(guard.mark("telegram:100:1"))
            store.close()


if __name__ == "__main__":
    unittest.main()
