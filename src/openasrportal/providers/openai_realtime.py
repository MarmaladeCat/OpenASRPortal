"""Dedicated OpenAI transcription sessions; PCM24k, explicit commit, no VAD."""

import base64
import hashlib
import json

from websockets.exceptions import InvalidStatusCode

from ..domain.asr_protocol import ProviderError
from ..domain.transcript import MAX_TEXT, ResultEmitter, protocol_error
from .base import StreamingProvider
from .openai_common import context, parse, usage
from .resample import PCM24k
from .transport import connect


class RealtimeResults:
    """Order comes from committed predecessors, including completions arriving first.

    A single local turn can bind its pre-commit preview unambiguously. Multi-turn
    consumers wait for predecessor evidence; the production profile commits once.
    """

    def __init__(self, turns=1):
        self.turns = turns
        self.items, self.seen = {}, {}
        self.results = ResultEmitter()
        self.reported = set()

    def accept(self, event):
        event_id = event.get("event_id")
        if event_id is not None:
            if not isinstance(event_id, str) or not 0 < len(event_id) <= 512:
                raise protocol_error()
            digest = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).digest()
            if event_id in self.seen:
                if self.seen[event_id] != digest:
                    raise protocol_error()
                return [], []
            if len(self.seen) >= 16384:
                raise protocol_error()
            self.seen[event_id] = digest
        kind = event.get("type")
        identity = event.get("item_id")
        if not isinstance(identity, str) or not 0 < len(identity) <= 500:
            raise protocol_error()
        if identity not in self.items:
            if len(self.items) >= self.turns:
                raise protocol_error()
            self.items[identity] = {"text": "", "committed": False, "completed": None,
                                    "order": 0 if self.turns == 1 else None}
        item = self.items[identity]
        if kind == "input_audio_buffer.committed":
            previous = event.get("previous_item_id")
            if previous is not None and (not isinstance(previous, str) or not previous or previous == identity):
                raise protocol_error()
            if item["committed"] and item["previous"] != previous:
                raise protocol_error()
            if self.turns == 1 and previous is not None:
                raise protocol_error()
            item.update(committed=True, previous=previous)
        else:
            if type(event.get("content_index")) is not int or event["content_index"] != 0:
                raise protocol_error()
            if kind == "conversation.item.input_audio_transcription.delta":
                if item["completed"] is not None or not isinstance(event.get("delta"), str):
                    raise protocol_error()
                item["text"] += event["delta"]
            elif kind == "conversation.item.input_audio_transcription.completed":
                if not isinstance(event.get("transcript"), str):
                    raise protocol_error()
                if item["completed"] is not None and item["text"] != event["transcript"]:
                    raise protocol_error()
                item["text"], item["completed"] = event["transcript"], event
            else:
                raise protocol_error()
        if sum(len(value["text"]) for value in self.items.values()) > MAX_TEXT:
            raise protocol_error()
        for key in self.items:
            chain = set()
            while key in self.items and self.items[key]["committed"]:
                if key in chain:
                    raise protocol_error()
                chain.add(key)
                key = self.items[key]["previous"]
        # Resolve links from the root, never from lexical IDs or completion order.
        for _ in range(len(self.items)):
            changed = False
            for value in self.items.values():
                if not value["committed"]:
                    continue
                previous = self.items.get(value["previous"])
                order = 0 if value["previous"] is None else (
                    previous["order"] + 1 if previous and previous["committed"] and previous["order"] is not None else None)
                if order is not None:
                    if order >= self.turns or (value["order"] is not None and value["order"] != order):
                        raise protocol_error()
                    changed |= value["order"] != order
                    value["order"] = order
            if not changed:
                break
        orders = [v["order"] for v in self.items.values() if v["order"] is not None]
        if len(set(orders)) != len(orders):
            raise protocol_error()
        events, reports = [], []
        for key, value in self.items.items():
            if value["order"] is None:
                continue
            stable = value["committed"] and value["completed"] is not None
            events.extend(self.results.replace(key + ":0", value["order"], value["text"],
                                               stable=stable, source="openai_realtime"))
            if stable and key not in self.reported:
                reports.append(usage(value["completed"], key + ":0"))
                self.reported.add(key)
        return events, reports

    @property
    def done(self):
        return len(self.reported) == self.turns


class OpenAIRealtimeProvider(StreamingProvider):
    label = "OpenAI"
    text_processing = "native"
    finish_timeout = 60
    token_metered = True
    scoped_usage = True

    def __init__(self, config):
        self.config, self.socket = config, None
        self.results = RealtimeResults()
        self.converter = None
        self.ending = False
        self.usage_callback = None

    async def send(self, kind, **fields):
        await self.socket.send(json.dumps({"type": kind, **fields}))

    async def open(self):
        self.converter = PCM24k()
        try:
            self.socket = await connect(
                self.config["endpoint"], use_proxy=self.config.get("useProxy", False), proxy=self.config.get("_proxy"),
                extra_headers={"Authorization": "Bearer " + self.config["apiKey"]},
                open_timeout=6, close_timeout=1, max_size=4 * 1024 * 1024, max_queue=16,
            )
        except InvalidStatusCode as error:
            raise ProviderError.upstream("OpenAI", error.status_code) from None
        await self.send("session.update", session={"type": "transcription", "audio": {"input": {
            "format": {"type": "audio/pcm", "rate": 24000}, "transcription": context(self.config),
            "turn_detection": None,
        }}})
        while True:
            event = parse(await self.socket.recv())
            if event.get("type") == "session.created":
                continue
            if event.get("type") != "session.updated":
                raise protocol_error()
            try:
                session = event["session"]
                audio = session["audio"]["input"]
                if (session["type"] != "transcription" or audio["format"] != {"type": "audio/pcm", "rate": 24000}
                        or audio["transcription"]["model"] != self.config["model"]
                        or audio["turn_detection"] is not None):
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise protocol_error() from None
            return

    async def send_audio(self, pcm, last=False):
        if self.ending:
            raise protocol_error()
        converted = self.converter.convert(pcm, last=last)
        for offset in range(0, len(converted), 1920):  # 40 ms transport frames, never semantic turns.
            await self.send("input_audio_buffer.append", audio=base64.b64encode(converted[offset:offset + 1920]).decode("ascii"))
        if last:
            self.ending = True
            await self.send("input_audio_buffer.commit")

    async def receive(self):
        event = parse(await self.socket.recv())
        kind = event.get("type", "")
        if kind in {"input_audio_buffer.committed", "conversation.item.input_audio_transcription.delta",
                    "conversation.item.input_audio_transcription.completed"}:
            if kind != "conversation.item.input_audio_transcription.delta" and not self.ending:
                raise protocol_error()
            events, reports = self.results.accept(event)
            for report in reports:
                if self.usage_callback:
                    self.usage_callback(report, final=self.results.done)
            return events, self.results.done
        if kind in {"rate_limits.updated", "conversation.item.created", "conversation.item.added",
                    "conversation.item.done"}:
            return [], False
        raise protocol_error()

    async def close(self):
        if self.socket:
            await self.socket.close()
