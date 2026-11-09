# Persistent installation and language selection

**English** | [简体中文](installation.zh-CN.md)

These behaviors apply to Portal 1.1.1 and the combined Input 1.1.1 + Portal 1.1.1 installers.

## Install with Input

[OpenASRInput](https://github.com/MarmaladeCat/OpenASRInput) captures audio and delivers text to applications; Portal connects it to recognition providers. The [Input release page](https://github.com/MarmaladeCat/OpenASRInput/releases) is the intended location for combined Windows x64 MSI and single Linux amd64/ARM64 DEB installers. APT manages both applications as `openasrinput-portal`, replacing standalone packages while retaining data. See the [combined installation guide](https://github.com/MarmaladeCat/OpenASRInput/blob/main/docs/installation.md). Standalone Portal packages remain available from [Portal releases](https://github.com/MarmaladeCat/OpenASRPortal/releases).

Each package has its own `filename.sha256`, containing only that package's checksum. A combined installer configures a dedicated local Input ASR key through the public product provisioning commands. Administrator passwords and upstream provider keys are separate.

## Directory and lifecycle

Windows stores service configuration at `%ProgramData%\OpenASR\Portal\service.json` and default data in its `data\` subdirectory. Linux uses `/var/lib/openasr/portal/service.env` and `/var/lib/openasr/portal/data/`. Input uses sibling `Input/<SID>` or `input/<uid>` directories with user-private permissions. Only Portal opens its database.

On upgrade, old default `%ProgramData%\OpenASRPortal`, `/etc/openasrportal/service.env`, and `/var/lib/openasrportal` configurations migrate while Portal is stopped. A configured custom data directory is retained. Keep legacy backups until the new installation is verified. Docker volumes and source-mode `--data-dir` remain explicit deployment choices.

Linux installation grants the configured data directory a narrow systemd sandbox exception in `/etc/systemd/system/openasrportal.service.d/20-data-directory.conf`. If you change `OPENASRPORTAL_DATA` later, stop the service and run `sudo dpkg-reconfigure openasrportal` to refresh that exception. Existing custom data files must remain accessible to the `openasrportal` service account.

For a combined DEB use `sudo dpkg-reconfigure openasrinput-portal` instead. Package installation does not open a browser; after graphical/root installation, use **OpenASR Input + Portal Setup** from the application menu or `sudo openasrinput-portal-setup --user ACCOUNT --no-open` to connect that account. Sudo installation connects its invoking account automatically.

Fresh Windows interactive installation or the Linux setup launcher opens `/admin/setup` if live authentication status says no administrator is configured. Set a password of at least 12 characters, then add an upstream. Upgrades and retained-data reinstallations preserve the administrator, client keys, profiles, hotwords, and quotas. An unfinished first setup continues after reinstall. Windows uses `OPENASRPORTAL_NO_LAUNCH=1` or `/qn` to suppress automatic opening; the Linux setup launcher accepts `--no-open`. On a headless service open the actual local management URL manually. The standalone Linux package prints that URL and tries to open setup when it can identify the invoking sudo user's graphical session.

Uninstall retains configuration by default. Windows explicit data deletion also removes recognized legacy backups; Linux data deletion is a separate administrator operation. Back up the entire actual data directory, including `portal.db` and `asr-key-vault.key`, before deleting anything.

## Interface language

The upper-right **中文 / English** buttons work on setup, login, and all administration sections. The initial language follows the browser/system; the browser remembers Portal's choice independently of Input. Switching does not submit or reset forms. User names, dictionary contents, provider IDs, endpoints, and credentials retain their original values.
