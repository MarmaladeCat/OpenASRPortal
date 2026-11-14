"""A metered management probe, independent of the legacy wire bridge."""

import asyncio
import time

from ..domain.asr_protocol import describe_error
from ..domain.events import EventStream


async def test_connection(provider):
    started = time.monotonic()
    try:
        await asyncio.wait_for(provider.open(), 40)
        if hasattr(provider, "probe"):
            await asyncio.wait_for(provider.probe(), 75 + provider.finish_timeout)
        else:
            await asyncio.wait_for(provider.write_audio(bytes(6400)), 15)
            await asyncio.wait_for(provider.finish_input(), 75)
            stream = EventStream("probe")

            async def drain():
                while True:
                    events, last = await provider.receive()
                    stream.apply(events)
                    if last:
                        stream.finish()
                        return

            await asyncio.wait_for(drain(), provider.finish_timeout)
        return {"ok": True, "latencyMs": round((time.monotonic() - started) * 1000)}
    except Exception as error:
        return {"ok": False, "error": describe_error(error, getattr(provider, "label", "远程 ASR"))}
    finally:
        await asyncio.wait_for(provider.close(), 5)
