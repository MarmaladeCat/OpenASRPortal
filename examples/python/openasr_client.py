"""Small, copyable Portal v1 client. Requires Python 3.10+ and aiohttp 3.x.

Only public HTTP/WS; no Portal installation, database or upstream key is needed.
The caller supplies an async iterable of raw PCM16/16 kHz/mono byte chunks.
"""

import asyncio
import json
import re
import time
import uuid
from urllib.parse import urlencode, urlsplit

import aiohttp

AUDIO = {"encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1}
TERMINALS = {"session.finished", "session.cancelled", "session.error"}


class PortalError(Exception):
    def __init__(self, code, request_id=""):
        self.code, self.request_id = code, request_id
        super().__init__(code)


def require(condition):
    if not condition:
        raise PortalError("INVALID_SERVER_RESPONSE")


class Ledger:
    def __init__(self, session_id):
        self.session_id, self.seq = session_id, 0
        self.ready = False
        self.terminal = False
        self.utterances = {}

    def accept(self, event):
        require(isinstance(event, dict) and event.get("sessionId") == self.session_id)
        seq, kind = event.get("seq"), event.get("type")
        require(type(seq) is int and seq > 0 and not self.terminal)
        if seq <= self.seq:
            return False
        require(seq == self.seq + 1)
        self.seq = seq
        if kind in TERMINALS:
            if kind == "session.error":
                self.terminal = True
                raise PortalError(event.get("code", "SESSION_ERROR"), event.get("requestId", ""))
            if kind == "session.cancelled":
                self.terminal = True
                raise PortalError("SESSION_CANCELLED")
            count = event.get("finalCount")
            require(self.ready and type(count) is int
                     and count == sum(row[2] for row in self.utterances.values())
                     and not any(row[1] and not row[2] for row in self.utterances.values()))
            self.terminal = True
        elif kind == "session.ready":
            require(not self.ready and event.get("audio") == AUDIO)
            timeout = event.get("finalizeTimeoutMs")
            require(type(timeout) is int and 0 < timeout <= 300000)
            self.ready = True
        elif kind in {"transcript.partial", "transcript.final"}:
            identity, revision, text = event.get("utteranceId"), event.get("revision"), event.get("text")
            require(self.ready and isinstance(identity, str) and 0 < len(identity) <= 200
                    and type(revision) is int and revision > 0 and isinstance(text, str))
            previous = self.utterances.get(identity)
            final = kind == "transcript.final"
            if previous:
                if previous[2]:
                    require(final and text == previous[1])
                    return False
                if revision <= previous[0]:
                    return False
            require(len(self.utterances) < 10000 or identity in self.utterances)
            self.utterances[identity] = (revision, text, final)
            require(sum(len(row[1]) for row in self.utterances.values()) <= 1000000)
        else:
            # v1 does not introduce unnegotiated new event semantics.
            raise PortalError("UNSUPPORTED_EVENT")
        return True

    @property
    def text(self):
        return "".join(row[1] for row in self.utterances.values() if row[2])


class PortalClient:
    def __init__(self, origin, api_key):
        try:
            parsed = urlsplit(origin)
            port = parsed.port
        except (TypeError, ValueError):
            raise PortalError("INVALID_ORIGIN") from None
        require(parsed.scheme in {"http", "https"} and parsed.hostname
                and not parsed.username and not parsed.password
                and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment)
        require(port != 0 and not any(c.isspace() or ord(c) < 32 for c in origin)
                and isinstance(api_key, str) and api_key
                and not any(ord(c) < 32 or ord(c) == 127 for c in api_key))
        self.origin, self.api_key = origin.rstrip("/"), api_key
        self.http = None

    async def __aenter__(self):
        async def reject_redirect(session, context, params):
            raise PortalError("REDIRECT_REJECTED")
        trace = aiohttp.TraceConfig()
        trace.on_request_redirect.append(reject_redirect)
        self.http = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30), trace_configs=[trace], trust_env=False,
        )
        return self

    async def __aexit__(self, *args):
        await self.http.close()

    async def request(self, method, path, **kwargs):
        async with self.http.request(
            method, self.origin + path, headers={"Authorization": "Bearer " + self.api_key},
            allow_redirects=False, **kwargs,
        ) as response:
            if 300 <= response.status < 400:
                raise PortalError("REDIRECT_REJECTED")
            body = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                body.extend(chunk)
                require(len(body) <= 1048576)
            try:
                result = json.loads(body)
            except (ValueError, UnicodeError):
                raise PortalError("INVALID_SERVER_RESPONSE") from None
            require(isinstance(result, dict))
            if response.status >= 400:
                error = result.get("error", {})
                require(isinstance(error, dict))
                raise PortalError(error.get("code", "HTTP_ERROR"), error.get("requestId", ""))
            require(200 <= response.status < 300)
            return result

    async def capabilities(self):
        return await self.request("GET", "/v1/capabilities")

    async def profiles(self):
        return await self.request("GET", "/v1/profiles")

    async def transcribe(self, chunks, *, profile_id="", on_event=None, client_request_id=None):
        """Return stable text after finished; on_event synchronously receives previews/finals.

        Cancelling this coroutine cancels only its own session. No automatic retry
        or audio replay. on_event should return quickly; partials replace, not append.
        """
        session_id, socket, tasks, ledger = None, None, [], None
        try:
            caps = await self.capabilities()
            require(type(caps.get("protocolVersion")) is int and caps["protocolVersion"] == 1
                    and caps.get("audio") == AUDIO)
            maximum = caps.get("maxRecordingMs", 300000)
            require(type(maximum) is int and 0 < maximum <= 300000)
            descriptor = await self.request("POST", "/v1/sessions", json={
                "protocolVersion": 1, "profileId": profile_id, "purpose": "dictation",
                "clientRequestId": client_request_id or str(uuid.uuid4()), "audio": AUDIO,
                "requiredFeatures": [name for name in ("effectiveSessionLimits", "recognitionCapabilities")
                                     if name in caps.get("features", [])],
            })
            identity = descriptor.get("sessionId")
            require(isinstance(identity, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", identity))
            session_id = identity
            maximum = descriptor.get("limits", {}).get("maxRecordingMs", maximum)
            require(type(maximum) is int and 0 < maximum <= 300000)
            path = f"/v1/sessions/{session_id}/stream"
            require(descriptor.get("streamPath") == path)
            ticket, ttl = descriptor.get("ticket"), descriptor.get("ticketExpiresInMs")
            require(isinstance(ticket, str) and 0 < len(ticket) <= 512 and type(ttl) is int and ttl > 0)
            origin = "ws" + self.origin[4:]
            # No long-lived Authorization header on WS. Trace rejects WS redirects too.
            socket = await self.http.ws_connect(
                origin + path + "?" + urlencode({"ticket": ticket}),
                heartbeat=30, max_msg_size=1048576,
            )
            ledger = Ledger(session_id)

            end_sent = False

            async def receive():
                message = await socket.receive()
                if message.type != aiohttp.WSMsgType.TEXT:
                    raise PortalError("CONNECTION_CLOSED_WITHOUT_TERMINAL")
                try:
                    event = json.loads(message.data)
                except ValueError:
                    raise PortalError("INVALID_SERVER_RESPONSE") from None
                if isinstance(event, dict) and event.get("type") == "session.finished":
                    require(end_sent or event.get("reason") == "quota_exhausted")
                if ledger.accept(event) and on_event:
                    on_event(event)
                return event

            ready_timeout = descriptor.get("readyTimeoutMs", 45000)
            require(type(ready_timeout) is int and 1000 <= ready_timeout <= 60000)
            ready = await asyncio.wait_for(receive(), ready_timeout / 1000)
            require(ready["type"] == "session.ready")
            require("limits" not in descriptor or descriptor["limits"] == ready.get("limits"))

            async def upload():
                nonlocal end_sent
                size = 0
                async for chunk in chunks:
                    require(isinstance(chunk, bytes) and 0 < len(chunk) <= 1048576 and len(chunk) % 2 == 0)
                    size += len(chunk)
                    if size > maximum * 32:
                        raise PortalError("AUDIO_LIMIT")
                    await socket.send_bytes(chunk)
                end_sent = True
                await socket.send_json({"type": "audio.end"})

            async def download():
                while not ledger.terminal:
                    await receive()

            sender, receiver = asyncio.create_task(upload()), asyncio.create_task(download())
            tasks = [sender, receiver]
            done, _ = await asyncio.wait(tasks, timeout=maximum / 1000, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise PortalError("SESSION_TIMEOUT")
            for task in done:
                task.result()
            if not receiver.done():
                await asyncio.wait_for(receiver, ready["finalizeTimeoutMs"] / 1000)
            return ledger.text
        except (aiohttp.ClientError, asyncio.TimeoutError):
            # Transport exceptions may contain the ticket-bearing URL.
            raise PortalError("TRANSPORT_ERROR") from None
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if socket:
                await socket.close()
            if session_id and not (ledger and ledger.terminal):
                try:
                    await self.request("DELETE", "/v1/sessions/" + session_id)
                except (aiohttp.ClientError, asyncio.TimeoutError, PortalError):
                    pass  # A lost connection can already have released the session.


async def wav_chunks(path):
    """Read a PCM WAV at real-time pace; headers are never sent to Portal."""
    import wave
    with wave.open(str(path), "rb") as audio:
        if (audio.getsampwidth(), audio.getframerate(), audio.getnchannels(), audio.getcomptype()) != (2, 16000, 1, "NONE"):
            raise ValueError("WAV must be PCM16 / 16000 Hz / mono")
        started, samples = time.monotonic(), 0
        while chunk := audio.readframes(3200):
            yield chunk
            samples += len(chunk) // 2
            await asyncio.sleep(max(0, started + samples / 16000 - time.monotonic()))
