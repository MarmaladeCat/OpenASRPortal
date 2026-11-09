# Activate Doubao Speech API and connect it to Portal

**English** | [简体中文](doubao-api-setup.zh-CN.md)

Create a Volcengine project, activate **Doubao streaming speech recognition 2.0**, and bind its API key to an upstream profile in OpenASRPortal **1.0.1**.

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

New users generally receive **20 hours** of free usage. After that allowance is exhausted, the usage-based price is **CNY 1 per hour**. Eligibility, credit expiration, and actual pricing depend on the console; check the resources and billing pages.

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
| WebSocket endpoint | Keep the read-only endpoint provided by Portal |
| Model resource | 2.0 duration edition: `volc.seedasr.sauc.duration` |
| Second-pass recognition | Keep enabled by default |

3. Select **Test upstream connection (测试上游连接)**, then **Save connection configuration (保存接入配置)** after success.
4. To use Doubao by default, select **Set as default (设为默认)** on its upstream card.

The Doubao API key is now bound to Portal's upstream. Select this profile in a client and record a short phrase to check recognition. For client connection settings, see the [Portal user guide](user-guide.md).

## Troubleshooting

- **Unauthorized or resource not activated:** confirm that the model and API key belong to the same project and that the selected resource is `volc.seedasr.sauc.duration`.
- **Authentication failure:** check the complete key. Do not add a `Bearer` prefix or use a legacy Access Token.
- **Recognition stops after free credit is exhausted:** check the Volcengine balance and service status, and the Portal upstream's local quota. Portal quota is separate from the cloud balance.
- **The test succeeds but the client cannot use the profile:** confirm that the profile is saved and enabled. Clients use an ASR key derived by Portal; the cloud API key belongs in Portal's upstream settings.

## Official references

- [Console guide: projects, model activation, and API keys](https://docs.volcengine.com/docs/6561/2485392?lang=zh)
- [Bidirectional streaming recognition WebSocket](https://docs.volcengine.com/docs/6561/2630027?lang=zh)
- [Billing instructions](https://docs.volcengine.com/docs/DoubaoVoice/Billinginstructions-21?lang=zh)
