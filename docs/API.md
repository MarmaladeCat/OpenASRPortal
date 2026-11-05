# OpenASRPortal Recognition and Personal Hotwords API v1

**English** | [简体中文](API.zh-CN.md)

The complete downstream reference for OpenASRInput and other clients, describing the current implementation. HTTP and WebSocket use v1; clients do not connect directly to Doubao, Bailian, or LocalASR internal protocols. See [management](MANAGEMENT.md) for admin authentication, profiles, public dictionaries, and usage; see the [user guide](user-guide.md) for installation/operation.

## 1. Responsibilities, addresses, and authentication

- Default origin: `http://127.0.0.1:10087`. Input takes an HTTP(S) origin without a business path, query, or user/password.
- Clients capture/resample audio, display waveforms/preedit, identify targets, and commit text.
- Portal owns recognition sessions, upstreams, credentials, personal hotwords, and quotas; it never manipulates Fcitx or the active application.
- Clients use an **ASR access key**. Upstream keys stay in Portal; admin passwords/sessions do not authorize recognition.
- Protected HTTP requests use `Authorization: Bearer <ASR_KEY>`; JSON requests use `Content-Type: application/json`.
- WS authenticates with the creation response's single-use ticket, without long-lived Authorization.
- Same-key devices share personal hotwords, but each recording has separate sessionId/audio/events. Different keys are isolated.
- Revoking a key rejects subsequent HTTP authentication and cancels its pending/active sessions.
- Input rejects HTTP/WS redirects and verifies streamPath refers to the original Portal's current session, preventing credential forwarding.
- HTTP responses use `Cache-Control: no-store`. Refresh capabilities, profiles, catalog, and personal settings as needed.

Example IDs, keys, text, and limits are illustrative. Runtime capabilities and ready responses take precedence.

## 2. Endpoint overview

| Method           | Path                                  | Authentication / purpose                                    |
| ---------------- | ------------------------------------- | ----------------------------------------------------------- |
| GET              | `/health`                             | Public liveness                                             |
| GET              | `/v1/capabilities`                    | ASR key; protocol/audio capabilities                        |
| GET              | `/v1/profiles`                        | ASR key; sanitized profiles/default                         |
| POST             | `/v1/sessions`                        | ASR key; create one recording session                       |
| WS               | `/v1/sessions/{id}/stream?ticket=...` | Single-use ticket; audio/events                             |
| DELETE           | `/v1/sessions/{id}`                   | ASR key; cancel an owned session                            |
| GET/PATCH        | `/v1/hotwords`                        | ASR key; read/save personal list                            |
| DELETE           | `/v1/hotwords/statistics`             | ASR key; clear own frequency statistics                     |
| GET              | `/v1/hotwords/catalog`                | ASR key; shared recommendation catalog                      |
| GET              | `/v1/hotwords/catalog/{sourceId}`     | ASR key; complete recommendation download                   |
| POST             | `/v1/hotwords/dictionaries`           | ASR key; preview or save a personal recommendation snapshot |
| GET/PATCH/DELETE | `/v1/hotwords/dictionaries/{id}`      | ASR key; manage own snapshot                                |

Valid keys share public recommendations; only the corresponding key accesses its personal list/snapshots. `/v1/admin/hotwords/public-dictionaries` requires management identity, not an ASR client key.

## 3. Capabilities and profiles

### 3.1 GET /health

```json
{ "status": "ok", "service": "OpenASRPortal", "protocolVersion": 1, "managementPage": "/admin" }
```

Health neither establishes configured upstreams/remaining quota nor creates a recording session.

### 3.2 GET /v1/capabilities

```json
{
  "protocolVersion": 1,
  "audio": { "encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1 },
  "maxSessions": 8,
  "maxRecordingMs": 300000,
  "resumable": false,
  "hotwords": {
    "version": 1,
    "path": "/v1/hotwords",
    "scope": "access-key",
    "dictionaries": true,
    "catalogPath": "/v1/hotwords/catalog",
    "personalTableOnly": true,
    "recommendationWords": true,
    "publicDictionaries": true,
    "publicDownloadPath": "/v1/hotwords/catalog/{sourceId}"
  },
  "events": [
    "session.ready",
    "transcript.partial",
    "transcript.final",
    "session.finished",
    "session.cancelled",
    "session.error"
  ]
}
```

`maxSessions` defaults to 8 for the entire Portal, not per key; service construction can change it. v1 does not resume audio. Older Portals may omit newer public-download/personal-table capability fields; tolerate their absence. Input asks for an upgrade if hotwords v1 is absent. New clients can inspect `publicDictionaries` or use compatible `POST dictionaries` with `sourceId/preview:true`.

### 3.3 GET /v1/profiles

Returns `profiles`, `defaultProfileId`, and administrator-defined `profileOrder`. Profiles follow that order and may include disabled entries; use `quota` for availability.

```json
{
  "profiles": [
    {
      "id": "doubao-1",
      "title": "Default cloud recognition",
      "provider": "doubao_realtime",
      "configuration": { "endpoint": "wss://example.invalid/asr", "hasApiKey": true },
      "quota": { "enabled": true, "disabledReason": "", "exhausted": false, "tokenBlocked": false },
      "capabilities": {
        "partialResults": true,
        "textProcessing": "native",
        "latencyClass": "streaming",
        "audio": { "encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1 },
        "tokenUsage": false,
        "hotwords": { "supported": true, "mode": "inline-context", "maxTokens": 100 }
      }
    }
  ],
  "defaultProfileId": "doubao-1",
  "profileOrder": ["doubao-1"]
}
```

Other configuration fields depend on provider; keys are never echoed. quota may be null. profileId is a Portal profile ID, not a model name; session creation does not directly select an upstream model. latencyClass `streaming` means streaming; `segmented` means segmented/polling previews, with different latency expectations.

## 4. Session creation and single-use connection

### 4.1 POST /v1/sessions

```json
{
  "profileId": "doubao-1",
  "clientRequestId": "f22b73e4-9c6d-4b29-82a6-example",
  "purpose": "dictation",
  "audio": { "encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1 }
}
```

| Field           | Rule                                                                          |
| --------------- | ----------------------------------------------------------------------------- |
| profileId       | Omitted/null/empty follows default; otherwise must be valid and exist         |
| clientRequestId | Optional text, up to 200 characters; recommend one UUID per round             |
| purpose         | Current Input sends dictation; describes purpose without granting permissions |
| audio           | Optional; if present must exactly match negotiated PCM16 / 16 kHz / mono      |

Nonempty profileId matches `[A-Za-z0-9][A-Za-z0-9_.-]{0,99}`. Explicitly selecting a missing/disabled profile never silently falls back. Creation resolves/pins the default, upstream configuration, and this key's hotword selection.

Success **201**:

```json
{
  "sessionId": "session-example",
  "ticket": "one-time-ticket-example",
  "streamPath": "/v1/sessions/session-example/stream",
  "ticketExpiresInMs": 29999
}
```

Tickets default to 30 seconds and one use. TTL is remaining milliseconds, not a hard-coded example value. Input verifies the exact same-origin session stream path before using the original Portal's WS/WSS origin.

**Creation retry idempotency:** the same key and nonempty clientRequestId return the same unconnected, unexpired descriptor without extending TTL. An established WS returns 409 `SESSION_STARTED`. After termination/expiry cleanup, the request ID no longer guarantees the old session; never use it to replay recognized audio.

### 4.2 WebSocket handshake

```text
ws://127.0.0.1:10087/v1/sessions/session-example/stream?ticket=one-time-ticket-example
```

HTTPS uses WSS. After HTTP upgrade, Portal connects upstream; await `session.ready`. Preparation can fail before upgrade with HTTP or afterward with `session.error`; the first event need not be successful. Used tickets, missing sessions, or revoked keys return 401 `AUTH_FAILED`. A still-identifiable expired ticket returns 401 `TICKET_EXPIRED`; after cleanup it may return `AUTH_FAILED`. Create a new session after failure; old tickets neither resume nor reconnect.

## 5. Audio and client control

### 5.1 Binary audio

- After ready, send **WebSocket binary messages**, not JSON, Base64, or file uploads.
- Signed little-endian PCM16, 16000 Hz, mono, without WAV/MP3 headers.
- Each chunk has an even byte count. Input chunks are nonempty and contain complete 16-bit samples.
- 20 ms = 640 bytes; 200 ms = 6400 bytes. Portal batches upstream sends at 6400 bytes.
- Read events continuously while uploading; do not wait for all upload data to finish.
- Maximum WS message: 1 MiB. Maximum recording: 300 seconds / 9600000 bytes.
- Input proactively finalizes around 295 seconds, leaving margin under five minutes.
- Portal uses a 30-second WS heartbeat, not an application `ping` command.

### 5.2 Normal finalization

Send one text JSON message:

```json
{ "type": "audio.end" }
```

Stop uploading, but keep receiving partials/finals until `session.finished` or a failure terminal event. audio.end flushes the incomplete PCM batch. Closing the socket is not finalization. Input sets a one-shot deadline from ready.finalizeTimeoutMs; new partials do not extend it.

### 5.3 Cancellation

On an established WS:

```json
{ "type": "session.cancel" }
```

Before/during connection or for explicit cleanup, use the ASR key:

```text
DELETE /v1/sessions/{sessionId}
```

Success is `{"ok":true}`, including absent/already-cleaned sessions. An existing session owned by another key returns 403. A key may cancel any owned session, but clients should cancel only IDs they created. Cancellation abandons a round, unlike audio.end's finalization; session.cancelled is not successful finished.

## 6. Server events and result ledger

### 6.1 Common fields

Every event contains `type`, `sessionId`, and `seq`. seq increases from 1 within a session, continuously in send order on a normal connection. Reject old sessionId first, then verify seq. Ignore already-processed seq; a new gap is a protocol fault, not permission to resubmit audio. Identical text may carry a new seq: update the event ledger rather than deduplicating solely by text.

### 6.2 session.ready

```json
{
  "type": "session.ready",
  "sessionId": "session-example",
  "seq": 1,
  "audio": { "encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1 },
  "textProcessing": "native",
  "finalizeTimeoutMs": 11000,
  "hotwords": { "supported": true, "appliedCount": 2, "omittedCount": 0 }
}
```

Ready occurs once. Verify audio and a positive integer finalizeTimeoutMs. Timeout depends on provider. Hotword counts describe the creation snapshot, not the entire personal list. supported=true does not mean enabled; the default-off switch gives appliedCount 0.

### 6.3 transcript.partial and transcript.final

```json
{
  "type": "transcript.partial",
  "sessionId": "session-example",
  "seq": 2,
  "utteranceId": "session-example:1",
  "revision": 1,
  "text": "neural net",
  "startMs": 0,
  "endMs": 800,
  "source": ""
}
```

```json
{
  "type": "transcript.final",
  "sessionId": "session-example",
  "seq": 3,
  "utteranceId": "session-example:1",
  "revision": 2,
  "text": "Neural network.",
  "startMs": 0,
  "endMs": 1100,
  "source": ""
}
```

| Field         | Meaning                                                                       |
| ------------- | ----------------------------------------------------------------------------- |
| utteranceId   | Stable utterance identity; treat as opaque                                    |
| revision      | Increasing positive integer within an utterance; restarts for a new utterance |
| text          | Complete replacement, not a delta; may be empty                               |
| startMs/endMs | Time relative to session audio; null if unknown/no valid interval             |
| source        | Optional upstream source description; never a deduplication key               |

Partials replace preedit at higher revisions. A final closes the utterance; finalized text cannot change, and the next utterance has a new ID. Ignore old revisions but consume their new seq. Duplicate finals never recommit; changed final text is a protocol error. Empty finals count toward finalCount even without characters to commit. All providers use these final fields.

### 6.4 Success, cancellation, and error terminals

```json
{ "type": "session.finished", "sessionId": "session-example", "seq": 4, "finalCount": 1 }
```

finalCount must equal the unique finals received. Input also requires no nonempty unfinalized preview. Socket closure without a terminal event is not success.

Automatic finalization when quota runs out:

```json
{
  "type": "session.finished",
  "sessionId": "session-example",
  "seq": 4,
  "finalCount": 1,
  "reason": "quota_exhausted",
  "quotaScope": "key"
}
```

quotaScope may be key/profile/account depending on the trigger stage. Use it diagnostically, not as an input command. Prior stable finals remain valid. Stop capture and audio sends.

```json
{ "type": "session.cancelled", "sessionId": "session-example", "seq": 4 }
```

```json
{
  "type": "session.error",
  "sessionId": "session-example",
  "seq": 4,
  "code": "FINALIZATION_TIMEOUT",
  "message": "等待最终定稿超时",
  "retryable": true,
  "requestId": "diagnostic-request-id"
}
```

The example message means “timed out waiting for final results”; message text may remain Chinese. No ledger changes follow a terminal event, and errors are not followed by successful finished. retryable permits trying a new session, not automatic replay or guaranteed immediate success.

## 7. Local client state and commits

Recommended lifecycle:

```text
idle/paused → connecting → session.ready → listening
listening → stop and flush → audio.end → pausing → session.finished → paused
any active state → cancel → session.cancelled → idle
connection/recognition/commit failure → failed
```

Pause is not a WS command: Input ends the session and creates another when recording resumes. Input uses Shift+Space for dictation, Enter to finalize, Esc to cancel, Linux Alt+Z / Windows Alt+X for text-command editing. These keystrokes never go to Portal.

Input queues each final and calls its bridge in the host-safe event loop without waiting to display all text at session end. Other clients may commit after finished; both strategies must commit each final at most once. Partials are not permanent text. Portal utteranceId/revision deduplicate recognition; host commitId deduplicates local delivery.

Input pins `lease/contextId/focusEpoch` and separates rounds with `generation`. These are local bridge fields, not Portal HTTP/WS. Lost focus, changed targets, old generations/sessions must never affect a new editor. Preserve unconfirmed text after uncertain ACKs, never blindly resend to a new target. Portal cannot retract successful commits after cancellation.

## 8. Personal hotwords and public recommendations

### 8.1 GET /v1/hotwords

Optional `?profileId=...` selects capability inspection; omission uses default. Personal lists remain manageable without a default upstream, with selection absent. An explicit missing profile returns 404.

```json
{
  "version": 1,
  "revision": 0,
  "profileId": "doubao-1",
  "settings": {
    "enabled": false,
    "autoLearn": false,
    "windowDays": 30,
    "minFrequency": 3,
    "maxWords": 100,
    "manualTerms": [],
    "excludedTerms": []
  },
  "learnedTerms": [],
  "terms": [],
  "dictionaries": [],
  "dictionaryCandidateLimit": 0,
  "personalTableOnly": true
}
```

selection, when present, contains capability, terms, omitted, appliedCount, and budgetUsed. Top-level terms are saved nonexcluded personal words; selection.terms is the actual upstream subset. manualTerms is the historical field name for the user-maintained list. Current Input/Portal pages show word/weight/enabled rows; disabled words remain in manualTerms and appear in excludedTerms. Page saves use autoLearn=false and maxWords=2000. See §11 for personal JSON.

| Setting       | Default / limits                                                                                    |
| ------------- | --------------------------------------------------------------------------------------------------- |
| enabled       | false; explicitly enable and save                                                                   |
| autoLearn     | false; only counts stable-final frequencies, never auto-adds words                                  |
| windowDays    | 30; integer 1–90                                                                                    |
| minFrequency  | 3; integer 2–100; compatibility statistics parameter, no frequency recommendations in current pages |
| maxWords      | 100; integer 1–2000; per-round selection cap                                                        |
| manualTerms   | Up to 2000 text/weight entries; integer weight 1–5, default 4                                       |
| excludedTerms | Up to 2000 excluded word strings                                                                    |

Terms use NFKC and collapsed whitespace, length 2–64, allowing letters/numbers/spaces and `. + # - / _ '`, but not symbol-only entries. Personal duplicates are case-insensitive. Exclusions take precedence; deleted terms are not automatically restored.

### 8.2 PATCH /v1/hotwords

```json
{
  "revision": 0,
  "settings": { "enabled": true, "manualTerms": [{ "text": "neural network", "weight": 4 }] }
}
```

Partial settings updates are allowed; arrays replace in full. Supply the latest integer revision. Another same-key device's save makes stale edits return 409 `HOTWORDS_CONFLICT`; refresh/reconcile. Success returns complete latest personal data. Changes affect future sessions only, never active snapshots.

learnedTerms provides text/frequency/lastSeen/excluded. Learning counts deduplicated stable finals after enablement, never full audio/transcripts or partials. `DELETE /v1/hotwords/statistics` returns `{"ok":true}`, clearing frequencies while retaining personal/excluded lists and deduplication IDs. GET again to refresh.

### 8.3 Public catalog, download, and selection

`GET /v1/hotwords/catalog`:

```json
{
  "formats": ["auto", "text", "tsv", "csv", "json", "rime"],
  "maxBytes": 4194304,
  "maxWords": 50000,
  "maxDictionaries": 8,
  "recommendationOnly": true,
  "sources": [
    {
      "id": "tech-ai",
      "title": "AI starter dictionary",
      "description": "Domain terms",
      "license": "Project-maintained term list",
      "homepage": "",
      "format": "text",
      "url": "",
      "kind": "portal-public",
      "revision": 1,
      "wordCount": 40,
      "downloadPath": "/v1/hotwords/catalog/tech-ai"
    }
  ]
}
```

portal-public is administrator-published persistent content; external is a built-in online-source entry. Counts/names/IDs vary and must remain refreshable. Not every source has identical summary fields.

`GET /v1/hotwords/catalog/{sourceId}` returns complete format/words/report/source/recommendationOnly. words contain text/weight/frequency/position. source records origin/sha256 and, for Portal public tables, current revision. report includes rows/wordCount/skipped/duplicates/warnings/sample (up to 20). Unpublished/deleted tables return 404 `PUBLIC_DICTIONARY_NOT_FOUND`; online sources may return 502.

Compatible download through `POST /v1/hotwords/dictionaries`:

```json
{ "sourceId": "tech-ai", "preview": true }
```

This also returns all words without changing personal settings, saving a snapshot, or increasing revision. Show candidates, let the user add/edit/remove individual terms locally, then PATCH on explicit save. **Downloading a table does not enable it. Public updates/deletions do not change selected personal terms; only the saved personal table feeds recognition.**

### 8.4 File previews and personal recommendation snapshots

```json
{ "preview": true, "format": "text", "content": "neural network|4\nmedical imaging|3\n" }
```

POST dictionaries previews TXT/TSV/CSV/JSON/RIME, up to 4 MiB / 50000 valid terms. It never executes RIME configuration or expands import_tables, and does not analyze PDFs/articles for keywords.

Omit preview and supply revision/title to save a **personal recommendation snapshot**: 201 with importedDictionaryId/importReport, up to 8 per key. GET dictionaries/{id} retrieves all words. PATCH uses `{"revision":n,"patch":{"title":"New name"}}`; DELETE uses `{"revision":n}`. Writes also increment the key's personal revision. Compatible enabled remains accepted but does not select recognition words. Deleting a snapshot leaves selected personal words intact. Other keys' snapshots return 404.

### 8.5 Upstream limits

- Doubao bidirectional streaming currently allows 100 tokens; Portal conservatively budgets UTF-8 bytes, not 100 words. Terms over 9 characters, numbers, or unsupported symbols are filtered; generic weight is not sent.
- Current Bailian models accept up to 2000 immediate terms. Non-ASCII terms allow 15 characters; ASCII phrases allow up to 7 space-separated segments.
- Current LocalASR has no session hotword input: supported=false, though personal lists remain manageable.
- omitted.reason: disabled, unsupported, count-limit, term-format, token-budget. Display the reason; do not edit global model vocabularies or bypass upstream limits.

## 9. HTTP errors and recovery

Unified business-error body:

```json
{
  "error": { "code": "AUTH_FAILED", "message": "Portal 接入凭据无效", "requestId": "diagnostic-id" }
}
```

The example message means “invalid Portal access credentials.” Branch on code, not localized message text.

| HTTP | Common code                                                            | Client handling                                              |
| ---- | ---------------------------------------------------------------------- | ------------------------------------------------------------ |
| 400  | INVALID_REQUEST / INVALID_PROFILE / UNSUPPORTED_AUDIO                  | Fix JSON/ID/audio; do not repeat unchanged invalid requests  |
| 401  | AUTH_FAILED / TICKET_EXPIRED                                           | Check key; create a new session for expired connections      |
| 402  | QUOTA_EXHAUSTED                                                        | Stop recognition; ask administrator for budget               |
| 403  | AUTH_FAILED                                                            | Key cannot cancel this existing session                      |
| 404  | PROFILE_NOT_FOUND / DICTIONARY_NOT_FOUND / PUBLIC_DICTIONARY_NOT_FOUND | Refresh profiles/catalog while preserving unsaved edits      |
| 409  | SESSION_STARTED                                                        | Do not establish another WS for the same recording           |
| 409  | HOTWORDS_CONFLICT                                                      | Refresh and reconcile another device's edits                 |
| 409  | PROFILE_DISABLED / TOKEN_USAGE_UNSUPPORTED / TOKEN_USAGE_UNAVAILABLE   | Change selection or request administrator action             |
| 429  | UPSTREAM_BUSY                                                          | Portal capacity exhausted; create a session later            |
| 502  | DICTIONARY_DOWNLOAD_FAILED                                             | Online download failed; manually download and preview a file |
| 503  | NO_UPSTREAM_AVAILABLE                                                  | All default candidates unavailable; wait for recovery        |

WS errors use session.error, including AUDIO_LIMIT, SESSION_TIMEOUT, FINALIZATION_TIMEOUT, UPSTREAM_CLOSED, CLIENT_DISCONNECTED, and UPSTREAM_ERROR; some parse/upstream exceptions collapse to UPSTREAM_ERROR. Stop capture/upload, clear this round's preedit, and retain unconfirmed text. New recordings use new generation/sessionId/ticket. requestId aids diagnosis.

## 10. Minimal sequence and HTTP examples

1. GET capabilities to verify v1/audio; GET profiles to choose explicit/default.
2. Acquire a local target lease and create clientRequestId.
3. POST sessions; validate sessionId, streamPath, and TTL.
4. Connect same-origin WS/WSS; receive/validate ready.
5. Capture PCM; upload/receive concurrently; replace partial preedit and deduplicate final commits.
6. Stop/flush recording, send audio.end, and keep awaiting terminal events.
7. Check finalCount on finished; clean up socket/bridge preedit.
8. Cancellation/failure/focus loss cleans only this round. New targets/recordings require new sessions.

```bash
# ASR_KEY is the administrator-issued client key; PORTAL is your service origin.
PORTAL=http://127.0.0.1:10087
curl -H "Authorization: Bearer $ASR_KEY" "$PORTAL/v1/capabilities"
curl -H "Authorization: Bearer $ASR_KEY" "$PORTAL/v1/profiles"
curl -X POST -H "Authorization: Bearer $ASR_KEY" -H 'Content-Type: application/json' \
  -d '{"purpose":"dictation","audio":{"encoding":"pcm_s16le","sampleRate":16000,"channels":1}}' \
  "$PORTAL/v1/sessions"
curl -H "Authorization: Bearer $ASR_KEY" "$PORTAL/v1/hotwords/catalog"
curl -H "Authorization: Bearer $ASR_KEY" "$PORTAL/v1/hotwords/catalog/tech-ai"
```

The last example assumes tech-ai still exists and is published; read the catalog first. Public integration does not import Portal Python. Input's own adapters/portal.py, domain/ledger.py, and application/controller.py demonstrate clients. See [testing](testing.md) for source regressions, Input black-box contracts, and real two-page dictionary tests.

## 11. Personal-list files and recommendation formats

Input/Portal export this JSON and also accept a terms array:

```json
{
  "format": "OpenASRPortal.PersonalHotwords",
  "version": 1,
  "terms": [
    { "text": "机器学习", "weight": 4, "enabled": true },
    { "text": "Node.js", "weight": 3, "enabled": false }
  ]
}
```

The file contains no key, connection, or master switch; it exports current edits. Import merges with NFKC/case-insensitive matching, taking imported weights/states for duplicates. Invalid terms, duplicates within the file, files over 4 MiB, or merged lists over 2000 terms reject the whole import. Save afterward; online manualTerms/excludedTerms represent complete/disabled entries.

Public/recommendation parsers accept UTF-8 with optional BOM: TXT one term per line or `term|weight`; TSV term/frequency or RIME term/code/frequency; CSV text/frequency/weight; JSON string arrays, term-object arrays, vocabulary objects, or term-to-weight maps; RIME default columns/columns metadata. Frequency sorts only, not ASR weight; default weight is 4. Technical symbols still face upstream constraints.

RIME never executes Lua/YAML object tags/import_tables or reads binary databases/.bin/.scel. Reports retain reference warnings; obtain actual text files yourself. Limits: 4 MiB / 50000 terms per file, 8 personal snapshots. Full recommendations do not consume the personal 2000-term allowance until selected.

## 12. Optional frequency learning and provider mapping

autoLearn counts only deduplicated stable finals after enablement, excluding partials, duplicate finals, and admin silence probes. Already-emitted finals still count after later cancellation. Jieba filters single characters, pure numbers, and common stopwords; English is lowercased. No entity recognition or automatic proper-noun correction. Storage retains terms, UTC daily counts, last-seen times, and deduplication IDs, never full transcripts/audio.

windowDays includes the current UTC day, up to 90 days. Each key retains at most 5000 distinct terms/day; queries show the top 2000, evicting by frequency/recency. Disabling learning keeps history; statistics failures do not interrupt recognition. Clearing statistics preserves the personal list/deduplication IDs. Learning/recommendations never auto-merge into personal terms.

Doubao bidirectional streaming sends serialized `{"hotwords":[{"word":"麒麟"}]}` through request.corpus.context, not the 5000-term nostream interface. The conservative UTF-8 approximation is neither an exact tokenizer nor 100 words; generic weights are omitted. Bailian qwen-audio-3.1-asr-flash sends a term-to-1–5-weight map through parameters.vocabulary, sharing one snapshot for previews/finalization without creating persistent vocabularies. LocalASR currently sends no hotword parameters.

Provider references: [Doubao streaming](https://www.volcengine.com/docs/6561/1354869), [hotword specification](https://docs.volcengine.com/docs/DoubaoVoice/Hotwords?lang=zh), [Bailian hotwords](https://help.aliyun.com/zh/model-studio/improve-asr-accuracy). Real enhancement needs real accounts/audio; simulated payload checks do not establish recognition quality.
