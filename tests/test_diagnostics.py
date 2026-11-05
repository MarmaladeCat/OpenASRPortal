import asyncio
import io
import json
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from openasrportal.diagnostics import (
    checkpoint,
    mark,
    session_tag,
    span,
    trace_request,
    websocket_options,
)


class TimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_timing_has_no_log_or_loop_instrumentation(self):
        @trace_request("test")
        async def operation():
            with span("work"):
                mark("ready")
            return 17

        output = io.StringIO()
        with patch.dict(os.environ, {"OPENASRPORTAL_TIMING": "0"}), redirect_stderr(output):
            self.assertEqual(await operation(), 17)
        self.assertEqual(output.getvalue(), "")
        self.assertFalse(getattr(asyncio.get_running_loop(), "_openasr_timing", False))

    async def test_concurrent_requests_and_child_tasks_keep_separate_content_free_timings(self):
        @trace_request("test")
        async def operation(identity, stage):
            session_tag(identity)

            async def child():
                with span(stage):
                    await asyncio.sleep(0)
                mark("ready")

            await asyncio.create_task(child())
            checkpoint("ready")

        output = io.StringIO()
        with patch.dict(os.environ, {"OPENASRPORTAL_TIMING": "1"}), redirect_stderr(output):
            await asyncio.gather(
                operation("private-one", "first"), operation("private-two", "second")
            )
        text = output.getvalue()
        self.assertNotIn("private-one", text)
        self.assertNotIn("private-two", text)
        records = [json.loads(line.split(" ", 1)[1]) for line in text.splitlines()]
        self.assertEqual(len(records), 4)
        groups = {}
        for record in records:
            groups.setdefault(record["session"], []).append(record)
            self.assertEqual(len(record["spansMs"]), 1)
            self.assertIn("ready", record["marksMs"])
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(len(records) == 2 for records in groups.values()))

    async def test_real_local_websocket_records_dns_tcp_and_upgrade_without_payload(self):
        from websockets.legacy.client import connect
        from websockets.legacy.server import serve

        async def echo(socket):
            await socket.send(await socket.recv())

        output = io.StringIO()
        with patch.dict(os.environ, {"OPENASRPORTAL_TIMING": "1"}), redirect_stderr(output):
            async with serve(echo, "127.0.0.1", 0) as server:
                port = server.sockets[0].getsockname()[1]

                @trace_request("upstream-test")
                async def operation():
                    mark("upstreamConnectStart")
                    async with connect(f"ws://localhost:{port}", **websocket_options()) as socket:
                        await socket.send("do-not-log-payload")
                        self.assertEqual(await socket.recv(), "do-not-log-payload")

                await operation()
        self.assertNotIn("do-not-log-payload", output.getvalue())
        record = json.loads(output.getvalue().split(" ", 1)[1])
        for name in ("dns", "tcpConnect", "upstreamWebsocketHandshake"):
            self.assertGreaterEqual(record["spansMs"][name], 0)
            self.assertGreaterEqual(record["counts"][name], 1)
        self.assertIn("upstreamTransportReady", record["marksMs"])
