"""公共 DashScope WebSocket 客户端，用于远程访问独立 OpenLocalASR 服务。"""

import asyncio
import json
import uuid

from websockets.exceptions import InvalidStatusCode
from websockets.legacy.client import connect

from ..domain.asr_protocol import ProviderError, text_event


class DashScopeProvider:
    label = "OpenLocalASR"
    text_processing = "native"
    finish_timeout = 60

    def __init__(self, config):
        self.config = config
        self.socket = None
        self.task_id = str(uuid.uuid4())
        self.finalized = set()
        self.pending = False

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
        except (ValueError, KeyError, TypeError):
            raise ProviderError("OpenLocalASR 返回了无效的 DashScope 任务事件") from None

    async def open(self):
        try:
            self.socket = await connect(
                self.config["endpoint"],
                extra_headers={
                    "Authorization": "Bearer " + self.config["apiKey"],
                },
                open_timeout=6,
                close_timeout=1,
                max_size=4 * 1024 * 1024,
            )
        except InvalidStatusCode as error:
            raise ProviderError(
                "OpenLocalASR 连接失败（HTTP %d），请检查地址和 API Key" % error.status_code
            ) from None
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
        if pcm:
            await self.socket.send(pcm)
        if last:
            await self.socket.send(self.command("finish-task", {"input": {}}))

    async def receive(self):
        kind, payload = self.parse(await self.socket.recv())
        if kind == "task-finished":
            if self.pending:
                raise ProviderError("OpenLocalASR 未返回最终分句，文字已保留供核对")
            return [], True
        if kind != "result-generated":
            return [], False
        sentence = payload.get("output", {}).get("sentence", {})
        if sentence.get("heartbeat"):
            return [], False
        text = sentence.get("text")
        if not isinstance(text, str):
            raise ProviderError("OpenLocalASR 结果缺少文本")
        identity = sentence.get("sentence_id", sentence.get("begin_time"))
        if identity in self.finalized:
            return [], False
        final = sentence.get("sentence_end") is True
        self.pending = bool(text) and not final
        if final:
            self.finalized.add(identity)
        return [
            text_event(
                "final_result" if final else "partial_result",
                text,
                sentence.get("begin_time") or 0,
                sentence.get("end_time") or 0,
                "dashscope",
            )
        ], False

    async def close(self):
        if self.socket:
            await self.socket.close()
