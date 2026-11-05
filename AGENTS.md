# OpenASRPortal development requirements

**English** | [简体中文](AGENTS.zh-CN.md)

Inspect Git status, then README.md, docs/development.md, docs/testing.md, and docs/release.md before editing.
Repository/layout changes must not regress functionality/performance. Keep the product independently runnable, testable, buildable, and releasable.
Never import other products' source, share databases, or borrow Python/Node runtimes. Cross-product communication uses public protocols.
Behavioral changes require relevant unit, business, UI, native, and package checks; docs/testing.md governs acceptance.
Skips, failures, and inadequate environments are not passes. Simulation does not replace real model/device/platform acceptance.
Maintain current docs/ manually in English (default) and linked Chinese *.zh-CN.md. scripts/build.py uses pinned environments; candidates go to .cache/build/artifacts/, final flat packages/checksums to `release/<VERSION>/`, never product dist/.
Test output goes to test-results/; tools/container/VM state to .cache/. Commit neither.
Do not carry old Git history, development logs, update status, personal paths, internal hosts, or real keys. Record normal new-project commits.
Commit/push this product before updating workspace gitlinks. Never force-push/rewrite shared new-project commits.
