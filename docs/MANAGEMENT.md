# OpenASRPortal.Management v1

**English** | [简体中文](MANAGEMENT.zh-CN.md)

The public management protocol shared by the web UI, OpenNotes, and OpenDrafts, not a shared code package. HTTP JSON requests use `Authorization: Bearer <management-session-token>`, never the plaintext password. Setup/login are below. Passwords/keys are database-managed, not credential environment variables. Reads are sanitized; upstream keys stay in Portal.

## Endpoints

| Method    | Path                            | Semantics                                                      |
| --------- | ------------------------------- | -------------------------------------------------------------- |
| GET       | /v1/admin/contract              | protocol/version/providers form and field contract             |
| GET       | /v1/admin/profiles              | All profiles, defaultProfileId, managementVersion              |
| POST      | /v1/admin/profiles              | Add profile; duplicate id is 409                               |
| GET       | /v1/admin/profiles/{id}         | Read profile                                                   |
| PATCH     | /v1/admin/profiles/{id}         | Update; missing is 404                                         |
| PUT       | /v1/admin/profiles/{id}         | Idempotent save by id for deployment registration              |
| DELETE    | /v1/admin/profiles/{id}         | Idempotent deletion                                            |
| POST      | /v1/admin/profiles/{id}/test    | Test saved profile or body draft without persistence           |
| GET/PATCH | /v1/admin/settings              | Read/set defaultProfileId                                      |
| GET/POST  | /v1/admin/asr-keys              | Sanitized list / derive named ASR key                          |
| DELETE    | /v1/admin/asr-keys/{id}         | Permanently revoke key and cancel its sessions                 |
| GET       | /v1/admin/asr-keys/{id}/secret  | Admin-only on-demand reveal of decryptable client key          |
| POST      | /v1/admin/asr-keys/{id}/recover | Restore reveal for a legacy hash using matching original value |
| GET       | /v1/admin/usage                 | Duration/token/request statistics by key/upstream and time     |
| PATCH     | /v1/admin/asr-keys/{id}/quota   | Set downstream remaining seconds/tokens                        |
| PATCH     | /v1/admin/profiles/{id}/quota   | Set upstream balances/enabled state                            |

Create/update body:

```json
{
  "id": "my-asr",
  "title": "My recognition service",
  "provider": "openlocalasr",
  "configuration": {
    "endpoint": "ws://127.0.0.1:10095/api-ws/v1/inference",
    "model": "funasr_sensevoice_small",
    "apiKey": "server-key-placeholder"
  }
}
```

id is immutable, up to 100 characters, allowing letters/digits/underscore/hyphen/dot. Provider and endpoint need not be unique: accounts at one endpoint use separate IDs, keys, and quotas. New profiles require explicit apiKey, never inherited. Omitting apiKey on update retains the same provider's key; changing provider does not reuse it. configuration.hasApiKey reports stored status without plaintext.

## Descriptive contract

GET contract returns:

```json
{
  "protocol": "OpenASRPortal.Management",
  "version": 1,
  "providers": [
    {
      "id": "openlocalasr",
      "title": "OpenLocalASR · Local speech recognition",
      "fields": [
        {
          "key": "model",
          "label": "Current server model",
          "type": "text",
          "required": true,
          "default": "funasr_sensevoice_small"
        }
      ]
    }
  ]
}
```

Types: text / secret / boolean / number / select. Supported metadata: default, required, readOnly, min/max/step, options, valueType=number, retainWhenOmitted. Consumers render the contract instead of copying Portal's provider validation/default code. Descriptive labels may be localized.

## Defaults and sessions

The first profile becomes default. settings can explicitly update the default and `profileOrder`. Omitted client profileId uses default; explicit selection pins that profile. Deleting/disabling/exhausting the default selects the next available profile in order, or none. Edits/deletion never rewrite active provider snapshots; quotas use current state at subsequent submission. See Usage and quotas for missing token reports.

## Standalone web UI

### Database authentication and legacy pairing compatibility (v1)

- `GET /v1/admin/auth/status`: public initialized/passwordMinLength; before initialization, a ten-minute setupChallenge.
- `POST /v1/admin/auth/setup`: `{password,confirmPassword,setupChallenge,pairingCode?}`; one-shot transaction. 201 returns token/expiresInMs/localInputApproved. Already configured is 409, never password overwrite.
- `POST /v1/admin/auth/login`: `{password}`; 200 token/expiresInMs; wrong password 401, throttled 429, uninitialized 409.
- `POST /v1/admin/auth/logout`: management session; revoke current token.
- `POST /v1/local-input/pairings`: native loopback clients only; `{clientId}` (32 hex characters). 201 id/claimToken/userCode/expiresAt/approvalPath/setupRequired.
- `GET /v1/admin/local-input-pairings?code=...`: management session; pairing code, expiry, approved/delivered, never private claim credentials or ASR key.
- `POST /v1/admin/local-input-pairings`: management session; `{code}` explicitly authorizes local-input key. Initial setup may confirm pairingCode too.
- `POST /v1/local-input/pairings/{id}/claim`: native loopback only; `{claimToken}` returns pending or approved/key/keyId/title.
- `POST /v1/local-input/pairings/{id}/ack`: acknowledge only after durable client key storage; claim credentials immediately expire.

Setup/login require application/json and same-origin browser requests. Setup challenges bind caller and Host; forwarded proxy headers do not establish loopback. Pairings expire in ten minutes; old pairings cannot reclaim revoked keys. All auth responses are no-store. See [user guide](user-guide.md) for installation/password recovery.

Native desktop consumers use this HTTP protocol through their main process. Store token/expiresInMs in memory per Portal origin, logout explicitly, and relogin after expiry. Never persist admin passwords or treat short tokens as static keys. Browser requests must be same-origin; Origin:null and other origins are rejected. Electron renderers must not directly make cross-origin management requests. Main-process IPC restricts callers and allowed operations, never arbitrary URL proxying or disabled server origin checks. Legacy pairing remains for old clients; new standalone clients use configured ASR keys, and Windows combined installation uses explicit product entry points.

GET /admin serves UI/same-origin assets. Users log in with the password. An authenticated launcher can POST /v1/admin/ui-tickets for a single-use 60-second ticket. The page exchanges a fragment ticket at /v1/admin/ui-session for a short management token, then immediately removes the fragment. It authorizes management, not recognition. Static resources contain no runtime keys.

## Multiple ASR keys

Only valid short management tokens authorize this protocol; old static admin keys no longer work. POST asr-keys with `{"title":"Local input method"}` returns id/title/prefix/createdAt/revoked and one-time `key`. Input, Drafts, and other devices store their own ASR keys. Multiple keys are supported; none grants management.

GET lists contain no full key/digest; canReveal indicates reveal capability. Authentication still uses SHA-256 digests. For admin reveal/copy, originals are Fernet-authenticated encrypted, with vault key data/asr-key-vault.key, permissions 0600. `/secret` accepts only management sessions and is no-store.

recover uses `{"key":"known-original"}` and must match the specified ID's digest; it cannot replace another key or restore revoked status. Unknown legacy originals cannot be recovered from hashes: derive replacements. Missing vault files give KEY_UNAVAILABLE, never silent key replacement. Back up the vault with the database.

DELETE revocation is irreversible and cleans only this key's connected/pending sessions. Other keys are unaffected. Credential tables use backward-compatible incremental SQLite migrations without changing profiles/upstream keys.

## Management categories

Public Hotword Tables supports multiple-table CRUD, file/online import, preview, publication, and JSON download. `/v1/admin/hotwords/public-dictionaries` is exposed by contract.publicDictionariesPath; independent revisions are below.

Manage User Hotwords on each downstream card operates one personal table per key: add, weight, enable/disable, delete, personal JSON import/export, and individual public-candidate selection. Administrators import/publish TXT/TSV/CSV/JSON/RIME under Public Hotword Tables. Only saved personal terms feed recognition. Admin and client Settings share owner/storage/revision.

Sidebar categories: Service Overview, Upstream ASR, Downstream Clients, Usage and Statistics, Public Hotword Tables, Access and Permissions. Forms, cards, and a bottom status bar are consistent. Upstream manages provider keys/endpoints/models; downstream manages derived client keys. Reveal, copy, and hide are explicit actions; navigation/logout clears revealed values.

Errors use `{error:{code,message,requestId}}`, never unstructured log strings.

## Admin-managed personal lists

Admins need not reveal a key: its digest locates the same owner. These management-session routes use [client API](API.md) fields, term validation, personal JSON, snapshots, and revision semantics.

| Operation                  | Management path                                                       |
| -------------------------- | --------------------------------------------------------------------- |
| GET/PATCH settings         | `/v1/admin/asr-keys/{id}/hotwords`                                    |
| DELETE frequencies         | `/v1/admin/asr-keys/{id}/hotwords/statistics`                         |
| POST preview/save snapshot | `/v1/admin/asr-keys/{id}/hotwords/dictionaries`                       |
| GET/PATCH/DELETE snapshot  | `/v1/admin/asr-keys/{id}/hotwords/dictionaries/{dictionary_id}`       |
| GET catalog/content        | `/v1/admin/hotwords/catalog`, `/v1/admin/hotwords/catalog/{sourceId}` |

Clients/admins edit the same personal table. Stale revision returns 409, never force-overwrite. Snapshot enabled is compatibility metadata, not recognition selection. Public tables use the separate API below.

## Public hotword tables

Collection `/v1/admin/hotwords/public-dictionaries`: GET returns `{dictionaries:[summaries],maxTables:100}`; POST creates/imports. `/{id}` supports GET complete, PATCH update, DELETE. Each public revision is independent of every key's personal revision.

POST example:

```json
{
  "title": "Medical imaging",
  "description": "Domain terms",
  "homepage": "https://example.org/terms",
  "license": "Original term list",
  "enabled": true,
  "format": "text",
  "content": "medical imaging|4\nneural network|3\n"
}
```

title length 1–100; description ≤2000; license ≤500; homepage ≤1000 and empty or HTTP(S). enabled is boolean, default true. Empty content creates an empty table. See client API for formats. Limits: 4 MiB / 50000 terms/table, 100 tables. Success 201 generates public-... ID and revision 1.

`{sourceId:"thuocl-it",preview:true}` downloads/parses a fixed source without storage, returning format/words/report/source/recommendationOnly. content/sourceId are mutually exclusive; arbitrary URLs are rejected. Without preview, import creates a table and may inherit omitted metadata from the source.

PATCH example: `{"revision":1,"title":"New edition","format":"text","content":"medical imaging|5\n","enabled":false}`. Metadata-only changes retain content/source hash; format changes require content. Success returns the complete table with incremented revision. DELETE `{"revision":2}` → `{ok:true}`. Missing: 404 PUBLIC_DICTIONARY_NOT_FOUND; conflict: 409 PUBLIC_DICTIONARY_CONFLICT.

Summaries contain id/revision/title/description/license/homepage/enabled/format/wordCount/createdAt/updatedAt/source/sha256. Full tables add words/report. Words contain text/weight/frequency/position; timestamps are Unix seconds; sha256 covers the last imported/edited UTF-8 body. Reports contain valid/skipped/duplicate counts, warnings, and up to 20 examples.

AI/computing/programming starter tables are seeded only at initialization as tech-ai/tech-computing/tech-programming. Restart never overwrites edits or revives deletions. Unpublishing/deleting does not change selected personal terms/snapshots. external entries are download links, not periodic overwrites of persistent public tables.

Sources include [THUOCL](https://github.com/thunlp/THUOCL), [Rime Ice](https://github.com/iDvel/rime-ice), and [Rime Wanxiang](https://github.com/amzxyz/rime-wanxiang). Preserve actual file origin/license; RIME frequency is not ASR weight. PDFs/scans/articles need external extraction/OCR/tokenization and manual selection. This API provides neither document analysis nor those tools.

## Usage and quotas

PATCH `/v1/admin/asr-keys/{id}/quota` or `/v1/admin/profiles/{id}/quota` accepts `{"remainingSeconds":900,"remainingTokens":null}`; upstreams also accept enabled. Values are replacement balances, not increments. null means unlimited, 0 exhausted, omitted unchanged; cumulative totals persist. Either exhausted dimension blocks future calls.

Admin quota contains remainingSeconds, remainingTokens, reservedSeconds, availableSeconds, usedSeconds, reportedTokens, tokens, requests, tokenReports, unreportedRequests, enabled, disabledReason, tokenBlocked, exhausted, priority. Without token reports, tokens is null, not 0.

`GET /v1/admin/usage` accepts from/to (Unix seconds or ISO 8601), bucket=hour/day/month, keyId, profileId, timezone (IANA, e.g. Asia/Shanghai). Defaults: last seven days, UTC. Returns total/timeline/keys/profiles/trackingStartedAt/resolutionSeconds. Ordinary `/v1/profiles` shows availability, not balances/totals.

Duration meters actual submitted PCM at 32000 bytes/second, not connection wait. Debit complete samples atomically; truncate at balance boundaries and finalize normally. Unconnected/expired tickets consume no audio; failure/cancellation retain actual usage. Streaming upstreams meter sent audio. Bailian HTTP meters every preview/final request, so upstream duration may exceed downstream. HTTP reserves final-audio quota, skips previews if insufficient, releases reservations for VAD-discarded silence, and releases unused reservations on cleanup.

Admin tests meter upstream only; unsaved drafts use `draft:provider:id`. Audio history is minute-compressed; queries expand to full minutes while debit remains sample-based. Portal is not a provider billing/cloud-balance service.

Tokens use actual upstream usage total_tokens or input_tokens/output_tokens, prompt_tokens/completion_tokens, deduplicated per request, never estimated from text length. Real HTTP preview tokens count too. Missing reports display unreported; partial reporting shows real totals plus unreported request counts. Doubao/LocalASR currently lack token metering and reject token-limited selection. Bailian depends on model reporting; a missing report under a token limit sets tokenBlocked and stops future calls.

Tokens settle after completion, so the last call may exceed remaining balance: all actual usage is recorded, balance becomes zero. HTTP admission is serialized within limited scopes. Lowering a balance cannot undo executed calls. Remove token limits/use duration, or confirm restored upstream reporting and reset budget to clear the pause.

Exhausted/missing-required-report upstreams disable automatically. Default selection cycles forward through order; if none is usable, clear it and return NO_UPSTREAM_AVAILABLE. Replenishing auto-exhausted profiles can restore them; manual disables need explicit enablement. Explicitly clearing default is respected when budgets are replenished. profileOrder must contain all profiles exactly once and can update atomically with defaultProfileId. Switching affects new sessions, never splices active recordings.

Usage/balances persist transactionally. Restart releases stale reservations, marks interrupted requests, and pauses token-limited accounts without reports. Deleted profiles/revoked keys retain history. Usage before tracking began is not reconstructed.

## Installation initialization and migration

Initial passwords require at least 12 characters and salted scrypt hashes. Admin sessions default to 30 minutes and revoke on logout. Listen on loopback by default; initialize locally before exposing remote access. Installation never resets an existing password.

With normal user authorization and Portal selected, Windows combined MSI invokes Portal's owner entry to allocate/reuse local-input for the installing user's SID, then hands it to Input's own configuration entry through an ACL-protected file. Keys never enter MSI properties/command lines. Repeated handoff generations do not overwrite later user-selected connections; revoked keys never revive. Standalone/remote installations remain user-configured.

Migrations preserve business data. Old OPENASRPORTAL_ADMIN_KEY/API_KEY are no longer imported. deb removes old credential lines from service.env; Windows clears old apiKey/adminKey from service.json while retaining other runtime parameters. Docker creates no legacy credential JSON. Keys that existed only in old environment variables must be rederived. Password recovery requires the actual existing database directory, revokes management sessions, and preserves ASR keys/business data.
