# Connect OpenLocalASR to Portal

**English** | [简体中文](localasr-setup.zh-CN.md)

Use this guide for Portal 1.1.1 with OpenLocalASR 0.14.0. LocalASR runs models on its own machine; it has no independent settings webpage. Install it and prepare weights using the [LocalASR user guide](https://github.com/MarmaladeCat/OpenLocalASR/blob/main/docs/user-guide.md).

## Prepare the recognition service

1. Choose the matching Linux/Windows CPU package or Linux Docker deployment. Packages do not contain model weights. Download the desired model to the same model directory used at service startup.
2. Set and retain a private `OPENLOCALASR_API_KEY` for the service. Enter that same value in Portal's upstream; it is different from a Portal client ASR key.
3. Start LocalASR with the model, initially `funasr_sensevoice_small`. Check its public `/health` and authenticated `/v1/models`: the service must be ready and the active model must match. A reachable API or downloaded weights alone do not establish readiness. One instance has one active model.

## Fill the Portal card

Open `/admin` → **Upstream ASR → Add service connection**. For an existing card, choose **Edit**.

| Field | Initial value |
| --- | --- |
| Profile ID / name | For example, `local-main` / “Local recognition” |
| Provider | OpenLocalASR |
| WebSocket endpoint | Same-host, noncontainer service: `ws://127.0.0.1:10095/api-ws/v1/inference` |
| Model | The exact active model ID, initially `funasr_sensevoice_small`; not a path |
| Upstream API key | The service's `OPENLOCALASR_API_KEY` value |
| Use proxy | Normally off for local/LAN access |

The address is reached by Portal, not by the browser. In separate containers use a service name on their shared network, such as `ws://localasr:10095/api-ws/v1/inference`, only if that is your actual service name. Container loopback refers to that container. Remote TLS deployments use `wss://` with a valid certificate and the same path.

Choose **Test upstream connection**; it uses the current form/proxy choice and displays the result inside the card. A successful test does not save changes: click **Save**, leave **Enabled** on, then set default or select the profile in a client. **Cancel** discards edits. If proxy routing is needed, first configure/test the global HTTP/HTTPS proxy; an unavailable enabled proxy fails without direct fallback.

## Verify speech and troubleshoot

Clients use Portal's HTTP(S) URL and a Portal-issued ASR key. Try short Chinese and English phrases using a model that supports them; stop and wait for final text. The page-language dropdown is not a model-language setting. This adapter does not expose a language-list field; recognition languages and partial-result behavior depend on the selected LocalASR model.

- Connection refused/timeout: confirm service host, published port, container network and the backend's route.
- Unauthorized: use the LocalASR service key in the upstream, not the Portal admin password or client ASR key.
- Model mismatch/not ready: check `/v1/models`, weight directory and loading/error state. Changing a model affects the entire LocalASR instance.
- API health works but recognition fails: verify model runtime dependencies and test real audio; health is a liveness check. This upstream does not support session hotwords or token accounting; use duration quotas.
