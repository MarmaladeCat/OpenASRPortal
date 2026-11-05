# OpenASRPortal testing requirements

**English** | [简体中文](testing.zh-CN.md)

Development/release acceptance follows this document and the [executable manifest](../tests/functional/manifest.json). Tests must run from this repository alone, without parent/other-product source or interpreters.

## Repository-local entry points

Python 3.10+; browser regression tools use Node.js 22.13+/Electron, not service runtime dependencies. Linux UI uses Xvfb; Windows uses an isolated interactive desktop.

```bash
python scripts/test.py list --suite core
python scripts/test.py setup --suite unit
python scripts/test.py run --suite unit --allow-skips
python scripts/test.py setup --suite core
python scripts/test.py run --suite core
python scripts/test.py setup --suite ui
python scripts/test.py run --suite ui
```

setup creates Python tests in `.cache/functional/`, product desktop dependencies in node_modules/, browser tools in `.cache/test-lab/ui/`. The app uses its own runtime. Every run creates fresh test-results/functional/ reports/logs. `--case <ID>` selects one check, never whole-product acceptance.

## Required coverage

| Layer                  | Checks                                                                                                                 |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| unit/core              | Setup/auth/logout, profile/key isolation, HTTP/WS v1, revision/final/cancel, quota/usage, hotwords/restart persistence |
| UI                     | Real setup/login/logout, profile CRUD/key retention; simulated upstream                                                |
| Native/install/service | Docker health/auth/volume recreation; deb/MSI install/upgrade/uninstall; separate temporary keys for real upstreams    |
| Performance            | Creation/WS-ready latency, first/final word, concurrent throughput, error rate, CPU/RSS                                |

After building the matching candidate:

```bash
python tests/check_container.py --image openasrportal:test
```

## Results

- Failures return nonzero; missing environments/dependencies/devices are blocked, not passed.
- unittest skips produce incomplete and normally nonzero. Daily `--allow-skips` permits a successful exit, not complete platform acceptance.
- Simulation/synthetic audio proves business/protocol behavior only, not real recognition/microphones/native input.
- Accept each OS, CPU, desktop/input framework, and installation form separately; do not copy another platform's pass.
- Recheck source/candidate consistency after source/locks/resources change; historical reports cannot replace current evidence.
- Use temporary HOME/ports/configuration/databases and fictional keys, never production data or desktop/input-method restarts.

## Performance

Fix machine/OS/interpreter/dependencies, input/resource hashes, CPU threads, and service settings. Warm up, then interleave at least five baseline/candidate runs each. Retain raw samples, median/p95, error rate, peak memory. Functionality/accuracy must hold too. Median regression >10% or p95 >15% blocks no-regression claims pending investigation; noisy/insufficient samples remain unconfirmed. Whole-core duration is not operation latency or ASR RTF. Store baselines/reports/samples in test-results/, not old release state in source.

## Environment ownership

Commit reproducible Dockerfiles/Compose templates/scripts/locks. Keep container exports/layers, VM disks/ISOs/snapshots, secrets, audio, and reports in .cache/ or test-results/. Clean only this run's processes/containers/volumes; isolate shared-VM instances from production data.

## Screenshot provenance

`docs/images/linux-admin.png`: 1.0 source service, Linux amd64/Chrome. `windows-admin.png`: service extracted from 1.0.0 MSI, Windows 11 amd64/Edge. Each uses fresh data, loopback ports, and browser profiles; real management API initialization creates a “local recognition (demo configuration)” profile before capturing Upstream ASR. These are capture-source versions.

Temporary demonstration keys remain hidden. No cloud recognition or LocalASR connection test ran. Images illustrate profile/default/balance controls, not installation, real recognition, or quota-metering acceptance. Raw scripts/logs/databases stay in test-results/; publish only reviewed captures.
