# Third-party Python integration

**English** | [简体中文](python-client.zh-CN.md)

Start with the [copyable Python example](../examples/python/README.md): `openasr_client.py`, a WAV CLI, and one dependency. It talks only to public Portal HTTP/WS and needs a client ASR key, never an upstream key or database.

## Protocol scope and extensibility

The [v1 reference](API.md) covers discovery, profile selection, creation/tickets, PCM transport, previews/revisions, stable finals, cancellation, error terminals, quotas and personal hotwords. It is suitable for third-party recording clients. It intentionally does not provide microphone capture, arbitrary audio codecs, resumable audio upload, translation, or upstream account provisioning through the ASR key.

Clients inspect `protocolVersion`, audio, event types and optional `features` from `/v1/capabilities`. Additive fields may be ignored. New incompatible event semantics require a negotiated feature or a new protocol version. `protocolVersion: 1` and `requiredFeatures` on session creation make requirements explicit; unsupported versions/features fail before a session is allocated. Missing optional capability fields on an older Portal mean the feature is unavailable, not implicitly supported.

## Lifecycle guarantees

- The same owner/request ID with the same creation parameters reuses an unconnected, unexpired descriptor; changed parameters return `REQUEST_CONFLICT`. Connected sessions return `SESSION_STARTED`. Completed sessions are not a durable idempotency store.
- Only ready authorizes audio sends. Upload and receive concurrently. Audio end is idempotent; subsequent audio is `INVALID_STATE`. Cancellation remains available over the same WS while finalization is pending, or through authenticated DELETE.
- Sequence numbers and revisions reject gaps/stale data. A unique final is immutable; finalCount and unresolved-preview checks prevent false success. One terminal wins a cancellation/finalization race. A disconnected socket is not a successful terminal.
- All accepted PCM is forwarded, including pauses; transport chunks do not impose sentence boundaries. Boson commits at audio end, Soniox defaults to no endpoint detection, while Doubao/Bailian still apply upstream semantics. Upstream punctuation is not an exact sentence-boundary guarantee.

The example rejects HTTP and WS redirects and validates the exact same-origin stream path. It avoids automatic reconnect/replay, closes its upload/receive tasks, and cleans up only sessions it created. HTTP errors have `error.code`; WS errors have `session.error`. Branch on codes, not translated messages. The API reference documents limits and error recovery.

## Verification

Run `python scripts/test.py run --suite unit --allow-skips` from the standalone Portal repository. Example tests use loopback HTTP/WS and simulated transcripts to check ready-before-upload, final-only output, redirects, abnormal closure and cancellation. These checks do not establish real cloud recognition, microphone quality or platform installation acceptance.
