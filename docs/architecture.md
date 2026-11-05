# OpenASRPortal architecture and design

**English** | [简体中文](architecture.zh-CN.md)

Portal is a protocol/authorization boundary: downstream sees unified recognition sessions; server adapters handle upstream differences. It neither captures microphones, controls input methods, nor loads local model weights.

## Source layers

`src/openasrportal/entrypoints` owns service/offline-admin entry points; `api` handles aiohttp routes, auth, requests, and WS lifecycle; `application` orchestrates sessions, usage, and hotwords; `domain` defines rules/capabilities; `providers` adapts clouds/LocalASR; `storage` owns SQLite/key custody; `presentation` serves static administration and built-in recommendations.

Startup composes `Store` and `Portal`. Production, Windows service, and tests share this composition point; the workspace must not import it.

## Session lifecycle

Creation validates ASR key/audio/profile/quota/capacity, pins provider configuration/hotwords, and issues a short single-use ticket. WS consumes it, connects upstream, and permits PCM after ready. Normal completion flushes trailing audio and awaits finals; cancellation/errors have distinct terminals.

Adapters normalize `seq/utteranceId/revision`. Partials replace, finals remain stable, finished counts unique finals. Default changes affect future sessions; active text is not spliced across models. Quotas, disablement, and revocation are still checked live on submission.

## Authentication and data ownership

- Admin passwords use salted scrypt; login tokens retain digests only, expiring after 30 minutes by default.
- ASR authentication digests and optional reveal ciphertext are separate. Back up Fernet `asr-key-vault.key` with `portal.db`.
- Upstream keys remain in Portal; reads are sanitized. Management tokens do not authorize ASR; ASR keys do not authorize management.
- Per-key hotwords/snapshots are isolated; public recommendations persist separately with independent revisions. Downloading does not enable personal terms.

Usage/balances update transactionally. Streaming meters submitted samples; HTTP previews/finals meter separately. Only actual token reports count. Restart releases stale reservations and marks interruptions, never erases failed-call usage. Portal does not persist recordings/full transcripts; optional learning stores word-level statistics only.

## Extensions

New providers implement capabilities, connections, event conversion, metering, and error mapping, exposing fields through management `contract`. Clients render that contract rather than duplicate provider internals. Test simulated boundaries first, then real accuracy/latency/budgets under [testing requirements](testing.md).

[Client API](API.md) and [management API](MANAGEMENT.md) define external commitments; database schemas/Python classes are not cross-product APIs.
