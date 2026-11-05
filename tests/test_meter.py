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
            async with meter.request(3200):
                pass
        self.assertTrue(locks)
        self.assertTrue(all(not lock.locked() for lock in locks.values()))
        usage.complete_call.side_effect = None

        async def retry():
            async with meter.request(3200):
                pass

        await asyncio.wait_for(retry(), 1)
