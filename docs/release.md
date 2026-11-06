# OpenASRPortal 1.0.1 release notes

**English** | [简体中文](release.zh-CN.md)

Product/package versions are 1.0.1; client and management protocols remain v1. Docs are English-first with Chinese counterparts. Platform acceptance is recorded per candidate, separately from these capability notes.

## Capabilities

- HTTP session creation, single-use WS tickets, unified partial/final/end/cancel events.
- Database passwords, short admin sessions, multiple client ASR keys, revocation, encrypted reveal.
- Cloud/LocalASR profiles, default selection, quotas, ordered fallback.
- Personal hotwords, public recommendations, revision conflict protection, actual usage metering.
- Standalone management UI; Linux local, Docker, and Windows service deployments.

## Downloads and documentation

[OpenASRInput](https://github.com/MarmaladeCat/OpenASRInput) provides system-wide voice input through Portal. Combined packages are intended for the [Input release page](https://github.com/MarmaladeCat/OpenASRInput/releases). Each installer has its own `filename.sha256`, with exactly one checksum record.

The 1.0.1 candidates add unified directories, retained-data reinstallation, setup-on-demand, and Chinese/English switching. See [installation.md](installation.md); candidates are pending maintainer review and manual testing before publication.

Linux deb: `*_local-service.deb`; image bundle: `*_docker.tar.gz`; Windows: `*_native.msi`. Choose amd64/arm64 appropriately. Standalone installation does not configure recording clients.

`OpenASRPortal_1.0.1_docs.zip` contains complete bilingual authored docs. Start at README.md; operations are in docs/user-guide.md, client API in docs/API.md, management in docs/MANAGEMENT.md. Archives also retain LICENSE, deployment notes, Compose/NGINX templates, and certificate scripts at source-relative paths. Execute deployment commands from the Docker bundle's flat layout. Verify manifest.json/SHA256SUMS.

## Upgrades and compatibility

Back up all data, including portal.db/asr-key-vault.key. Migrations preserve profiles, ASR keys/revocations, hotwords, quotas, and usage. Admin passwords are not imported from old environment variables; initialize locally if no admin exists. Legacy environment-only ASR keys must be rederived.

Default is loopback-only. Health proves liveness, not a working upstream. LocalASR lacks session hotwords; missing tokens are not zero usage. Accept installation, upgrade, uninstall, remote HTTPS, and real cloud recognition separately.
