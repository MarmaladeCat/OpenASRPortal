"""公共 DashScope WebSocket 客户端，用于远程访问独立 OpenLocalASR 服务。"""

import asyncio
import json
import uuid

from websockets.exceptions import InvalidStatusCode

from ..domain.asr_protocol import ProviderError
from ..domain.transcript import ResultEmitter, protocol_error
from .base import StreamingProvider
from .transport import connect


class DashScopeProvider(StreamingProvider):
    label = "OpenLocalASR"
    text_processing = "native"
    finish_timeout = 60

    def __init__(self, config):
        self.config = config
        self.socket = None
        self.task_id = str(uuid.uuid4())
        self.results = ResultEmitter()
        self.ending = False

    def command(self, action, payload):
        return json.dumps(
            {
                "header": {"action": action, "task_id": self.task_id, "streaming": "duplex"},
                "payload": payload,
            }
        )

    def parse(self, raw):
        try:
            message = json.loads(raw)
            header = message["header"]
            if header.get("task_id") != self.task_id:
                raise ValueError("task mismatch")
            if header.get("event") == "task-failed":
                # 不回显任意上游正文（可能含输入数据），明确提示服务与模型检查方向。
                raise ProviderError(
                    "OpenLocalASR 任务失败，请检查服务模型是否就绪、模型名和音频参数"
                )
            return header.get("event"), message.get("payload", {})
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ProviderError("OpenLocalASR 返回了无效的 DashScope 任务事件") from None

    async def open(self):
        try:
            self.socket = await connect(
                self.config["endpoint"],
                use_proxy=self.config.get("useProxy", False), proxy=self.config.get("_proxy"),
                extra_headers={
                    "Authorization": "Bearer " + self.config["apiKey"],
                },
                open_timeout=6,
                close_timeout=1,
                max_size=4 * 1024 * 1024,
            )
        except InvalidStatusCode as error:
            raise ProviderError.upstream("OpenLocalASR", error.status_code) from None
        await self.socket.send(
            self.command(
                "run-task",
                {
                    "task_group": "audio",
                    "task": "asr",
                    "function": "recognition",
                    "model": self.config["model"],
                    "parameters": {"format": "pcm", "sample_rate": 16000},
                    "input": {},
                },
            )
        )
        kind, _ = self.parse(await asyncio.wait_for(self.socket.recv(), 8))
        if kind != "task-started":
            raise ProviderError("OpenLocalASR 未确认任务启动")

    async def send_audio(self, pcm, last=False):
        if self.ending:
            raise ProviderError("OpenLocalASR 音频已经结束")
        if pcm:
            await self.socket.send(pcm)
        if last:
            self.ending = True
            await self.socket.send(self.command("finish-task", {"input": {}}))

    async def receive(self):
        kind, payload = self.parse(await self.socket.recv())
        if kind == "task-finished":
            if not self.ending:
                raise ProviderError("OpenLocalASR 未返回最终分句，文字已保留供核对")
            self.results.finish()
            return [], True
        if kind != "result-generated":
            return [], False
        try:
            sentence = payload["output"]["sentence"]
            if sentence.get("heartbeat"):
                return [], False
            identity, final = sentence["sentence_id"], sentence["sentence_end"]
            # The public OpenLocalASR protocol numbers sentences from one.
            if type(identity) is not int or identity < 1 or type(final) is not bool:
                raise ValueError()
            return self.results.replace(
                f"{self.task_id}:{identity}", identity - 1, sentence["text"], stable=final,
                start=sentence.get("begin_time"), end=sentence.get("end_time"), source="dashscope",
            ), False
        except (ValueError, KeyError, TypeError, AttributeError):
            raise protocol_error() from None

    async def close(self):
        if self.socket:
            await self.socket.close()
