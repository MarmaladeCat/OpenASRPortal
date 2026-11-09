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

Usage/balances update transactionally. Streaming meters submitted samples once. Bailian cumulative token reports debit only increases, then settle on task completion; missing final reports block token-limited accounts. Limited streams acquire account locks until cleanup; restart marks interruptions without erasing usage. Soniox's stream-duration cloud billing differs from Portal's local audio quotas. Portal does not persist recordings/full transcripts; optional learning stores word-level statistics only.

## Extensions

Bailian uses `qwen-audio-3.1-asr-flash-streaming` with DashScope duplex tasks, binary PCM and server-side sentence boundaries. No repeated HTTP recognition remains. Stored HTTP profiles migrate model/protocol/path on read and persist on save, keeping keys and account identity. Soniox uses `stt-rt-v6`, handshake authentication, stable-prefix/provisional-suffix updates and semantic `<end>` boundaries. End-of-audio awaits upstream completion; disconnects never promote provisional text to final. See [Bailian](bailian-api-setup.md) and [Soniox](soniox-api-setup.md).

The Boson adapter streams PCM with manual turns and `higgs-stt-3.1` input transcription. Local silence/15-second segmentation commits one turn at a time; backpressure prevents later turns replacing pending transcripts. Only matching input-transcription completions become finals; duplicate item IDs and assistant output are ignored. See [Boson configuration](boson-api-setup.md).

New providers implement capabilities, connections, event conversion, metering, and error mapping, exposing fields through management `contract`. Clients render that contract rather than duplicate provider internals. Test simulated boundaries first, then real accuracy/latency/budgets under [testing requirements](testing.md).

[Client API](API.md) and [management API](MANAGEMENT.md) define external commitments; database schemas/Python classes are not cross-product APIs.
