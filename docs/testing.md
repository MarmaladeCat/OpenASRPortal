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

Crash recovery starts with a new data root and loopback-only file upstream. Kill the real service process before file submission and while awaiting its response, restart with the same newly created data, and verify persisted authentication/profiles/usage, rejection of old tickets, no automatic audio replay, and one successful new request. Abrupt client TCP loss must release file-cache admission without charging an unsubmitted request. These checks exercise SIGKILL / TerminateProcess, not physical power failure or storage durability. Fresh installation uses empty current and legacy data locations; retention fixtures are created within the run.

Typed-result tests cover interleaved A-preview/B-final/A-final, duplicate identities/revisions, identical text at different audio positions, conflicting stable text, unresolved empty units, and full preview withdrawal. Session tests block real write/commit/body drain independently of recognition completion, exercise cancel/timeout races and ready-before-audio, and check source-sample quotas and cleanup.

File and OpenAI fixtures cover one complete PCM/WAV request after end, cache admission, zero audio, pre-submit cancellation, quota-end submission, JSON/SSE full-text replacement and truncated streams, UTF-8/line framing, pre-commit Realtime deltas, predecessor ordering, and request/item usage deduplication. NumPy/SoXR checks use different chunk boundaries, explicit PCM16 rounding and one final flush. UI covers both OpenAI forms, short limits, timing labels and duration/unknown usage in both languages. These are synthetic checks; real cloud tests require public speech, temporary credentials, actual event timings/usage and each target's packaged conversion libraries.

Boundary regressions cover Doubao's 300–5000 ms configuration/migration and non-definite terminal packets, Soniox stable-prefix/all-provisional withdrawal at endpoints and completion, Boson legal large frames versus a genuinely stalled bounded queue, and separate recording/finalization deadlines. Verify explicit and quota-triggered end, cancellation after the recording deadline, and exactly one terminal event. Profile UI checks validate provider-specific ranges and retained drafts in both languages.

Proxy checks use disposable HTTP and HTTPS CONNECT proxies and a locally trusted WSS echo/protocol server. Cover binary/text/empty-text frames, separate proxy/upstream authentication, explicit direct routing, no fallback, rejected authentication, timeout/cancellation cleanup, encrypted persistence, admin-only redaction, public probe/recognition routing, and bilingual profile/settings UI. These simulated endpoints verify transport, not cloud recognition. Re-run the transport tests in the packaged runtime as well as the development interpreter.

Bailian and Soniox use simulated WebSocket wire tests for partials before audio end, stable/deduplicated finals, server errors, completion markers, raw PCM, and bounded state. Public v1 checks cover quota truncation, probes, cancellation/timeout, cumulative token accounting and limited-account serialization; migration keeps old keys/regions/quotas. UI checks cover streaming model fields, removal of preview intervals, Soniox settings and both languages. These tests do not establish cloud recognition or latency. Real acceptance needs provider credentials, public Chinese/English audio, pre-stop partials, end-to-final timing, and actual usage records under test-results/; installer/native acceptance remains platform-specific.

Boson adapter checks use a simulated WebSocket for manual-turn initialization, ordered/deduplicated finals, empty audio, errors/disconnects, bounded backlog, cancellation during pending transcription, public v1 finalization, duration quotas, and probe metering. Profile UI checks cover Boson fields, language switching, and retained keys. For real-cloud acceptance, provide a temporary Boson key outside the checkout, replay public 16 kHz PCM speech including two separated turns, and retain audio hashes, event timing/finalCount, and usage under test-results/. Keep silence probes, real recognition, microphone input, and installer checks distinct.

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

In an isolated network namespace or VM, run `python tests/check_packaged_asr.py --runtime <extracted-runtime> --results test-results/<new-run>`. On Windows, pass the extracted private `python.exe` and add `--python-runtime`. The check owns loopback proxy port 7890, trusts a disposable fixture certificate only in the child, and exercises packaged SoXR conversion/flush plus file JSON/SSE through public APIs. Its upstream is simulated; it needs no real credential or Internet access and is separate from installer acceptance.

## Results

Bailian wire fixtures must use normal sentence IDs starting at 1 and heartbeat ID 0. Cover interleaved sentences, an empty terminal payload after a stable cumulative token report, a missing last report, and interruption after partial usage. Real token-limited acceptance must reconcile debits with captured supplier reports.

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
