"""使用公开 v1 协议回放 WAV，不依赖桌面应用。"""

import argparse
import asyncio
import getpass
import json
import uuid
import wave
from urllib.parse import urlencode

from aiohttp import ClientSession, WSMsgType


async def recognize(url, key, profile, wav):
    with wave.open(wav, "rb") as audio:
        if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (16000, 1, 2):
            raise ValueError("需要 16kHz 单声道 PCM16 WAV")
        pcm = audio.readframes(audio.getnframes())
    async with ClientSession(headers={"Authorization": "Bearer " + key}) as client:
        async with client.post(
            url.rstrip("/") + "/v1/sessions",
            json={
                "profileId": profile,
                "purpose": "dictation",
                "clientRequestId": str(uuid.uuid4()),
            },
        ) as response:
            created = await response.json()
            if response.status != 201:
                raise RuntimeError(created.get("error", {}).get("message", "创建会话失败"))
        socket_url = (
            url.rstrip("/") + created["streamPath"] + "?" + urlencode({"ticket": created["ticket"]})
        )
        async with client.ws_connect(socket_url) as socket:
            sender = None

            async def upload():
                for offset in range(0, len(pcm), 6400):
                    await socket.send_bytes(pcm[offset : offset + 6400])
                    await asyncio.sleep(0.2)
                await socket.send_json({"type": "audio.end"})

            try:
                async for message in socket:
                    if message.type != WSMsgType.TEXT:
                        break
                    event = json.loads(message.data)
                    print(json.dumps(event, ensure_ascii=False))
                    if event["type"] == "session.ready":
                        sender = asyncio.create_task(upload())
                    if event["type"] == "session.error":
                        raise RuntimeError(event["message"])
                    if event["type"] == "session.finished":
                        return
                raise RuntimeError("连接提前关闭，未收到完整定稿")
            finally:
                if sender:
                    sender.cancel()
                    await asyncio.gather(sender, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("wav")
    parser.add_argument("--url", default="http://127.0.0.1:10087")
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    asyncio.run(
        recognize(
            args.url,
            getpass.getpass("管理页派生的识别 Key："),
            args.profile,
            args.wav,
        )
    )
