"""Qwen Audio ASR duplex WebSocket; each PCM byte is uploaded exactly once."""

import asyncio
import json
import uuid

from websockets.exceptions import InvalidStatusCode

from ..domain.asr_protocol import ProviderError, text_event
from .transport import connect


class BailianProvider:
    label = "百炼"
    text_processing = "native"
    finish_timeout = 30
    token_metered = True

    def __init__(self, config):
        self.config = config
        self.socket = None
        self.task_id = str(uuid.uuid4())
        self.finalized = -1
        self.pending = None
        self.ending = False
        self.usage_callback = None

    def command(self, action, payload):
        return json.dumps({"header": {"action": action, "task_id": self.task_id,
                                      "streaming": "duplex"}, "payload": payload})

    def parse(self, raw):
        try:
            message = json.loads(raw)
            header, payload = message["header"], message.get("payload", {})
            if header.get("task_id") != self.task_id or not isinstance(payload, dict):
                raise ValueError()
            if header.get("event") == "task-failed":
                raise ProviderError("百炼流式任务失败，请检查模型权限、额度与音频参数")
            return header.get("event"), payload
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ProviderError("百炼返回了无效的流式任务事件") from None

    def parameters(self):
        result = {"format": "pcm", "sample_rate": 16000,
                  "keep_dialect": self.config["keepDialect"],
                  "max_sentence_silence": self.config["silenceMs"], "heartbeat": True}
        if self.config["language"] != "auto":
            result["language_hints"] = [self.config["language"]]
        if self.config.get("hotwords"):
            result["vocabulary"] = {term["text"]: term["weight"] for term in self.config["hotwords"]}
        return result

    async def open(self):
        try:
            self.socket = await connect(
                self.config["endpoint"],
                use_proxy=self.config.get("useProxy", False), proxy=self.config.get("_proxy"),
                extra_headers={"Authorization": "Bearer " + self.config["apiKey"]},
                open_timeout=6, close_timeout=1, max_size=4 * 1024 * 1024, max_queue=16,
            )
        except InvalidStatusCode as error:
            raise ProviderError("百炼连接失败（HTTP %d），请检查地址和 API Key" % error.status_code) from None
        await self.socket.send(self.command("run-task", {
            "task_group": "audio", "task": "asr", "function": "recognition",
            "model": self.config["model"], "parameters": self.parameters(), "input": {},
        }))
        kind, _ = self.parse(await asyncio.wait_for(self.socket.recv(), 8))
        if kind != "task-started":
            raise ProviderError("百炼未确认流式任务启动")

    async def send_audio(self, pcm, last=False):
        if self.ending:
            raise ProviderError("百炼音频已经结束")
        if pcm:
            await self.socket.send(pcm)
        if last:
            self.ending = True
            await self.socket.send(self.command("finish-task", {"input": {}}))

    async def receive(self):
        kind, payload = self.parse(await self.socket.recv())
        if self.usage_callback:
            self.usage_callback(payload, final=kind == "task-finished")
        if kind == "task-finished":
            if not self.ending or self.pending is not None:
                raise ProviderError("百炼未完成最终分句")
            return [], True
        if kind != "result-generated":
            return [], False
        try:
            sentence = payload["output"]["sentence"]
            if sentence.get("heartbeat"):
                return [], False
            identity, text = sentence["sentence_id"], sentence["text"]
            if type(identity) is not int or identity < 0 or not isinstance(text, str):
                raise ValueError()
            if identity <= self.finalized:
                return [], False
            if self.pending is not None and self.pending != identity:
                raise ValueError()
            final = sentence.get("sentence_end") is True
            start, end = sentence.get("begin_time", 0), sentence.get("end_time")
            if type(start) is not int or start < 0 or (end is not None and (type(end) is not int or end < start)):
                raise ValueError()
            if final:
                self.finalized = identity
                self.pending = None
            else:
                self.pending = identity if text else None
            return [text_event("final_result" if final else "partial_result", text,
                               start, end or start, "bailian")], False
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ProviderError("百炼返回了无效的流式识别结果") from None

    async def close(self):
        if self.socket:
            await self.socket.close()
