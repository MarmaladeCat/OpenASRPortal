"""远程豆包二进制协议适配：PCM16 -> 项目统一的分句消息。"""

import asyncio
import gzip
import json
import struct
import uuid

from websockets.exceptions import InvalidStatusCode
from websockets.legacy.client import connect

from ..diagnostics import mark, span, websocket_options
from ..domain.asr_protocol import ProviderError, text_event


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


def result_message(kind, utterance):
    text = utterance.get("text", "")
    return text_event(
        kind,
        text,
        utterance.get("start_time", 0),
        utterance.get("end_time", 0),
        utterance.get("additions", {}).get("source", ""),
    )


class ResultNormalizer:
    """full 模式会重发历史分句；只提交新定稿，预览只包含尚未定稿的尾部。"""

    def __init__(self):
        self.committed_end = -1
        self.partial = ""

    def accept(self, payload, last=False):
        result = payload.get("result", {})
        if not isinstance(result, dict):
            return []
        events, pending = [], []
        for utterance in result.get("utterances", []):
            end = utterance.get("end_time", 0)
            if end <= self.committed_end:
                continue
            if utterance.get("definite") or last:
                if utterance.get("text", "").strip():
                    events.append(result_message("final_result", utterance))
                self.committed_end = end
            else:
                pending.append(utterance)
        partial = "".join(item.get("text", "") for item in pending)
        if partial != self.partial or events:
            events.append(
                result_message(
                    "partial_result",
                    {
                        "text": partial,
                        "start_time": pending[0].get("start_time", 0) if pending else 0,
                        "end_time": pending[-1].get("end_time", 0) if pending else 0,
                    },
                )
            )
            self.partial = partial
        return events


class DoubaoProvider:
    text_processing = "native"
    label = "豆包"
    finish_timeout = 5

    def __init__(self, config):
        self.config = config
        self.socket = None
        self.sequence = 1
        self.results = ResultNormalizer()

    async def open(self):
        mark("upstreamConnectStart")
        try:
            with span("upstreamConnect"):
                self.socket = await connect(
                    self.config["endpoint"],
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
            raise ProviderError(
                "豆包鉴权/连接失败（HTTP %d），请检查 API Key、模型资源及服务额度"
                % error.status_code
            ) from None
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
                "end_window_size": 800,
            },
        }
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
        await self.socket.send(encode_packet(2, self.sequence, pcm, last))
        self.sequence += 1

    async def receive(self):
        payload, last = decode_packet(await self.socket.recv())
        return self.results.accept(payload, last), last

    async def close(self):
        if self.socket:
            await self.socket.close()
