# OpenASRPortal 1.2.0 release notes

**English** | [简体中文](release.zh-CN.md)

Product/package versions are 1.2.0; client and management protocols remain v1. Docs are English-first with Chinese counterparts. Platform acceptance is recorded per candidate, separately from these capability notes.

## Capabilities

- Typed upstream results now publish an immutable audio-ordered prefix and a replaceable preview tail, including interleaved second-pass results. Upload drain and recognition use separate deadlines; actual commit/body write completion starts the recognition budget.
- Independent [OpenAI file JSON/SSE and Realtime](openai-api-setup.md) profiles, plus complete-recording LocalASR HTTP. [Capabilities and effective limits](recognition-contract.md) distinguish live preview from text after stopping. File requests are submitted once; source PCM, request/item token reports, duration and unknown usage have separate accounting semantics.

- Independent control reading keeps cancellation responsive during initialization, upload and final sending. Bounded upload queues, coordinated ready deadlines, classified non-retryable authentication/configuration failures, and real-time Doubao pacing cover buffered speech. Finalization starts after upstream audio submission.

- Upstream panels with inline read-only/edit modes, enable/proxy switches and local test results; proxy availability/latency testing; language dropdowns and page reload icon. New Soniox profiles use `zh,en` hints for mostly Chinese with occasional English; hint order does not assign weights.

- Global HTTP/HTTPS proxy settings with encrypted optional authentication and per-upstream opt-in, shared by probes and recognition; no silent direct fallback.

- Genuine Bailian duplex streaming with `qwen-audio-3.1-asr-flash-streaming`; stored HTTP-profile migration and cumulative token accounting. Repeated HTTP previews and their interval setting are removed.
- Soniox `stt-rt-v6` real-time STT with stable/provisional token handling, semantic endpoints, context hotwords, cancellation and audio-duration quotas. See [setup and billing semantics](soniox-api-setup.md).

- Boson AI Higgs STT: full live audio upload, one manual commit at recording end, language hints and duration quotas. Local silence cutting and forced 15-second segmentation are removed. See [setup and limitations](boson-api-setup.md).

- Soniox endpoint detection defaults off; new Doubao profiles disable second-pass VAD and use a 300–5000 ms silence range (default 5000). Legacy out-of-range Doubao values migrate to the nearest boundary while valid values and second-pass switches are retained. Bailian independently keeps its 200–6000 ms range and new-profile default of 6000. Upstream models still decide punctuation.
- v1 adds explicit version/features, creation-parameter conflict detection, cancellation during finalization, and single-terminal/pending-preview checks. A [standalone Python client](python-client.md) demonstrates third-party integration.
- Recording and provider finalization have separate deadlines. Boson large-frame uploads yield between transport chunks while retaining bounded backlog. Doubao terminal packets cannot promote non-definite text; Soniox completion accepts withdrawn provisional tails and commits only stable text, including empty finals where needed.

- HTTP session creation, single-use WS tickets, unified partial/final/end/cancel events.
- Database passwords, short admin sessions, multiple client ASR keys, revocation, encrypted reveal.
- Cloud/LocalASR profiles, default selection, quotas, ordered fallback.
- Personal hotwords, public recommendations, revision conflict protection, actual usage metering.
- Standalone management UI; Linux local, Docker, and Windows service deployments.

## Downloads and documentation

[OpenASRInput](https://github.com/MarmaladeCat/OpenASRInput) provides system-wide voice input through Portal. Combined packages are intended for the [Input release page](https://github.com/MarmaladeCat/OpenASRInput/releases). Each installer has its own `filename.sha256`, with exactly one checksum record.

The 1.2.0 packages include Bailian/Soniox streaming, Boson AI Higgs STT, per-upstream proxy selection, unified directories, retained-data reinstallation, setup-on-demand, and Chinese/English switching. See [installation.md](installation.md).

Packages use `OpenASRPortal_1.2.0_<os>_<architecture>.<extension>`: Linux `.deb` for the service or `.tar.gz` for Docker deployment, and Windows `.msi`. Choose amd64/arm64 appropriately. Standalone installation does not configure recording clients.

GitHub Release attachments contain only packages and their individual `.sha256` files. Read the [user guide](user-guide.md), [client API](API.md), and [management API](MANAGEMENT.md) online. Local build directories retain documentation archives, manifest.json, and SHA256SUMS. Docker deployment packages contain the image and deployment materials; execute deployment commands from their flat layout.

## Upgrades and compatibility

Back up all data, including portal.db/asr-key-vault.key. Migrations preserve profiles, ASR keys/revocations, hotwords, quotas, and usage. Admin passwords are not imported from old environment variables; initialize locally if no admin exists. Legacy environment-only ASR keys must be rederived.

Default is loopback-only. Health proves liveness, not a working upstream. LocalASR lacks session hotwords; missing tokens are not zero usage. Accept installation, upgrade, uninstall, remote HTTPS, and real cloud recognition separately.
