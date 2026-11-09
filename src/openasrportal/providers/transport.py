"""Explicit per-profile routing, independent of environment proxy variables."""

import asyncio

import aiohttp
from websockets.exceptions import InvalidStatusCode
from websockets.legacy.client import connect as direct_connect

from ..domain.asr_protocol import ProviderError


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
