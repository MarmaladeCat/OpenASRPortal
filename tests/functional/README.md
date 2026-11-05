# OpenASRPortal functional tests

**English** | [简体中文](README.zh-CN.md)

[manifest.json](manifest.json) defines scenarios/expectations/commands; [requirements.txt](requirements.txt) pins protocol/management dependencies. Tests use no production upstream keys.

- service-lifecycle: real subprocess setup, ASR key/profile creation, restart persistence, normal exit, port conflicts.
- admin-login: real browser/independent service setup, confirmation, login, password-field clearing, logout.
- profile-management: real profile/key/quota UI operations and key isolation; simulated upstream.

From this repository, Python 3.10+:

```bash
python scripts/test.py setup --suite core
python scripts/test.py run --suite core
python scripts/test.py setup --suite ui
python scripts/test.py run --suite ui
```

The entry prepares an independent venv with src/tests search paths. UI uses Electron 44.4.5; the runner sets OPENASRPORTAL_TEST_PYTHON and automatically uses Linux Xvfb. The host needs Xvfb/browser system libraries.

All databases/credentials use temporary test-results/ directories, independent ports, and self-cleaning processes. Environments/downloads go to ignored .cache/. ARM64 runs core; Windows runs core/ui. Real cloud recognition and MSI service install/upgrade/uninstall need separate [acceptance](../../docs/testing.md). See [development](../../docs/development.md) for build preparation.
