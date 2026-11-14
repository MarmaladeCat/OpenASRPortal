# Recognition workflows and ordered results

**English** | [简体中文](recognition-contract.zh-CN.md)

This supplements the [public v1 API](API.md). A WebSocket, `stream=true`, or `partialResults=true` alone does not promise text during recording.

## Effective capability snapshot

`GET /v1/profiles` includes `capabilities.recognition` and `capabilities.limits`. Creation and `session.ready` repeat the same frozen `profileId`, `capabilities`, and `limits`. Profile edits affect subsequent sessions.

Recognition fields:

- `upstreamInput`: `continuous` or `complete_recording`.
- `processingMode`: `online`, `batch`, `online_with_second_pass`, or `unknown`; an unknown implementation is not inferred from its transport.
- `preview`: `supported` plus `phase` (`during_capture`, `after_commit`, `after_audio_end`, `none`, or `unknown`).
- `stability`: `unit` (`token`, `utterance`, `turn`, `recording`) and `triggers`. Stability does not end the session.
- `completion`: `upstream_done`, `http_response`, `sse_done`, or `committed_items`.
- `sessionEnd`: `audio.end`; `portalSegmentation`: `none`.
- `secondPass`: support is `supported` or `unknown`; `enabled` is a boolean when known, otherwise null. Doubao retains its saved second-pass preference.

Compatibility fields remain: `partialResults` means partials may occur; `latencyClass=streaming` means preview during capture, while `segmented` is the legacy fallback for other/unknown timing. `finalization` describes result stability, not automatic session completion. LocalASR's internal streaming strategy is unknown to Portal.

The server advertises `effectiveSessionLimits`, `recognitionCapabilities`, and `realtimePreview` in `features`. Clients opt in using `requiredFeatures`. `realtimePreview` is checked against the selected profile. A new profile with a limit below 300 seconds requires `effectiveSessionLimits`; older clients are rejected at creation rather than allowed to over-record.

Limits contain `maxRecordingMs`, `maxMessageBytes`, `maxQueuedAudioBytes`, `readyTimeoutMs`, `uploadTimeoutMs`, `recognitionTimeoutMs`, and `finalizeTimeoutMs`. The last is upload budget + recognition budget + 1000 ms. Creation/ready snapshots, rather than a brand-specific UI constant, are authoritative.

## Available workflows

| Provider | Input / preview | Stable unit / completion | Recording maximum |
| --- | --- | --- | --- |
| Doubao | continuous / during capture | utterance / upstream done | 300 s |
| Bailian | continuous / during capture | utterance / upstream done | 300 s |
| LocalASR WS | continuous / unknown timing | utterance / upstream done | 300 s |
| Soniox | continuous / during capture | stable tokens / upstream done | 300 s |
| Boson | continuous / no preview | manual turn / matching completion | 300 s |
| LocalASR HTTP | complete recording / no preview | recording / full JSON | 60 s |
| OpenAI file JSON | complete recording / no preview | recording / full JSON | 300 s |
| OpenAI file SSE | complete recording / after audio end | recording / SSE done | 300 s |
| OpenAI live | continuous / during capture | manual turn / matching completion | 300 s |
| OpenAI committed-turn | continuous / after commit | manual turn / matching completion | 300 s |

## Ordered v1 output

The public transcript is an immutable, audio-ordered prefix plus one replaceable preview tail. `seq` is delivery order, not evidence of audio order. Provider identities and predecessor/sentence/full-history evidence are checked before publishing finals. Equal text or equal timestamps are not duplicate identities. Conflicting stable text is `UPSTREAM_PROTOCOL_ERROR`.

One public utterance can combine several upstream units. When A awaits correction and B is already stable, both remain in the preview until A stabilizes. If A stabilizes first, publish its final, then publish B's remaining preview with a new public ID. The final can be shorter than the preceding preview. Partial text fully replaces the current tail, including an empty withdrawal. An empty final closes a withdrawn unit and counts in `finalCount`.

All declared units, including empty candidates, must stabilize and form a gap-free prefix before success. Final count counts public publishing units, not vendor sentences. Missing predecessors, unfinished candidates and transport EOF cannot manufacture success. Consumers append each unique final once and never roll back earlier text to accommodate an upstream correction.

## Audio and lifecycle

States are connecting → receiving → draining → finalizing → terminal. Audio and `audio.end` before ready are invalid; cancellation remains available. Repeated end is idempotent. Only one terminal is published. Sends and cleanup are bounded.

Source audio stays PCM16/16 kHz/mono. Zero-sample sessions finish locally with no file/commit. Nonzero silence is delivered normally. Continuous adapters preserve vendor pacing. Boson's private uploader must drain before its commit barrier. File adapters keep bounded memory, seal once, then issue one request. Known-length HTTP payloads signal submission only after the last body byte and writer drain, independently of the response. There is no automatic audio retry, local VAD, or repeated file-preview request.

The 75-second upload budget starts at explicit/quota-triggered end; the provider recognition budget starts after actual submission. Upload failures use `UPLOAD_TIMEOUT`; result waits use `FINALIZATION_TIMEOUT`. Finished reports `acceptedAudioSamples` and `submittedAudioSamples` in source-rate samples. Quota completion also reports `truncated: true` and its existing reason/scope. In-flight audio after quota end may be discarded. These counters do not claim per-packet vendor ACKs or processed audio progress.

File cache admission reserves the maximum source PCM size against a 64 MiB Portal budget. WAV/base64/multipart encoders stream chunks rather than allocating whole encoded copies. Recordings remain in memory and are released on upload or cleanup. There is no persistent asynchronous job API, resume, or public long-file upload API; the current file adapters are one bounded HTTP request (JSON/SSE), not polling jobs.

OpenAI Realtime lazily loads numpy/SoXR, maintains one continuous 16→24 kHz converter per session and flushes once. Other paths do not resample. See [OpenAI setup](openai-api-setup.md) and [acceptance requirements](testing.md).

## Usage

Local audio quotas debit accepted source samples once. Supplier reports remain separate: OpenAI request/item scopes distinguish `tokens`, `duration`, and `unknown`, deduplicate cumulative reports, and never convert seconds into tokens. Missing usage is not zero. Token-limited accounts retain the existing unavailable-report blocking behavior when the upstream reports duration or omits tokens. Cancellation cannot promise a supplier refund.
