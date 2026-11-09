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

Packages use `OpenASRPortal_1.0.1_<os>_<architecture>.<extension>`: Linux `.deb` for the service or `.tar.gz` for Docker deployment, and Windows `.msi`. Choose amd64/arm64 appropriately. Standalone installation does not configure recording clients.

GitHub Release attachments contain only packages and their individual `.sha256` files. Read the [user guide](user-guide.md), [client API](API.md), and [management API](MANAGEMENT.md) online. Local build directories retain documentation archives, manifest.json, and SHA256SUMS. Docker deployment packages contain the image and deployment materials; execute deployment commands from their flat layout.

## Upgrades and compatibility

Back up all data, including portal.db/asr-key-vault.key. Migrations preserve profiles, ASR keys/revocations, hotwords, quotas, and usage. Admin passwords are not imported from old environment variables; initialize locally if no admin exists. Legacy environment-only ASR keys must be rederived.

Default is loopback-only. Health proves liveness, not a working upstream. LocalASR lacks session hotwords; missing tokens are not zero usage. Accept installation, upgrade, uninstall, remote HTTPS, and real cloud recognition separately.
