# OpenASRPortal standalone container deployment

**English** | [简体中文](README.zh-CN.md)

This bundle provides a Portal image and two independent Compose configurations. Match image.json OS/CPU to your Docker host. Windows/macOS Docker Desktop uses matching Linux containers. The image contains neither clients, LocalASR, nor models.

Commands use the Compose plugin; for standalone Compose v2, replace `docker compose` with `docker-compose`.

## Local HTTP

In the unpacked bundle directory:

```bash
docker load -i image.tar
cp .env.example .env
# Linux: container UID 10001 must be able to write data.
mkdir -p data
sudo chown 10001:10001 data
docker compose up -d
docker compose logs portal
```

Open `http://127.0.0.1:10087/admin`, set a password of at least 12 characters, configure an upstream, then derive client keys. Credentials are database-managed; no credential JSON is generated. Clients manually enter Portal origin and their ASR key.

In `.env`, IMAGE selects the loaded image, BIND/PORT control host listening, DATA defaults to `./data`. A changed DATA directory must also be writable. Docker Desktop shared-directory permissions follow the host; confirm writes work. `docker compose down` stops HTTP and retains the bind directory.

## Single-instance HTTPS

`compose.https.yaml` is a **complete standalone configuration**: NGINX publishes 80/443, Portal listens only in the container network, and data uses named volume portal-data. Always use `docker compose -f compose.https.yaml ...`. It ignores HTTP DATA/BIND/PORT. HTTPS binding uses OPENASRPORTAL_HTTPS_BIND, default loopback. Ports and ./tls are literal Compose settings; .env.example has no domain/TLS-path variables.

These files are not base/override layers. Do not stack them: merging mixes ports/volumes and some Compose versions reject duplicate extra_hosts. Existing HTTP-data migration is below.

1. Load Portal and copy .env as above. Also prepare nginx:1.28-alpine (`docker pull nginx:1.28-alpine` online, or import the matching architecture offline). image.tar contains Portal only.
2. Place a certificate covering actual DNS names/IPs at tls/server.crt, with tls/server.key. Use a complete chain for trusted certificates. For a self-signed demonstration:

```bash
# Linux: use image Python/cryptography in a temporary container; no host Python needed.
docker compose -f compose.https.yaml run --rm --no-deps --user "$(id -u):$(id -g)" -v "$PWD:/work" --entrypoint python portal /work/create_tls_certificate.py --host localhost --host 127.0.0.1 --output /work/tls
docker compose -f compose.https.yaml up -d
docker compose -f compose.https.yaml ps
curl --cacert tls/server.crt https://localhost/health
```

Repeat --host for actual client-access names/IPs, without scheme/port. Validity defaults to 365 days; --days accepts 1–3650. Existing certificates are never overwritten. In Windows PowerShell replace the --user expression with `--user 0:0` and mount with `-v "${PWD}:/work"`.

3. Initialize locally at https://localhost/admin. For self-signed certificates, verify fingerprints, then import **server.crt** into each actual client trust store. Browser/Python/Node stores can differ; verify each. Copy only public certificates; server.key stays server-side. Do not disable TLS checks.
4. For remote access add OPENASRPORTAL_HTTPS_BIND=0.0.0.0 or a specific interface to .env, then rerun up -d with the same -f. Connect using a covered name and direct HTTPS, not HTTP redirects clients may reject. NGINX supports WS upgrades/streaming.

## Migration, backup, and maintenance

HTTP uses a host directory; HTTPS uses the Compose project's portal-data volume. They do not share automatically. Retain all data, especially portal.db/asr-key-vault.key. Stop the relevant service before backup to avoid omitting SQLite WAL.

To retain existing HTTP data: `docker compose down`, back up data/, change Portal's HTTPS mount to `./data:/data` (or actual path), confirm UID 10001 writes, then start using only the HTTPS file. Verify login/profiles/hotwords/keys. Without migration, a fresh volume shows setup, not loss of old data.

Named volumes follow Compose project names. When moving directories, retain `-p <original-project-name>` or migrate explicitly. HTTPS down preserves volumes; down -v deletes them. Upgrade by loading the new image, updating IMAGE, then up -d using the original configuration.

Rotate certificates by generating/validating in a new directory, keeping rollback copies, replacing certificate/key together in tls/, then running `docker compose -f compose.https.yaml exec nginx nginx -t` and `docker compose -f compose.https.yaml exec nginx nginx -s reload`. Self-signed clients also need updated trust.

Diagnose with `docker compose -f compose.https.yaml logs --tail 100 portal nginx`. NGINX waits for Portal healthy. For 502 check health/network; for certificate failures check SAN/validity/client trust. Portal may reach host LocalASR through configured host.docker.internal, but the host service must listen on a container-reachable interface. Service names in another Compose project require a shared network.
