# Connect Boson AI Higgs STT to Portal

**English** | [简体中文](boson-api-setup.zh-CN.md)

Portal uses Boson's Higgs Realtime WebSocket with `higgs-stt-3.1` input transcription. All audio uploads during recording; the complete round is committed at `audio.end`. The API returns completed input transcripts, not word-by-word partials.

## Account and configuration

1. Sign in at [Boson workspace](https://www.boson.ai/workspace), complete account verification, then open [API Keys](https://www.boson.ai/workspace/api-key) and select **Create API Key**. Copy the complete `bai-…` key when shown. Follow [account setup](https://docs.boson.ai/set-up-your-account) for current requirements. Claim any eligible trial credit explicitly on the API Keys or billing page; creating an account/key alone does not add credit. Otherwise fund the account and verify model access.
2. Open Portal `/admin`, sign in, and choose **Upstream ASR → Add service connection**.
3. Select **Boson AI · Higgs STT**, give the profile a unique ID/name, and enter the key without a `Bearer` prefix.
4. Keep the read-only endpoint `wss://api.boson.ai/v1/realtime` and transcription model `higgs-stt-3.1`. The adapter sets the underlying session model to `higgs-realtime` automatically.
5. Use `auto` for automatic Chinese/English recognition, or one ISO-639-1 hint such as `zh` or `en`. Do not enter `en,zh`: this adapter accepts one hint, unlike Soniox. Boson may ignore unrecognized language hints. There is no local silence setting; legacy `silenceMs` is ignored and removed on save.
6. Choose **Use proxy** before testing. If enabled, first save and test the global HTTP/HTTPS proxy in **Settings**; it must be reachable from the Portal backend. Existing cards require **Edit** to change fields. The upstream test uses the current unsaved form and proxy switch, reports inside the panel, commits 200 ms of silence and waits for a transcription response. It consumes a small amount of usage and checks model access, not just the socket handshake. Select **Save** after success; **Cancel** discards edits.
7. Set the profile as default or select it explicitly in a client. Clients still use a Portal-issued ASR key.

Leave the saved card **Enabled**. The page-language dropdown does not change the recognition language. Verify Chinese and English phrases with thinking pauses, then stop recording to receive the complete result. Proxy availability and recognition connection tests have different scopes; an unavailable enabled proxy never falls back to a direct connection.

## Recognition behavior

- Portal sends all 16 kHz mono PCM16 samples as base64 chunks, including silence and quiet speech. There is no local energy threshold, silence cutting or 15-second forced boundary. Chunking is transport framing, not sentence segmentation.
- Large client frames within the public WS limit are split with uploader scheduling between chunks. The 15-second pending-audio bound applies to actual upstream backlog; a healthy upload burst does not consume it all before the uploader can run. A stalled connection fails explicitly and remains cancellable.
- Completed segments produce stable finals. No speculative previews or hotword hints: public capabilities report `partialResults: false` and `latencyClass: segmented`.
- Manual turns (`turn_detection: null`) avoid automatic assistant replies. Portal never sends `response.create` or treats assistant output as recognition text. Boson currently does not support OpenAI transcription-only sessions; changing only an OpenAI URL is insufficient.
- Only `audio.end` (or the accepted-audio quota limit) commits the round. A stalled finalization fails explicitly. Cancellation closes the connection without committing another turn. After the recording budget, Portal allows 75 seconds to drain and actually write the commit, then 35 seconds for recognition. The advertised `finalizeTimeoutMs` is 111000 ms, including a one-second margin; consume the session snapshot rather than hard-coding it.
- Portal duration quotas count accepted client audio, including silence. The cloud bill remains authoritative. Portal counts one streaming request per session and never infers tokens from duration. Use duration quotas, not token quotas.

## Troubleshooting and references

For authentication/model errors, check the key, model permissions, balance, and backend network access to Boson. No text until recording stops is expected. A successful connection test does not establish microphone accuracy or native input acceptance.

`429 insufficient_quota` can mean the trial credit has not been claimed or the balance is empty; check [billing](https://www.boson.ai/workspace/billing/overview). A rate-limit error instead requires checking concurrency/request limits. `401` calls for checking the complete key without a `Bearer` prefix. For proxy timeout/CONNECT errors, check the configured proxy from the Portal host before changing model settings.

Latency has separate stages: connection/session setup, recording until the user stops, and commit-to-final transcription. `audio.end` flushes and commits immediately; thinking pauses do not trigger a commit. The model still decides punctuation within the completed transcript. This does not guarantee that a pause can never be interpreted as a sentence boundary by the model.

At INFO log level, `Boson timing` records a random session correlation ID, `ready_ms`, audio boundaries, `commit_ack_ms`, `final_after_commit_ms`, and queued audio duration, without keys, transcripts or audio. A quick commit with a slow final points to the upstream/network path. These measurements cannot separate server queuing from model inference. Compare the same public audio with a direct manual-turn session; connection-test latency alone is not speech latency.

- [Connections and sessions](https://docs.boson.ai/models/higgs-realtime/guides/connections-and-sessions)
- [Compatibility differences](https://docs.boson.ai/models/higgs-realtime/migrate-an-existing-integration)
- [Client events](https://docs.boson.ai/api-reference/realtime/client-events)
- [Server events and transcription usage](https://docs.boson.ai/api-reference/realtime/server-events)
- [Pricing](https://docs.boson.ai/pricing)
