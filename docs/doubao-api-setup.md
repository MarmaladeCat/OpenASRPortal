# Activate Doubao Speech API and connect it to Portal

**English** | [简体中文](doubao-api-setup.zh-CN.md)

Create a Volcengine project, activate **Doubao streaming speech recognition 2.0**, and bind its API key to an upstream profile in OpenASRPortal **1.1.1**.

## 1. Sign in to Volcengine

Open the [Volcengine Doubao Speech console](https://console.volcengine.com/speech/new/overview?projectName=default) and sign in. If you do not have an account, register and complete identity verification and initial service activation as prompted.

## 2. Create a project

1. Open the **project selector** at the top of the page.
2. Select **Manage projects (管理项目)** to open project management.
3. Create a project with a name such as `openasr` and confirm.
4. Return to the Doubao Speech console and select the new project at the top.

Use this project for both model activation and API key creation below.

## 3. Activate streaming speech recognition 2.0

1. Select **Activation management (开通管理)** in the sidebar.
2. Find **Doubao streaming speech recognition model 2.0 (豆包流式语音识别模型 2.0)** and select **Activate (开通)**.
3. Confirm the service agreement and complete activation. This guide uses the **duration edition**.

Check the selected project's available trial resources, expiration, balance, and current duration/concurrency pricing in the console. Trial allowances and prices can change; Portal does not provision cloud credit or synchronize its local quota with the cloud balance.

## 4. Create an API key

1. Confirm that the new project is still selected.
2. Open **API key management (API Key 管理)**, also called **API management (API 管理)** in some pages.
3. Create one API key, supplying a name such as `openasrportal` if requested.
4. Copy and save the complete key for the Portal configuration below.

Use the **API key** from the new Doubao Speech console. If the page shows legacy `APP ID` and `Access Token` credentials, switch to the new console to obtain the key.

## 5. Bind the API key to a Portal upstream

1. Open Portal administration, normally `http://127.0.0.1:10087/admin` locally. Sign in and open **Upstream ASR → Add service connection (上游 ASR 接入 → 增加服务接入)**.
2. Enter these settings:

| Field | Value |
| --- | --- |
| Profile ID | For example, `doubao-main` |
| Display name | For example, “Doubao Speech 2.0” |
| Provider | Doubao realtime speech recognition |
| Upstream API key | The newly created API key; enter only the key |
| WebSocket endpoint | Keep `wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async` (read-only) |
| Model resource | 2.0 duration edition: `volc.seedasr.sauc.duration` |
| Second-pass recognition | Keep enabled by default |
| Use proxy | Off for direct access; enable only after configuring Portal's global HTTP/HTTPS proxy |

3. For an existing card, select **Edit** first; otherwise fill the new-connection form. Choose **Use proxy** before **Test upstream connection**. The test uses the current form values and proxy choice, with its result inside that panel. It does not save the form. Select **Save** after success; **Cancel** discards edits.
4. To use Doubao by default, select **Set as default (设为默认)** on its upstream card.

The Doubao API key is now bound to Portal's upstream. Select this profile in a client and record a short phrase to check recognition. For client connection settings, see the [Portal user guide](user-guide.md).

## Recognition and network settings

- Match the resource to the service you activated: 2.0 duration is `volc.seedasr.sauc.duration`, 2.0 concurrency is `volc.seedasr.sauc.concurrent`. The `volc.bigasr.sauc.*` choices are the older 1.0 resources. A valid key alone does not grant every resource.
- Second-pass recognition revises a completed segment after streaming previews. Keep it enabled initially. This Portal adapter does not expose a language-list field for Doubao; do not paste `en,zh` into the model/resource field. The interface language dropdown changes the page language, not the recognizer.
- To use a proxy, save its address and optional authentication under **Settings → HTTP/HTTPS proxy**, test availability there, then enable **Use proxy** on this upstream. The proxy must support CONNECT to the WSS endpoint. An enabled but unavailable proxy fails explicitly; disabling the switch selects direct routing. The proxy address must be reachable from the Portal service, not just your browser.
- Keep the card **Enabled** after saving. The connection test can consume upstream usage and establishes connectivity/model access, not microphone quality. Verify with a short Chinese phrase and a short English phrase from an actual client.

## Troubleshooting

- **Unauthorized or resource not activated:** confirm that the model and API key belong to the same project and that the selected resource is `volc.seedasr.sauc.duration`.
- **Authentication failure:** check the complete key. Do not add a `Bearer` prefix or use a legacy Access Token.
- **Recognition stops after free credit is exhausted:** check the Volcengine balance and service status, and the Portal upstream's local quota. Portal quota is separate from the cloud balance.
- **The test succeeds but the client cannot use the profile:** confirm that the profile is saved and enabled. Clients use an ASR key derived by Portal; the cloud API key belongs in Portal's upstream settings.

## Official references

- [Console guide: projects, model activation, and API keys](https://docs.volcengine.com/docs/6561/2485392?lang=zh)
- [Bidirectional streaming recognition WebSocket](https://docs.volcengine.com/docs/6561/2630027?lang=zh)
- [Billing instructions](https://docs.volcengine.com/docs/DoubaoVoice/Billinginstructions-21?lang=zh)
