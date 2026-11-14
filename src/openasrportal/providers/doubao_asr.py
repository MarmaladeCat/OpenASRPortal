"""远程豆包二进制协议适配：PCM16 -> 项目统一的分句消息。"""

import asyncio
import gzip
import json
import struct
import uuid

from websockets.exceptions import InvalidStatusCode

from ..diagnostics import mark, span, websocket_options
from ..domain.asr_protocol import ProviderError
from ..domain.transcript import MAX_UNITS, ResultEmitter, protocol_error
from .base import StreamingProvider
from .transport import connect


def encode_packet(kind, sequence, data, last=False):
    compressed = gzip.compress(data)
    return (
        bytes([0x11, kind << 4 | (3 if last else 1), 0x11, 0])
        + struct.pack(">iI", -sequence if last else sequence, len(compressed))
        + compressed
    )


def decode_packet(data):
    if not isinstance(data, bytes) or len(data) < 8:
        raise ProviderError("豆包返回了无效的数据帧")
    kind, flags = data[1] >> 4, data[1] & 15
    offset = (data[0] & 15) * 4
    if data[0] >> 4 != 1 or offset < 4 or kind not in (9, 15):
        raise ProviderError("豆包返回了不支持的协议帧")
    if flags & 1:
        offset += 4
    if flags & 4:
        offset += 4
    try:
        code = 0
        if kind == 15:
            code = struct.unpack_from(">I", data, offset)[0]
            offset += 4
        size = struct.unpack_from(">I", data, offset)[0]
        body = data[offset + 4 :]
        if size != len(body):
            raise ValueError("invalid size")
        if data[2] & 15 == 1:
            body = gzip.decompress(body)
        payload = json.loads(body) if data[2] >> 4 == 1 else body.decode("utf-8")
    except (ValueError, OSError, EOFError, struct.error):
        raise ProviderError("豆包响应数据解析失败") from None
    if kind == 15:
        # 服务端错误可能包含请求数据；只显示代码和排查方向，不返回原始载荷。
        raise ProviderError(
            "豆包识别失败（代码 %s），请检查 Key、服务开通状态、额度和音频格式" % code
        )
    return payload, bool(flags & 2)


class ResultNormalizer:
    """Full snapshots prove order; mutable splits/merges share one tail identity."""

    def __init__(self):
        self.committed = []
        self.results = ResultEmitter()
        self.order = 0

    def replace(self, items, stable=False):
        return self.results.replace(
            f"window:{self.order}", self.order, "".join(item["text"] for item in items),
            stable=stable, start=items[0].get("start_time") if items else None,
            end=items[-1].get("end_time") if items else None,
            source=items[-1].get("additions", {}).get("source", "") if items else "",
        )

    def accept(self, payload, last=False):
        try:
            result = payload.get("result", {})
            if not isinstance(result, dict):
                raise ValueError()
            if "utterances" not in result:
                if result.get("text"):
                    raise ValueError()  # Requested show_utterances/full; no order evidence.
                if last:
                    self.results.finish()
                return []
            items = result["utterances"]
            if not isinstance(items, list) or len(items) > MAX_UNITS:
                raise ValueError()
            for item in items:
                if not isinstance(item["text"], str) or type(item["definite"]) is not bool:
                    raise ValueError()
            if len(items) < len(self.committed) or any(
                    not item["definite"] or item["text"] != text
                    for item, text in zip(items, self.committed)):
                raise ValueError()
            tail = items[len(self.committed):]
            count = 0
            while count < len(tail) and tail[count]["definite"]:
                count += 1
            # An empty/terminal snapshot is not proof of stability or withdrawal.
            if last and (count < len(tail) or (not count and any(
                    not item.stable for item in self.results.results.values()))):
                raise ValueError()
            events = []
            if count:
                events.extend(self.replace(tail[:count], stable=True))
                self.committed.extend(item["text"] for item in tail[:count])
                self.order += 1
            if tail[count:] or (not last and f"window:{self.order}" in self.results.results):
                events.extend(self.replace(tail[count:]))
            if last:
                self.results.finish()
            return events
        except (ValueError, KeyError, TypeError, AttributeError):
            raise protocol_error() from None


class DoubaoProvider(StreamingProvider):
    text_processing = "native"
    label = "豆包"
    finish_timeout = 5
    realtime_upload = True

    def __init__(self, config):
        self.config = config
        self.socket = None
        self.sequence = 1
        self.results = ResultNormalizer()
        self.next_audio_at = 0

    async def open(self):
        mark("upstreamConnectStart")
        try:
            with span("upstreamConnect"):
                self.socket = await connect(
                    self.config["endpoint"],
                    use_proxy=self.config.get("useProxy", False), proxy=self.config.get("_proxy"),
                    extra_headers={
                        "X-Api-Key": self.config["apiKey"],
                        "X-Api-Resource-Id": self.config["resourceId"],
                        "X-Api-Request-Id": str(uuid.uuid4()),
                    },
                    open_timeout=6,
                    close_timeout=1,
                    max_size=4 * 1024 * 1024,
                    **websocket_options(),
                )
        except InvalidStatusCode as error:
            raise ProviderError.upstream("豆包", error.status_code) from None
        payload = {
            "user": {"uid": "opennotes"},
            "audio": {"format": "pcm", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "show_utterances": True,
                "result_type": "full",
                "enable_nonstream": self.config["enableNonstream"],
            },
        }
        if self.config["enableNonstream"]:
            # Two-pass recognition enables upstream VAD. Allow thinking pauses;
            # otherwise omit the forced endpoint and use upstream semantic logic.
            payload["request"]["end_window_size"] = self.config.get("silenceMs", 5000)
        if self.config.get("hotwords"):
            payload["request"]["corpus"] = {
                "context": json.dumps(
                    {"hotwords": [{"word": term["text"]} for term in self.config["hotwords"]]},
                    ensure_ascii=False,
                )
            }
        with span("upstreamInitSend"):
            await self.socket.send(
                encode_packet(1, self.sequence, json.dumps(payload).encode("utf-8"))
            )
        self.sequence += 1
        with span("upstreamInitAck"):
            decode_packet(await asyncio.wait_for(self.socket.recv(), 6))

    async def send_audio(self, pcm, last=False):
        loop = asyncio.get_running_loop()
        await asyncio.sleep(max(0, self.next_audio_at - loop.time()))
        await self.socket.send(encode_packet(2, self.sequence, pcm, last))
        # Do not accumulate idle-time credit: buffered audio remains real-time.
        self.next_audio_at = loop.time() + len(pcm) / 32000
        self.sequence += 1

    async def receive(self):
        payload, last = decode_packet(await self.socket.recv())
        return self.results.accept(payload, last), last

    async def close(self):
        if self.socket:
            await self.socket.close()
