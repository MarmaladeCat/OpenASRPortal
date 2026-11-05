"""远程 Qwen Audio 3.1 ASR Flash：HTTP 转写 + 分段/快照适配统一录音协议。

上游接收完整音频。阶段性快照仅是预览，VAD/最长时长/停止录音触发完整片段定稿。
串行请求、合并待处理预览、优先处理定稿，避免旧快照覆盖新分句及无限积压。
"""

import array
import asyncio
import base64
import io
import json
import re
import sys
import wave
from collections import deque

import httpx

from ..domain.asr_protocol import ProviderError, text_event

BYTES_PER_SECOND = 32000
FRAME_BYTES = 640  # 20 ms PCM16 / mono / 16 kHz
MAX_SEGMENT_BYTES = 15 * BYTES_PER_SECOND


def wav_data_uri(pcm):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm)
    return "data:audio/wav;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def parse_result(payload):
    """兼容官方文档及实测的 output.output 嵌套；短音频 HTTP 返回整段累积文本。"""
    if not isinstance(payload, dict):
        raise ProviderError("百炼返回了无效的识别结果")
    if payload.get("code"):
        raise ProviderError("百炼识别请求失败，请检查模型权限、账户额度与音频格式")
    output = payload.get("output", {})
    for _ in range(3):
        if not isinstance(output, dict):
            break
        if isinstance(output.get("text"), str):
            return output["text"]
        # 没有累积 text 时，优先取全部 sentences；不能只取长音频最后一个 sentence。
        sentences = output.get("sentences")
        if isinstance(sentences, list) and all(
            isinstance(item, dict) and isinstance(item.get("text"), str) for item in sentences
        ):
            return "".join(item["text"] for item in sentences)
        if isinstance(output.get("output"), dict):
            output = output["output"]
            continue
        sentence = output.get("sentence", {})
        if isinstance(sentence, dict) and isinstance(sentence.get("text"), str):
            return sentence["text"]
        break
    raise ProviderError("百炼响应缺少识别文本，不能作为正常定稿")


class BailianProvider:
    label = "阿里云百炼"
    text_processing = "native"
    finish_timeout = 65  # 最多一个执行中请求 + 两个排队定稿，每个请求上限 20 秒。
    request_metered = True

    def __init__(self, config):
        self.config = config
        self.client = None
        self.worker = None
        self.events = asyncio.Queue(maxsize=32)
        self.wake = asyncio.Event()
        self.finals = deque()
        self.preview = None
        self.ending = False
        self.closed = False
        self.segment_id = 0
        self.total = 0
        self.start = 0
        self.voice_end = 0
        self.voiced = 0
        self.last_preview = 0
        self.buffer = bytearray()
        self.preroll = bytearray()
        self.usage_meter = None
        self.pending_final_audio_bytes = 0

    @property
    def required_final_audio_bytes(self):
        return (
            len(self.buffer)
            + len(self.preroll)
            + sum(len(job[1]) for job in self.finals)
            + self.pending_final_audio_bytes
        )

    async def open(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(20, connect=6), follow_redirects=False
        )
        self.worker = asyncio.create_task(self._work())

    async def probe(self):
        # 静音也实际调用指定模型，从而验证鉴权、模型权限及响应解析。
        await self._transcribe(bytes(BYTES_PER_SECOND))

    async def _transcribe(self, pcm, *, final=True):
        parameters = {
            "format": "wav",
            "sample_rate": "16000",
            "keep_dialect": self.config["keepDialect"],
        }
        if self.config["language"] != "auto":
            parameters["language_hints"] = [self.config["language"]]
        if self.config.get("hotwords"):
            parameters["vocabulary"] = {
                term["text"]: term["weight"] for term in self.config["hotwords"]
            }
        body = {
            "model": self.config["model"],
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_audio", "input_audio": {"data": wav_data_uri(pcm)}}
                        ],
                    }
                ]
            },
            "parameters": parameters,
        }
        if self.usage_meter is not None:
            async with self.usage_meter.request(len(pcm), final) as (identity, report):
                if identity is None:
                    return None
                if final:
                    self.pending_final_audio_bytes = 0
                    self.usage_meter.reserve_final(self.required_final_audio_bytes)
                return await self._request(body, report)
        return await self._request(body)

    async def _request(self, body, report=None):
        try:
            response = await asyncio.wait_for(
                self.client.post(
                    self.config["endpoint"],
                    headers={
                        "Authorization": "Bearer " + self.config["apiKey"],
                        "X-DashScope-SSE": "disable",
                    },
                    json=body,
                ),
                20,
            )
        except (httpx.TimeoutException, asyncio.TimeoutError):
            raise ProviderError("百炼识别请求超时，请检查网络后重试") from None
        except httpx.HTTPError:
            raise ProviderError("无法连接百炼，请检查后端网络及端点地址") from None
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            raise ProviderError("百炼返回了无效 JSON 响应") from None
        if report is not None:
            report(payload)
        if response.status_code != 200:
            code = ""
            try:
                failure = payload
                # 百炼用特定 400 表达“音频中无可识别文字”；静音探测/噪声片段视为空文本。
                if (
                    response.status_code == 400
                    and failure.get("code") == "CLIENT_ERROR"
                    and failure.get("message") == "ASR_RESPONSE_HAVE_NO_WORDS"
                ):
                    return ""
                raw = failure.get("code", "")
                if isinstance(raw, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", raw):
                    code = "，" + raw
            except (ValueError, AttributeError):
                pass
            raise ProviderError(
                "百炼调用失败（HTTP %s%s），请检查 API Key、地域、模型权限和额度"
                % (response.status_code, code)
            )
        return parse_result(payload)

    def _job(self, final):
        return (self.segment_id, bytes(self.buffer), self.start // 32, self.voice_end // 32, final)

    def _finalize(self):
        self.preview = None
        if self.buffer and self.voiced >= 3200:
            if len(self.finals) >= 2:
                raise ProviderError("百炼识别请求积压，请停止录音并检查网络后重试")
            self.finals.append(self._job(True))
            self.wake.set()
        self.segment_id += 1
        self.buffer.clear()
        self.voiced = 0
        self.last_preview = 0

    async def send_audio(self, pcm, last=False):
        if self.ending or self.closed:
            raise ProviderError("百炼录音会话已经结束")
        for offset in range(0, len(pcm), FRAME_BYTES):
            frame = pcm[offset : offset + FRAME_BYTES]
            self.total += len(frame)
            samples = array.array("h", frame)
            if sys.byteorder != "little":
                samples.byteswap()
            speaking = (
                bool(samples) and sum(sample * sample for sample in samples) / len(samples) >= 10737
            )  # -50 dBFS
            if not self.buffer:
                self.preroll.extend(frame)
                if not speaking:
                    del self.preroll[:-6400]
                    continue
                self.buffer.extend(self.preroll)
                self.start = self.total - len(self.buffer)
                self.preroll.clear()
            else:
                self.buffer.extend(frame)
            if speaking:
                self.voiced += len(frame)
                self.voice_end = self.total
            if (
                self.total - self.voice_end >= self.config["silenceMs"] * 32
                or len(self.buffer) >= MAX_SEGMENT_BYTES
            ):
                self._finalize()
                continue
            interval = self.config["previewIntervalMs"] * 32
            if (
                interval
                and self.voiced >= 3200
                and len(self.buffer) - self.last_preview >= interval
            ):
                self.last_preview = len(self.buffer)
                self.preview = self._job(False)
                self.wake.set()
        if last:
            self._finalize()
            self.ending = True
            self.wake.set()

    async def _work(self):
        try:
            while True:
                await self.wake.wait()
                self.wake.clear()
                while self.finals or self.preview:
                    job = self.finals.popleft() if self.finals else self.preview
                    if job is self.preview:
                        self.preview = None
                    segment, pcm, start, end, final = job
                    self.pending_final_audio_bytes = len(pcm) if final else 0
                    try:
                        text = await self._transcribe(pcm, final=final)
                    finally:
                        self.pending_final_audio_bytes = 0
                        if self.usage_meter is not None:
                            self.usage_meter.reserve_final(self.required_final_audio_bytes)
                    if text is None:
                        continue
                    if final or (segment == self.segment_id and not self.ending):
                        kind = "final_result" if final else "partial_result"
                        await self.events.put(
                            ([text_event(kind, text, start, end, "bailian_http")], False)
                        )
                if self.ending:
                    await self.events.put(([], True))
                    return
        except Exception as error:
            await self.events.put(error)

    async def receive(self):
        result = await self.events.get()
        if isinstance(result, Exception):
            raise result
        return result

    async def close(self):
        self.closed = True
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        if self.client:
            await self.client.aclose()
