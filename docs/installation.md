# Persistent installation and language selection

**English** | [简体中文](installation.zh-CN.md)

These behaviors apply to Portal 1.2.0 and the combined Input 1.2.0 + Portal 1.2.0 installers.

## Install with Input

[OpenASRInput](https://github.com/MarmaladeCat/OpenASRInput) captures audio and delivers text to applications; Portal connects it to recognition providers. The [Input release page](https://github.com/MarmaladeCat/OpenASRInput/releases) is the intended location for combined Windows x64 MSI and single Linux amd64/ARM64 DEB installers. APT manages both applications as `openasrinput-portal`, replacing standalone packages while retaining data. See the [combined installation guide](https://github.com/MarmaladeCat/OpenASRInput/blob/main/docs/installation.md). Standalone Portal packages remain available from [Portal releases](https://github.com/MarmaladeCat/OpenASRPortal/releases).

Each package has its own `filename.sha256`, containing only that package's checksum. A combined installer configures a dedicated local Input ASR key through the public product provisioning commands. Administrator passwords and upstream provider keys are separate.

## Directory and lifecycle

Windows stores service configuration at `%ProgramData%\OpenASR\portal\service.json` and default data in its `data\` subdirectory. Linux uses `/var/lib/OpenASR/portal/service.env` and `/var/lib/OpenASR/portal/data/`. Standalone, combined, foreground and source launches share the default data location. `OPENASR_DATA_ROOT` relocates the common namespace; `OPENASRPORTAL_DATA` or `--data-dir` explicitly overrides this product's database directory. Input uses sibling `input/<SID-or-UID>` directories. Only Portal opens its database.

On upgrade, old default `%ProgramData%\OpenASRPortal`, `/var/lib/openasr/portal`, `/etc/openasrportal/service.env`, and `/var/lib/openasrportal` configurations migrate while Portal is stopped. Custom data paths are retained. Keep legacy backups until verified. Compose now binds the standard host data directory; existing named volumes require an explicit retained mount or an offline copy of the complete data directory. For old source/XDG deployments, stop Portal and copy the whole old directory, including its vault key, into the new `portal/data` before first launch; existing destinations must not be merged or overwritten.

Linux installation grants the configured data directory a narrow systemd sandbox exception in `/etc/systemd/system/openasrportal.service.d/20-data-directory.conf`. If you change `OPENASRPORTAL_DATA` later, stop the service and run `sudo dpkg-reconfigure openasrportal` to refresh that exception. Existing custom data files must remain accessible to the `openasrportal` service account.

For a combined DEB use `sudo dpkg-reconfigure openasrinput-portal` instead. Package installation does not open a browser; after graphical/root installation, use **OpenASR Input + Portal Setup** from the application menu or `sudo openasrinput-portal-setup --user ACCOUNT --no-open` to connect that account. Sudo installation connects its invoking account automatically.

Fresh Windows interactive installation or the Linux setup launcher opens `/admin/setup` if live authentication status says no administrator is configured. Set a password of at least 12 characters, then add an upstream. Upgrades and retained-data reinstallations preserve the administrator, client keys, profiles, hotwords, and quotas. An unfinished first setup continues after reinstall. Windows uses `OPENASRPORTAL_NO_LAUNCH=1` or `/qn` to suppress automatic opening; the Linux setup launcher accepts `--no-open`. On a headless service open the actual local management URL manually. The standalone Linux package prints that URL and tries to open setup when it can identify the invoking sudo user's graphical session.

Uninstall retains configuration by default. Windows explicit data deletion also removes recognized legacy backups; Linux data deletion is a separate administrator operation. Back up the entire actual data directory, including `portal.db` and `asr-key-vault.key`, before deleting anything.

### Retiring old Portal directories

Once the new service's actual `service.json` / `service.env` and data path are verified, its profiles/keys/hotwords are present, and old services are stopped, the old defaults can be removed: Windows `%ProgramData%\OpenASRPortal`; Linux `/var/lib/openasr/portal`, `/etc/openasrportal/service.env`, and `/var/lib/openasrportal`. Remove the rest of `/etc/openasrportal` only after checking its contents and service references. Explicit custom data paths, old source/XDG directories, and Docker volumes remain active when a command, service configuration, or mount still selects them.

For fresh-install acceptance, use an empty data root and empty legacy locations before first startup; retaining old defaults can trigger migration. Current `/var/lib/OpenASR/portal` and `%ProgramData%\OpenASR\portal` contain live data. Keep the database and vault key together. Never remove the entire shared OpenASR root for a Portal-only cleanup.

## Explicit Linux data removal

After stopping and uninstalling Portal, remove and purge retain data. Delete only Portal with `sudo rm -rf -- /var/lib/OpenASR/portal`; this removes its configuration, credentials, hotwords and usage. Inspect retained legacy directories, custom paths and old Docker volumes separately. The common root contains other products and must not be removed for a Portal-only cleanup.

## Interface language

The upper-right **中文 / English** buttons work on setup, login, and all administration sections. The initial language follows the browser/system; the browser remembers Portal's choice independently of Input. Switching does not submit or reset forms. User names, dictionary contents, provider IDs, endpoints, and credentials retain their original values.
