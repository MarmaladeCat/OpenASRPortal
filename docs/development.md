# OpenASRPortal development and releases

**English** | [简体中文](development.zh-CN.md)

Source uses Python 3.10+, aiohttp, and product-owned SQLite, without Electron/model runtimes. Install browser test tools separately. See [client API](API.md) and [management API](MANAGEMENT.md).

## Local development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m openasrportal --data-dir runtime/portal --host 127.0.0.1 --port 10087
```

Windows uses `py -3.12 -m venv .venv` and `.venv\Scripts\python.exe` with the same module command. Open `/admin` for initial password setup. Use isolated data, never deployed databases. Configure host/port/data through `OPENASRPORTAL_HOST/PORT/DATA`. Database management owns credentials; old credential environment variables no longer work.

## Iteration and verification

```bash
python scripts/test.py setup --suite unit
python scripts/test.py run --suite unit --allow-skips
python scripts/test.py setup --suite core
python scripts/test.py run --suite core
```

Add UI for web changes; adapter changes cover revisions, metering, end/cancel, and real upstreams. Follow [testing](testing.md); skips are not complete acceptance. Use this repository's Ruff and existing JS/CSS styles.

## Pinned builds

```bash
python scripts/build.py --deployment local --arch amd64
python scripts/build.py --deployment docker --arch amd64
# Linux ARM64: --arch arm64; Windows: isolated guest
python scripts/build.py --deployment windows --arch amd64 --wix-bin <WiX-directory>
```

debs use Ubuntu 22.04 / PyInstaller 6.16.0; images use Python 3.12.10 / Debian 12. MSI orchestration uses native Windows Python 3.12.10 and WiX 3.14.1; bundled private Python is 3.13.16, service wrapper WinSW 2.12.0. packaging/ recipes call build_portable_deb.py, build_image.py, or build_windows.py without workspace source dependencies.

Candidates: `.cache/build/artifacts/<os>/<arch>/<variant>/`. Publish to `release/1.0.0/`; VERSION/package metadata are 1.0.0. Flat output contains debs, image bundles, MSI, bilingual docs ZIP/READMEs, manifest.json, SHA256SUMS. Docker bundles contain real image.tar and authored deployment instructions, never dist/ output.

Publication verifies provenance, unique candidates, version, architecture, and hashes before replacement; matching-source other-platform artifacts merge. Building is not service installation/upgrade/uninstallation or real-recognition acceptance. Store records in test-results/.

## Deployment maintenance boundaries

Migrations preserve profiles, keys, revocations, hotwords, and usage. Back up the whole data directory, including asr-key-vault.key. Offline recovery: `python -m openasrportal.entrypoints.admin --data-dir <actual-directory>`, with interactive password entry only, never plaintext CLI arguments.

Standalone installation does not configure Input. Windows combined MSI connects only through public product-owner entry points and ACL-protected handoff files, not shared databases. Legacy pairing remains for v1 compatibility; see management API.

## Documentation and Git

For a docs-only preview, create `test-results/`, then run `python scripts/release.py --docs test-results/product-docs.zip`. All authored Markdown, images, and linked attachments retain their original bytes and relative paths. Flat releases include `release.md` / `release.zh-CN.md` beside identical README copies to keep language links valid.

Manually maintain both languages for operations, client/management protocols, architecture, development, tests, and release notes. Release READMEs copy the corresponding docs/release files verbatim; archives retain directories/screenshots. Reports/manifests/hashes are evidence, not authored instructions.

Commit source, templates, locks, recipes, tests, selected captures, and current docs; ignore real configuration/databases/keys/logs, raw captures, environments, VMs, and packages. Retain third-party licenses. Push product commits before workspace gitlinks, with maintainer review.
