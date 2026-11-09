# OpenASRPortal

**English** | [简体中文](README.zh-CN.md)

**1.1.1** · Unified ASR gateway with HTTP/WebSocket v1, sessions, upstream profiles, client keys, hotwords, quotas, and a management UI. Connect cloud services or OpenLocalASR upstream.

## Documentation

For system-wide dictation, use [OpenASRInput](https://github.com/MarmaladeCat/OpenASRInput). Its [downloads](https://github.com/MarmaladeCat/OpenASRInput/releases) are also the distribution point for Input + Portal combined installers. See [installation lifecycle and language selection](docs/installation.md).

- **Deploy and operate:** [Windows / Linux user guide](docs/user-guide.md).
- **Cloud API setup:** [Doubao Speech](docs/doubao-api-setup.md), [Bailian streaming](docs/bailian-api-setup.md), [Soniox real-time STT](docs/soniox-api-setup.md), and [Boson AI Higgs STT](docs/boson-api-setup.md): activate services, create keys, and connect them to Portal.
- **Local recognition:** [Connect OpenLocalASR](docs/localasr-setup.md): prepare the active model, service key, network address, and Portal upstream card.
- **Client development:** [recognition and personal hotwords API v1](docs/API.md).
- **Management tools:** [management protocol v1](docs/MANAGEMENT.md), including authentication, public dictionaries, and metering.
- **Implementation:** [architecture](docs/architecture.md).
- **Source and delivery:** [development/releases](docs/development.md).
- **Acceptance:** [testing requirements](docs/testing.md).
- **Changes:** [1.1.1 release notes](docs/release.md).

Source requires Python 3.10+, without Node.js, Electron, or local models. Native packages include private Python. Default listening is loopback-only; first open `/admin`, set a management password, then derive client keys.

This repository owns dependencies, configuration, and `portal.db`; it never reads other product databases. English/Chinese docs are manually maintained; reviewed demonstration captures may enter source, but real data/credentials may not.

## License

Copyright (C) 2026 OpenASRPortal contributors.

Original code/docs use **GNU GPL v3 (`GPL-3.0-only`)**, allowing use, modification, and redistribution, including commercial use, under its terms, without warranty. See [LICENSE](LICENSE). Third-party components retain their own copyrights/licenses. Provide matching source/build instructions when distributing packages as required by the license.
