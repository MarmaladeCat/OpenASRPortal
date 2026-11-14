# OpenASRPortal architecture and design

**English** | [简体中文](architecture.zh-CN.md)

Portal is a protocol/authorization boundary: downstream sees unified recognition sessions; server adapters handle upstream differences. It neither captures microphones, controls input methods, nor loads local model weights.

## Source layers

`src/openasrportal/entrypoints` owns service/offline-admin entry points; `api` handles aiohttp routes, auth, requests, and WS lifecycle; `application` orchestrates sessions, usage, and hotwords; `domain` defines rules/capabilities; `providers` adapts clouds/LocalASR; `storage` owns SQLite/key custody; `presentation` serves static administration and built-in recommendations.

Startup composes `Store` and `Portal`. Production, Windows service, and tests share this composition point; the workspace must not import it.

## Session lifecycle

Creation validates ASR key/audio/profile/quota/capacity, pins provider configuration/hotwords, and issues a short single-use ticket. WS consumes it, connects upstream, and permits PCM after ready. Normal completion flushes trailing audio and awaits finals; cancellation/errors have distinct terminals.

`providers/registry.py` defines constructors, capabilities and effective limits, independently of the legacy bridge. `application/recognition.py` owns receiving, draining, finalizing, cancellation, budgets and cleanup. Adapters interpret their wire protocol into typed `ProviderEvent` identities, audio order and stability; `domain/transcript.py` checks revisions and the contiguous stable prefix, and `domain/events.py` projects ordered `seq/utteranceId/revision` output. Partials replace the whole tail, finals remain immutable, and finished counts public publishing units. Default changes affect future sessions; active text is not spliced across models. Quotas, disablement, and revocation remain live checks.

Continuous providers implement open/write/finish/receive/close. `finish_input()` includes private queue drain and actual commit writing. `BufferedFileProvider` reserves bounded source PCM, then makes one JSON/SSE HTTP request after end; a known-length payload confirms its last byte and drain separately from result completion. Zero audio and pre-end cancellation make no file request. Persistent asynchronous jobs and polling adapters are not implemented. See the [recognition contract](recognition-contract.md).

## Authentication and data ownership

- Admin passwords use salted scrypt; login tokens retain digests only, expiring after 30 minutes by default.
- ASR authentication digests and optional reveal ciphertext are separate. Back up Fernet `asr-key-vault.key` with `portal.db`.
- Upstream keys remain in Portal; reads are sanitized. Management tokens do not authorize ASR; ASR keys do not authorize management.
- Per-key hotwords/snapshots are isolated; public recommendations persist separately with independent revisions. Downloading does not enable personal terms.

Usage/balances update transactionally. Local quotas debit accepted source samples once. Bailian task and OpenAI request/item token reports debit only cumulative increases; duration and unknown reports are stored separately, never converted to tokens. Missing final token reports block token-limited accounts while preserving known charges. File request counts begin at submission, not cache admission. Limited sessions hold account locks until cleanup; restart marks interruptions without erasing usage. Soniox's cloud stream duration differs from local audio quotas. Portal does not persist recordings/full transcripts; optional learning stores word-level statistics only.

## Extensions

OpenAI file and Realtime adapters share only OpenAI configuration/error/usage helpers. Realtime confirms the effective transcription session, continuously converts 16→24 kHz with one SoXR filter, disables VAD and commits once per round. File mode keeps source-rate WAV. The SSE parser, result ledger and file lifecycle are reusable mechanisms; supplier event identities remain in their adapter. [OpenAI setup](openai-api-setup.md) documents current models and workflow differences.

Bailian uses `qwen-audio-3.1-asr-flash-streaming` with DashScope duplex tasks, binary PCM and server-side sentence boundaries. No repeated HTTP recognition remains. Stored HTTP profiles migrate model/protocol/path on read and persist on save, keeping keys and account identity. Soniox uses `stt-rt-v6`, handshake authentication, stable-prefix/provisional-suffix updates and semantic `<end>` boundaries. End-of-audio awaits upstream completion; disconnects never promote provisional text to final. See [Bailian](bailian-api-setup.md) and [Soniox](soniox-api-setup.md).

The Boson adapter streams every PCM sample with manual turns and `higgs-stt-3.1` input transcription. Only audio end commits the round; no local silence/energy/15-second segmentation discards or cuts audio. Matching input-transcription completions become finals; duplicate item IDs and assistant output are ignored. See [Boson configuration](boson-api-setup.md).

New providers implement capabilities, connections, event conversion, metering, and error mapping, exposing fields through management `contract`. Clients render that contract rather than duplicate provider internals. Test simulated boundaries first, then real accuracy/latency/budgets under [testing requirements](testing.md).

[Client API](API.md) and [management API](MANAGEMENT.md) define external commitments; database schemas/Python classes are not cross-product APIs.
