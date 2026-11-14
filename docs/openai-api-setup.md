# OpenAI transcription setup

**English** | [简体中文](openai-api-setup.zh-CN.md)

Create an API key with transcription model access in the [OpenAI platform](https://platform.openai.com/api-keys), then add one of these explicit upstream types in Portal. Keep the key in Portal, never in Input. Enable the existing global proxy option if required by your deployment.

- **OpenAI · Complete recording** (`openai_file`): `gpt-transcribe`, `https://api.openai.com/v1/audio/transcriptions`. JSON returns the complete text; SSE displays revisions while processing the already-recorded file. Both upload once after stopping. Neither previews live microphone audio.
- **OpenAI · Realtime transcription** (`openai_realtime`): `wss://api.openai.com/v1/realtime?intent=transcription`. `gpt-live-transcribe` previews during capture; `gpt-transcribe` begins transcription after commit. Both use one manual turn per Input round, with VAD disabled.

Optional comma-separated expected languages and a context prompt are model hints, not guaranteed output. Portal caps prompts at 4096 characters. Personal hotwords become unweighted keywords, capped locally at 100 terms/4096 UTF-8 bytes; `<`, `>`, CR and LF are forbidden in keywords. Leave language hints empty for automatic detection. Delay (`minimal` through `xhigh`) is optional and only applies to the live model; it is not a guaranteed millisecond value.

Realtime waits for the effective `session.updated` before ready, converts source 16 kHz PCM continuously to 24 kHz with SoXR, preserves pre-commit deltas, and matches completion to the committed item. Final text replaces the candidate. There are no fabricated word timestamps, speaker labels or confidence scores. File audio remains 16 kHz WAV. Portal's five-minute limit is below the service's 25 MB file limit.

Cancellation closes this round's I/O. It does not call conversation-response cancellation or promise that committed ASR is unbilled. Tokens and duration reports are separate; choose duration quotas if your account/workflow does not return token usage. Missing usage is not zero.

The build/runtime dependencies include numpy and SoXR; 16 kHz providers do not load them. Verify the conversion library in each actual Linux amd64/arm64 and Windows candidate. A source installation without the required component fails before ready.

Connection tests submit a short silent request and may incur usage. Real acceptance additionally requires public speech, live pre-stop text for the live model, complete final replacement, stopping/cancellation latency, and actual usage. Follow [testing](testing.md); simulated protocol fixtures do not establish cloud availability or transcription quality.

References: [file transcription](https://developers.openai.com/api/docs/guides/speech-to-text), [Realtime transcription](https://developers.openai.com/api/docs/guides/realtime-transcription), [transcription overview](https://developers.openai.com/api/docs/guides/transcription). Current profiles use `gpt-transcribe` / `gpt-live-transcribe`, not the older models scheduled for shutdown on 2027-02-26.
