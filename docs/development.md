# OpenASRPortal development and releases

**English** | [简体中文](development.zh-CN.md)

Source uses Python 3.10+, aiohttp, and product-owned SQLite, without Electron/model runtimes. Install browser test tools separately. See [client API](API.md) and [management API](MANAGEMENT.md).

## Local development

See [installation lifecycle](installation.md) for current-source directories and migration. `openasrportal --provision-local-input --installed --client-id ID --output FILE` is an installation-owner command; stop the service and protect its output for the recipient. `openasrportal --open-setup --url-file FILE` uses public authentication status before opening a browser. The bundle composer obtains current provenance with `python scripts/release.py --source-digest`. Translation catalogs are owned by this product; UI tests cover setup and administration in both languages without losing drafts or translating user data.

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

Preserve `.cache/build/portable/<arch>/` and the toolchain images between builds. Frozen-runtime reuse verifies code/assets, recipe/version, immutable image ID, Python/CPU and every payload hash/mode; documentation-only changes still repackage with fresh source provenance. A changed input or damaged cache triggers refreezing. Windows retains a hash-checked resolved wheelhouse in `.cache/windows/wheels/`, keyed by requirements and target Python/architecture, and installs offline with `--no-index`. Keep Python/WinSW downloads and the universal jieba wheel; delete a wheelhouse explicitly only when refreshing dependencies. Temporary package staging is disposable; database/model directories are not build caches.

Public package filenames are `OpenASRPortal_<version>_<os>_<architecture>.<extension>`, including Docker `.tar.gz` packages. GitHub Release attachments contain only packages and their exact `.sha256` companions; authored notes and documentation links go in the release body. Local release directories retain documentation and provenance records.

```bash
python scripts/build.py --deployment local --arch amd64
python scripts/build.py --deployment docker --arch amd64
# Linux ARM64: --arch arm64; Windows: isolated guest
python scripts/build.py --deployment windows --arch amd64 --wix-bin <WiX-directory>
```

debs use Ubuntu 22.04 / SHA256-pinned Python 3.12.10 / PyInstaller 6.16.0; images use Python 3.12.10 / Debian 12. The private DEB interpreter enables HTTPS proxy TLS-in-TLS while retaining the Ubuntu 22.04 libc baseline. Source installations need Python 3.11+ for HTTPS proxies. MSI orchestration uses native Windows Python 3.12.10 and WiX 3.14.1; bundled private Python is 3.13.16, service wrapper WinSW 2.12.0. packaging/ recipes call build_portable_deb.py, build_image.py, or build_windows.py without workspace source dependencies.

Candidates: `.cache/build/artifacts/<os>/<arch>/<variant>/`. Publish to `release/1.1.1/`; VERSION/package metadata are 1.1.1. Flat output contains debs, image bundles, MSI, bilingual docs ZIP/READMEs, manifest.json, SHA256SUMS. Docker bundles contain real image.tar and authored deployment instructions, never dist/ output.

Publication verifies provenance, unique candidates, version, architecture, and hashes before replacement; matching-source other-platform artifacts merge. Building is not service installation/upgrade/uninstallation or real-recognition acceptance. Store records in test-results/.

## Deployment maintenance boundaries

Migrations preserve profiles, keys, revocations, hotwords, and usage. Back up the whole data directory, including asr-key-vault.key. Offline recovery: `python -m openasrportal.entrypoints.admin --data-dir <actual-directory>`, with interactive password entry only, never plaintext CLI arguments.

Stored Bailian HTTP profiles are normalized on read into the streaming model and WSS path, then persisted on save. Never reintroduce HTTP preview requests. Streaming usage is cumulative per task, not per event; keep historical database reservation columns compatible without using them for new streams. Soniox final tokens accumulate once and provisional tokens replace a suffix; endpoint/final completion must not duplicate text. Provider-specific tests and bilingual configuration contracts accompany protocol changes.

Standalone installation does not configure Input. Windows combined MSI connects only through public product-owner entry points and ACL-protected handoff files, not shared databases. Legacy pairing remains for v1 compatibility; see management API.

## Documentation and Git

For a docs-only preview, create `test-results/`, then run `python scripts/release.py --docs test-results/product-docs.zip`. All authored Markdown, images, and linked attachments retain their original bytes and relative paths. Flat releases include `release.md` / `release.zh-CN.md` beside identical README copies to keep language links valid.

Manually maintain both languages for operations, client/management protocols, architecture, development, tests, and release notes. Release READMEs copy the corresponding docs/release files verbatim; archives retain directories/screenshots. Reports/manifests/hashes are evidence, not authored instructions.

Commit source, templates, locks, recipes, tests, selected captures, and current docs; ignore real configuration/databases/keys/logs, raw captures, environments, VMs, and packages. Retain third-party licenses. Push product commits before workspace gitlinks, with maintainer review.
