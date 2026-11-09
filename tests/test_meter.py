"""Settlement failures must not strand quota serialization locks."""

import asyncio
import unittest
from unittest.mock import MagicMock

from openasrportal.application.meter import SessionMeter


class MeterTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_settlement_releases_every_acquired_lock(self):
        usage = MagicMock()
        usage.session.return_value = {"key_id": "key", "profile_id": "profile"}
        usage.account.return_value = {"remaining_tokens": 10}
        usage.begin_call.return_value = "event"
        usage.complete_call.side_effect = RuntimeError("disk unavailable")
        locks = {}
        meter = SessionMeter(usage, "session", locks)
        with self.assertRaisesRegex(RuntimeError, "disk unavailable"):
            try:
                await meter.start()
                meter.response({}, final=True)
            finally:
                meter.close()
        self.assertTrue(locks)
        self.assertTrue(all(not lock.locked() for lock in locks.values()))
        usage.complete_call.side_effect = None

        async def retry():
            try:
                await meter.start()
            finally:
                meter.close()

        await asyncio.wait_for(retry(), 1)

    async def test_cancel_while_waiting_releases_the_already_acquired_key_lock(self):
        usage = MagicMock()
        usage.session.return_value = {"key_id": "key", "profile_id": "profile"}
        usage.account.return_value = {"remaining_tokens": 10}
        profile_lock = asyncio.Lock()
        await profile_lock.acquire()
        locks = {("profile", "profile"): profile_lock}
        meter = SessionMeter(usage, "session", locks)
        task = asyncio.create_task(meter.start())
        await asyncio.sleep(0)
        self.assertTrue(locks[("key", "key")].locked())
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        meter.close()
        self.assertFalse(locks[("key", "key")].locked())
        self.assertTrue(profile_lock.locked())
        profile_lock.release()
