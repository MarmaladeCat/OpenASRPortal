# Copyable Python ASR client

**English** | [简体中文](README.zh-CN.md)

Use Python 3.10+ with the client ASR key issued by Portal. Copy this directory into your application; it has no imports from Portal or another product. Only `aiohttp` is required.

```bash
python -m venv .venv
# Windows: .venv\Scripts\python.exe instead
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python transcribe.py recording.wav --portal http://127.0.0.1:10087
```

The command prompts privately for the ASR key, or reads `OPENASR_ASR_KEY`. Do not put a key in command-line arguments or source. WAV must contain uncompressed PCM16, 16 kHz, mono. The file helper strips the WAV header and sends every sample, including silence, at real-time pace. `--profile ID` chooses a Portal profile; omit it to use the default. HTTPS automatically uses WSS.

## Embed

```python
import asyncio
from openasr_client import PortalClient, wav_chunks

async def recognize(origin, asr_key, wav_path):
    async with PortalClient(origin, asr_key) as client:
        return await client.transcribe(wav_chunks(wav_path))

# Feed a microphone's async iterable of bytes instead of wav_chunks(...).
# Call asyncio.run(recognize(...)) from a synchronous program.
```

`on_event=callback` receives validated events synchronously, so keep it fast. Display partials by replacing the current utterance, never appending each revision. Final text is concatenated in utterance order without inventing spaces; the raw upstream spelling/punctuation is retained. `transcribe()` returns only after a valid `session.finished`, with a matching finalCount and no unresolved nonempty preview. For immediate text delivery, commit each unique final once in your own event loop. Cancellation cannot undo text you already committed.

Cancel the task with `task.cancel()` and await it; `CancelledError` propagates after owned-session cleanup. There is no automatic retry/audio replay. HTTP/WS redirects are rejected, tickets remain on the exact same-origin session path, transport exceptions are reduced to a safe error code, and disconnects without a terminal are failures. The creation retry ID is optional; reuse one only for a retry of the same creation request, never for replaying audio.

This is a small reference client, not a microphone driver or resampler. Each call is one v1 round, at most five minutes or the smaller negotiated recording limit. It consumes `effectiveSessionLimits`, the descriptor's `readyTimeoutMs` (45-second legacy fallback), and Portal's finalization timeout. Responses are bounded; it never splits an oversized recording into hidden requests. See the [complete API](../../docs/API.md) for negotiation, quotas, hotwords and lifecycle errors, and the [quick integration guide](../../docs/python-client.md).
