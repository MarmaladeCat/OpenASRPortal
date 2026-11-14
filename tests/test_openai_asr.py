"""Official-wire contract fixtures; no claims about account/model availability."""

import asyncio
import base64
import json
import unittest

import numpy as np
from websockets.legacy.server import serve

from openasrportal.domain.asr_protocol import ProviderError
from openasrportal.domain.config import validate_config
from openasrportal.domain.events import EventStream
from openasrportal.providers.openai_realtime import OpenAIRealtimeProvider, RealtimeResults
from openasrportal.providers.registry import definition
from openasrportal.providers.resample import PCM24k
from openasrportal.providers.sse import events as sse_events


def transcript(kind, identity, **fields):
    return {"type": "conversation.item.input_audio_transcription." + kind,
            "item_id": identity, "content_index": 0, **fields}


def committed(identity, previous=None):
    return {"type": "input_audio_buffer.committed", "item_id": identity, "previous_item_id": previous}


class ResultTests(unittest.TestCase):
    def test_precommit_delta_full_replacement_and_duplicate_event(self):
        results, stream = RealtimeResults(), EventStream("s")
        delta = transcript("delta", "a", delta="预览", event_id="e1")
        self.assertEqual(stream.apply(results.accept(delta)[0])[0]["text"], "预览")
        self.assertEqual(results.accept(delta), ([], []))
        events, _ = results.accept(transcript("completed", "a", transcript="校正。"))
        self.assertFalse(results.done)
        self.assertEqual(stream.apply(events)[0]["type"], "transcript.partial")
        events, reports = results.accept(committed("a"))
        self.assertEqual(stream.apply(events)[0]["text"], "校正。")
        self.assertTrue(results.done)
        self.assertEqual(reports[0].kind, "unknown")
        stream.finish()
        with self.assertRaises(ProviderError):
            results.accept(transcript("completed", "a", transcript="冲突"))

    def test_reverse_completed_and_predecessor_arrivals_never_reverse_finals(self):
        results, stream = RealtimeResults(turns=2), EventStream("s")
        for event in (transcript("completed", "b", transcript="乙。"), committed("b", "a"),
                      transcript("completed", "a", transcript="甲。")):
            self.assertEqual(stream.apply(results.accept(event)[0]), [])
        self.assertFalse(results.done)
        events, _ = results.accept(committed("a"))
        self.assertEqual(stream.apply(events)[0]["text"], "甲。乙。")
        self.assertTrue(results.done)
        stream.finish()

    def test_conflicting_ids_cycles_and_malformed_results_fail(self):
        results = RealtimeResults(turns=2)
        results.accept(committed("a", "b"))
        with self.assertRaises(ProviderError):
            results.accept(committed("b", "a"))
        for event in (committed("a", "missing"), transcript("delta", "a", delta=4),
                      {**transcript("delta", "a", delta="a"), "content_index": True}):
            with self.assertRaises(ProviderError):
                RealtimeResults().accept(event)

    def test_four_capabilities_and_configuration_validation(self):
        for provider, patch, phase in (
            ("openai_file", {}, "none"), ("openai_file", {"responseMode": "sse"}, "after_audio_end"),
            ("openai_realtime", {}, "during_capture"),
            ("openai_realtime", {"model": "gpt-transcribe"}, "after_commit"),
        ):
            config = validate_config(provider, {"apiKey": "fictional", **patch})
            caps = definition(provider).capabilities(config)
            self.assertEqual(caps["recognition"]["preview"]["phase"], phase)
            self.assertEqual(caps["latencyClass"] == "streaming", phase == "during_capture")
        with self.assertRaises(ValueError):
            validate_config("openai_realtime", {"apiKey": "fictional", "model": "gpt-transcribe", "delay": "low"})


class AudioTests(unittest.TestCase):
    def test_continuous_resampling_is_chunk_independent_and_flushes_once(self):
        pcm = (np.sin(np.arange(16007) * .3) * 25000).astype("<i2").tobytes()
        reference = PCM24k().convert(pcm, last=True)
        for size in (2, 640, 1280, 6400):
            converter = PCM24k()
            converted = b"".join(converter.convert(pcm[i:i + size]) for i in range(0, len(pcm), size))
            converted += converter.convert(b"", last=True)
            self.assertEqual(converted, reference)
            self.assertLessEqual(abs(converter.output_samples - 16007 * 1.5), 1)
            self.assertEqual(converter.source_samples, 16007)
            self.assertEqual(converter.stream.delay(), 0)
            with self.assertRaises(ValueError):
                converter.convert(b"", last=True)
        self.assertEqual(set(PCM24k().convert(bytes(320), last=True)), {0})


class WireTests(unittest.IsolatedAsyncioTestCase):
    async def test_updated_confirmation_audio_conversion_precommit_delta_and_final(self):
        audio, controls = [], []

        async def handle(ws):
            update = json.loads(await ws.recv())
            config = update["session"]
            self.assertEqual(config["audio"]["input"]["format"]["rate"], 24000)
            self.assertIsNone(config["audio"]["input"]["turn_detection"])
            await ws.send(json.dumps({"type": "session.created"}))
            await ws.send(json.dumps({"type": "session.updated", "session": config}))
            async for raw in ws:
                event = json.loads(raw)
                controls.append(event["type"])
                if event["type"] == "input_audio_buffer.append":
                    audio.append(base64.b64decode(event["audio"]))
                    if len(audio) == 1:
                        await ws.send(json.dumps(transcript("delta", "item", delta="错字")))
                elif event["type"] == "input_audio_buffer.commit":
                    await ws.send(json.dumps(transcript("completed", "item", transcript="正确。",
                                                      usage={"type": "duration", "seconds": .2})))
                    await ws.send(json.dumps(committed("item")))

        async with serve(handle, "127.0.0.1", 0) as upstream:
            config = validate_config("openai_realtime", {"apiKey": "fictional"})
            config["endpoint"] = f"ws://127.0.0.1:{upstream.sockets[0].getsockname()[1]}"
            provider = OpenAIRealtimeProvider(config)
            try:
                await provider.open()
                await provider.write_audio(bytes(6400))
                preview, last = await asyncio.wait_for(provider.receive(), 1)
                self.assertFalse(last)
                self.assertEqual(preview[0].text, "错字")
                self.assertFalse(provider.ending)
                await provider.finish_input()
                _, last = await provider.receive()
                self.assertFalse(last)
                final, last = await provider.receive()
                self.assertTrue(last)
                self.assertEqual(final[0].text, "正确。")
                self.assertTrue(final[0].stable)
                self.assertEqual(len(b"".join(audio)), 9600)
                self.assertEqual(controls.count("input_audio_buffer.commit"), 1)
            finally:
                await provider.close()

    async def test_sse_multiline_utf8_and_truncated_frame(self):
        async def chunks(data):
            for value in data:
                yield bytes([value])

        framed = 'event: result\r\ndata: 中文\r\ndata: tail\r\n\r\n'.encode()
        self.assertEqual([value async for value in sse_events(chunks(framed))], [("result", "中文\ntail")])
        for data in (b"data: unfinished", b"data: \xff\n\n"):
            with self.assertRaises(ProviderError):
                [value async for value in sse_events(chunks(data))]
