# Connect Soniox real-time STT

**English** | [简体中文](soniox-api-setup.zh-CN.md)

Create an API key in the [Soniox console](https://console.soniox.com/) and enable credit/model access. In Portal **Upstream ASR → Add service connection**, choose **Soniox · Real-time speech recognition**, enter a unique profile ID/name and the key without a Bearer prefix, then test and save.

- Provider ID: `soniox_realtime`; model: `stt-rt-v6`.
- Endpoint: `wss://stt-rt.soniox.com/transcribe-websocket` (read-only).
- Language: new profiles default to English and Chinese (`en,zh`). Choose automatic detection or a language in the dropdown; the API also accepts up to ten comma-separated two-letter hints. Saved selections are retained. Hints do not restrict recognition to those languages.
- Maximum endpoint delay: 500–3000 ms, default 2000. This caps semantic endpoint waiting after speech, not network or total response latency.

Portal authenticates with a Bearer header during the WebSocket handshake, sends configuration followed by raw 16 kHz mono PCM16, and forwards real partial text. Stable tokens accumulate once; provisional tokens replace the current suffix. An `<end>` marker finalizes a segment. End-of-audio sends an empty text frame and waits for `finished: true`; final tokens are flushed once. Cancellation closes the stream without inventing a final transcript. Idle connections send keepalive messages; errors and finish timeouts remain errors.

Personal hotwords use `context.terms`, without numerical weights. Portal conservatively limits selected context to 7000 UTF-8 bytes, below Soniox's 8000-token context limit. Only the selected terms are sent.

Portal provides local **submitted-audio duration** quotas; Soniox bills **stream duration**, including idle time kept alive. These figures are different and Portal's quota is not a cloud spending cap. Soniox text tokens are recognition pieces, not billable token-usage reports: token quotas are unavailable. Connection tests send 200 ms silence and wait for completion, consuming real upstream usage; success is not a recognition-accuracy or microphone test.

Check key access/credit and backend connectivity if probing fails. New streams require access to the configured model. For acceptance, replay public Chinese and English audio and verify partials before stopping, stable finals without duplicate words, cancellation, and measured tail latency. Keep keys outside source control.

Official references: [WebSocket API](https://soniox.com/docs/api-reference/stt/websocket-api), [transcription](https://soniox.com/docs/stt/rt/real-time-transcription), [endpoint detection](https://soniox.com/docs/stt/rt/endpoint-detection), [context](https://soniox.com/docs/stt/concepts/context).
