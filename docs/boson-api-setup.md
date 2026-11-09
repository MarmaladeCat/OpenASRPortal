# Connect Boson AI Higgs STT to Portal

**English** | [简体中文](boson-api-setup.zh-CN.md)

Portal uses Boson's Higgs Realtime WebSocket with `higgs-stt-3.1` input transcription. Audio uploads during recording; text arrives after a segment is committed. The API currently returns completed input transcripts, not word-by-word partials.

## Account and configuration

1. Follow Boson's [account setup](https://docs.boson.ai/set-up-your-account) to create an API key and enable sufficient credit/model access.
2. Open Portal `/admin`, sign in, and choose **Upstream ASR → Add service connection**.
3. Select **Boson AI · Higgs STT**, give the profile a unique ID/name, and enter the key without a `Bearer` prefix.
4. Keep the read-only endpoint `wss://api.boson.ai/v1/realtime` and transcription model `higgs-stt-3.1`. The adapter sets the underlying session model to `higgs-realtime` automatically.
5. Use `auto` for language detection, or an ISO-639-1 hint such as `zh` or `en`. Boson may ignore unrecognized language hints. Set segmentation silence to 600–3000 ms (default 800 ms).
6. Test the upstream connection, then save. The test commits 200 ms of silence and waits for a transcription response, consuming a small amount of usage. It verifies model access rather than just the socket handshake.
7. Set the profile as default or select it explicitly in a client. Clients still use a Portal-issued ASR key.

## Recognition behavior

- Portal sends 16 kHz mono PCM16 as base64 chunks. Local energy-based segmentation submits on a pause, at 15 seconds of continuous audio, or at recording end. Low-level background silence is discarded, with up to 200 ms of pre-roll retained. Very quiet speech and background noise can affect boundaries; adjust microphone level and silence settings as needed.
- Completed segments produce stable finals. No speculative previews or hotword hints: public capabilities report `partialResults: false` and `latencyClass: segmented`.
- Manual turns (`turn_detection: null`) avoid automatic assistant replies. Portal never sends `response.create` or treats assistant output as recognition text. Boson currently does not support OpenAI transcription-only sessions; changing only an OpenAI URL is insufficient.
- The next segment waits for the preceding transcript because Boson can supersede an unfinished transcription with a newer turn. A stalled request fails rather than silently losing a segment. Cancellation closes the connection without committing buffered speech.
- Portal duration quotas count accepted client audio, including silence. Upstream billed duration can differ after silence filtering; the cloud bill is authoritative. Portal counts one streaming request per session, not one per commit, and never infers tokens from duration. Use duration quotas, not token quotas.

## Troubleshooting and references

For authentication/model errors, check the key, model permissions, balance, and backend network access to Boson. No text until a pause is expected; continuous speech is forcibly segmented at 15 seconds. A successful connection test does not establish microphone accuracy or native input acceptance.

Latency has separate stages: connection/session setup, waiting for a speech boundary, and commit-to-final transcription. The 800 ms default silence boundary adds to upstream time while recording; `audio.end` commits immediately after any pending turn. There are no word-by-word previews. Background noise above the local energy threshold can keep a turn open until the 15-second limit; check microphone level/noise before reducing silence (minimum 600 ms). A slow pending transcript also holds subsequent audio uploads to prevent lost turns.

At INFO log level, `Boson timing` records a random session correlation ID, `ready_ms`, segment audio boundaries, `commit_ack_ms`, `final_after_commit_ms`, and queued audio duration. It records no key, transcript, or audio. A late commit points to segmentation/backlog; a quick commit with a slow final points to the upstream/network path. These client-side measurements cannot separate server queuing from model inference. Compare against the same public audio through a direct manual-turn session; connection-test latency alone is not speech latency.

- [Connections and sessions](https://docs.boson.ai/models/higgs-realtime/guides/connections-and-sessions)
- [Compatibility differences](https://docs.boson.ai/models/higgs-realtime/migrate-an-existing-integration)
- [Client events](https://docs.boson.ai/api-reference/realtime/client-events)
- [Server events and transcription usage](https://docs.boson.ai/api-reference/realtime/server-events)
- [Pricing](https://docs.boson.ai/pricing)
