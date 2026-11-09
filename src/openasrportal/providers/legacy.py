#!/usr/bin/env python3
"""远程 ASR 中间层：提供与本地运行时相同的 start / PCM / end 协议。"""

import argparse
import asyncio
import json
import sys
import time

from websockets.exceptions import ConnectionClosed
from websockets.legacy.server import serve

from ..domain.asr_protocol import ProviderError, describe_error
from ..domain.config import (
    BAILIAN_MODEL,
    BOSON_MODEL,
    DOUBAO_MODEL,
    LOCAL_ASR_MODEL,
    SONIOX_MODEL,
    validate_config,
)
from .bailian_asr import BailianProvider
from .boson_asr import BosonProvider
from .dashscope_asr import DashScopeProvider
from .doubao_asr import DoubaoProvider
from .soniox_asr import SonioxProvider

PROVIDERS = {
    SONIOX_MODEL: SonioxProvider,
    BOSON_MODEL: BosonProvider,
    DOUBAO_MODEL: DoubaoProvider,
    BAILIAN_MODEL: BailianProvider,
    LOCAL_ASR_MODEL: DashScopeProvider,
}


async def bridge(client, provider):
    """每个录音会话独占远端连接；结束、失败或断连都会释放双向任务。"""
    tasks = []
    try:
        start = json.loads(await asyncio.wait_for(client.recv(), 10))
        if not isinstance(start, dict) or start.get("signal") != "start":
            raise ProviderError("请先发送语音开始信号")
        await provider.open()
        await client.send(
            json.dumps(
                {
                    "type": "server_ready",
                    "text_processing": provider.text_processing,
                    "finalize_timeout_ms": (provider.finish_timeout + 1) * 1000,
                }
            )
        )
        ended = asyncio.Event()

        async def upload():
            pending = bytearray()
            async for message in client:
                if isinstance(message, bytes):
                    if len(message) % 2:
                        raise ProviderError("音频必须为 16 kHz 单声道 PCM16")
                    pending.extend(message)
                    while len(pending) >= 6400:
                        await provider.send_audio(bytes(pending[:6400]))
                        del pending[:6400]
                elif json.loads(message).get("signal") == "end":
                    await provider.send_audio(bytes(pending), last=True)
                    ended.set()
                    return
            raise ConnectionError("client disconnected")

        async def download():
            while True:
                events, last = await provider.receive()
                for event in events:
                    await client.send(json.dumps(event, ensure_ascii=False))
                if last:
                    await client.send(json.dumps({"type": "speech_end"}))
                    return

        async def finish_deadline():
            await ended.wait()
            await asyncio.sleep(provider.finish_timeout)
            raise ProviderError("%s 未及时返回最终结果，请重新开始录音" % provider.label)

        sender = asyncio.create_task(upload())
        receiver = asyncio.create_task(download())
        deadline = asyncio.create_task(finish_deadline())
        tasks = [sender, receiver, deadline]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        if receiver not in done:
            done, _ = await asyncio.wait([receiver, deadline], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
    except Exception as error:
        try:
            await client.send(
                json.dumps(
                    {
                        "status": "failed",
                        "message": describe_error(error, getattr(provider, "label", "远程 ASR")),
                    },
                    ensure_ascii=False,
                )
            )
        except ConnectionClosed:
            pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await provider.close()


async def test_connection(provider):
    started = time.monotonic()
    try:
        await provider.open()
        if hasattr(provider, "probe"):
            await provider.probe()
            return {"ok": True, "latencyMs": round((time.monotonic() - started) * 1000)}
        # 初始化及短静音请求都通过才算成功，不只检查 HTTP 握手。
        await provider.send_audio(bytes(6400), last=True)

        async def drain():
            while True:
                _, last = await provider.receive()
                if last:
                    return

        await asyncio.wait_for(drain(), 5)
        return {"ok": True, "latencyMs": round((time.monotonic() - started) * 1000)}
    except Exception as error:
        return {"ok": False, "error": describe_error(error, getattr(provider, "label", "远程 ASR"))}
    finally:
        await provider.close()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=list(PROVIDERS), required=True)
    parser.add_argument("--port", type=int, default=10087)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    # 密钥经 stdin 传入，不出现在进程参数和日志中。
    config = validate_config(args.provider, json.loads(sys.stdin.readline()))
    factory = PROVIDERS[args.provider]
    if args.test:
        print(json.dumps(await test_connection(factory(config)), ensure_ascii=False), flush=True)
        return

    async def handle(client):
        await bridge(client, factory(config))

    async with serve(
        handle, "127.0.0.1", args.port, max_size=1024 * 1024, max_queue=16, close_timeout=1
    ):
        print("[remote-asr] %s ready on port %d" % (args.provider, args.port), flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
