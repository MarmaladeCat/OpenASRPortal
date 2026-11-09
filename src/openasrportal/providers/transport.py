"""Explicit per-profile routing, independent of environment proxy variables."""

import asyncio
import time
from urllib.parse import urlsplit

import aiohttp
from websockets.exceptions import InvalidStatusCode
from websockets.legacy.client import connect as direct_connect

from ..domain.asr_protocol import ProviderError


async def test_proxy(proxy, target):
    """Measure an HTTPS request through CONNECT, without persisting draft settings."""
    try:
        url = urlsplit(target)
        valid = (
            isinstance(target, str) and len(target) <= 2048 and url.scheme == "https"
            and url.hostname and url.port != 0 and not url.username and not url.password
            and not url.fragment and not any(c.isspace() or ord(c) < 32 for c in target)
        )
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise ValueError("测试目标须为不含凭据的 HTTPS 地址")
    if not proxy.get("url"):
        raise ValueError("请先填写代理地址")
    started = time.monotonic()
    result = {"ok": False}
    auth = (
        aiohttp.BasicAuth(proxy["username"], proxy.get("password", ""), encoding="utf-8")
        if proxy.get("username") else None
    )
    try:
        async with aiohttp.ClientSession(
            trust_env=False, timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            async with session.get(
                target, proxy=proxy["url"], proxy_auth=auth, allow_redirects=False
            ) as response:
                result["ok"] = 200 <= response.status < 400
                result["status"] = response.status
                if not result["ok"]:
                    result["error"] = "测试目标返回 HTTP %d" % response.status
    except asyncio.TimeoutError:
        result["error"] = "代理测试超时"
    except aiohttp.ClientHttpProxyError:
        result["error"] = "代理连接或认证失败，请检查 Proxy 设置"
    except (aiohttp.ClientError, OSError):
        result["error"] = "代理连接失败，请检查 Proxy 地址、证书和网络"
    result["latencyMs"] = round((time.monotonic() - started) * 1000)
    return result


class ProxySocket:
    def __init__(self, session, socket):
        self.session = session
        self.socket = socket

    async def send(self, data):
        if isinstance(data, str):
            await self.socket.send_str(data)
        else:
            await self.socket.send_bytes(data)

    async def recv(self):
        message = await self.socket.receive()
        if message.type in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
            return message.data
        raise ProviderError("代理上游连接已中断，请检查网络后重试")

    async def close(self):
        try:
            await self.socket.close()
        finally:
            await self.session.close()


async def connect(endpoint, *, use_proxy=False, proxy=None, **options):
    if not use_proxy:
        return await direct_connect(endpoint, **options)
    if not proxy or not proxy.get("url"):
        raise ProviderError("此上游已启用代理，请先在 Proxy 设置中配置代理地址")
    session = aiohttp.ClientSession(trust_env=False)
    try:
        auth = aiohttp.BasicAuth(proxy["username"], proxy.get("password", ""), encoding="utf-8") \
            if proxy.get("username") else None
        socket = await asyncio.wait_for(
            session.ws_connect(
                endpoint, proxy=proxy["url"], proxy_auth=auth,
                headers=options.get("extra_headers"),
                max_msg_size=options.get("max_size", 4 * 1024 * 1024),
                timeout=aiohttp.ClientWSTimeout(ws_close=options.get("close_timeout", 1)),
                heartbeat=20,
            ), options.get("open_timeout", 10),
        )
        return ProxySocket(session, socket)
    except BaseException as error:
        await session.close()
        if isinstance(error, asyncio.TimeoutError):
            raise
        if isinstance(error, aiohttp.ClientHttpProxyError):
            raise ProviderError("代理连接或认证失败，请检查 Proxy 设置") from None
        if isinstance(error, aiohttp.WSServerHandshakeError):
            raise InvalidStatusCode(error.status, {}) from None
        if isinstance(error, (aiohttp.ClientError, OSError)):
            raise ProviderError("代理连接失败，请检查 Proxy 地址、证书和网络") from None
        raise
