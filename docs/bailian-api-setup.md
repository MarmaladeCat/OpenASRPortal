# Activate Alibaba Cloud Model Studio API and connect it to Portal

**English** | [简体中文](bailian-api-setup.zh-CN.md)

Create an Alibaba Cloud Model Studio (Bailian) workspace, authorize **`qwen-audio-3.1-asr-flash-streaming`**, and create an API key bound to that workspace for an upstream profile in OpenASRPortal **1.1.1**.

## 1. Sign in to Model Studio

Open the [Model Studio console](https://bailian.console.aliyun.com/) and sign in to Alibaba Cloud. On first use, complete identity verification and model-service activation as prompted.

This guide uses **China (Beijing) / 华北 2（北京）**. Keep the workspace, API key, and endpoint in the same region throughout the following steps.

## 2. Create a workspace

1. Open the **workspace selector** at the top of the console.
2. Select **Add workspace (新增业务空间)**, enter a name such as `openasr`, and complete creation.
3. Open **Workspace management (业务空间管理)** and find the new workspace.

## 3. Authorize model calls for the workspace

1. Open the new workspace in **Workspace management**.
2. Open its **Model permissions and rate-limit settings (模型权限流控设置)** page.
3. Search for the exact model name **`qwen-audio-3.1-asr-flash-streaming`**.
4. Enable **model invocation (模型调用)** and confirm that its status is **Authorized (已授权)**.

The `-streaming` suffix is required. If you cannot change authorization, contact the account or workspace administrator.

## 4. Create and bind an API key

1. Open **API key management** ([Beijing entry](https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key)).
2. Select **Create API Key (创建 API Key)**.
3. For the **owning workspace (归属业务空间)**, choose the workspace you just created and authorized. Select the owning account as requested and complete creation.
4. Immediately copy and save the complete key. New keys are generally shown in full only once after creation.

The key must **belong to the workspace whose model access you authorized**. If you additionally configure custom model permissions for the key, include `qwen-audio-3.1-asr-flash-streaming`.

## 5. Bind the API key to a Portal upstream

1. Open Portal administration, normally `http://127.0.0.1:10087/admin` locally. Sign in and open **Upstream ASR → Add service connection (上游 ASR 接入 → 增加服务接入)**.
2. Enter these settings:

| Field | Value |
| --- | --- |
| Profile ID | For example, `bailian-main` |
| Display name | For example, “Bailian speech recognition” |
| Provider | Bailian · Qwen ASR Streaming |
| Upstream API key | The key bound to the new workspace; enter only the key |
| WebSocket endpoint | This workspace's DashScope WSS endpoint, as described below |
| Model | Keep the read-only `qwen-audio-3.1-asr-flash-streaming` |
| Recognition language | `auto` for automatic recognition including Chinese and English; select a single supported language only when needed |
| Preserve dialect | Off initially; enable only if you want the provider's dialect-preservation behavior |
| Segmentation silence | 800 ms initially; supported range 200–6000 ms |
| Use proxy | Off for direct access; enable only with a configured global HTTP/HTTPS proxy |

Obtain the **Workspace ID** from this workspace's connection information in Model Studio. For Beijing, enter:

```text
wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference
```

Replace `{WorkspaceId}`, including the braces, with the new workspace's ID, not its name. Portal also completes the path on an official WSS root address. The older shared `wss://dashscope.aliyuncs.com/api-ws/v1/inference` domain remains accepted; workspace domains are recommended by Alibaba Cloud.

For Singapore, use a workspace and key in that region and enter:

```text
wss://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/inference
```

3. Existing cards start read-only: choose **Edit** before changing fields. Set **Use proxy**, then **Test upstream connection**. The test uses the unsaved form and current proxy choice; its result stays in the panel. Select **Save** to persist the connection, or **Cancel** to discard edits.
4. To use Bailian by default, select **Set as default (设为默认)** on its upstream card.

The Bailian API key is now bound to Portal's upstream. Select this profile in a client and record a short phrase to check recognition. For client connection settings, see the [Portal user guide](user-guide.md).

## Language, proxy, and first-use checks

`auto` is the starting point for Chinese/English or mixed-language speech. Bailian accepts one language selection here, not Soniox's comma-separated `en,zh` list. The page-language dropdown is independent. The selected model must actually be available to your region and workspace; access to a similarly named HTTP or Realtime model does not replace permission for the exact streaming model above.

For proxy routing, first save and test **Settings → HTTP/HTTPS proxy**, then enable **Use proxy** on the Bailian card. A proxy availability test is an HTTPS request, not a Bailian model test; run both checks. Proxy failures never fall back to direct access. For Docker/remote services, addresses are resolved from Portal's environment; its `127.0.0.1` is not the browser machine.

Save the profile, leave **Enabled** on, and set it as default or choose it explicitly in the client. Clients connect to Portal's HTTP(S) address with a Portal-issued ASR key. Test short Chinese and English utterances, watching for previews before Stop and a final result after Stop. An upstream connection test may consume a small amount of usage and does not validate real speech accuracy.

## Billing and troubleshooting

Portal sends `run-task`, waits for `task-started`, streams raw 16 kHz mono PCM16 once, and forwards upstream partial/final sentences. Ending sends `finish-task` and waits for `task-finished`. Server-side silence segmentation accepts 200–6000 ms (default 800). There is no local VAD, repeated HTTP recognition, preview interval, or HTTP fallback.

Existing stored HTTP profiles are read as streaming profiles: the model and protocol/path migrate, the region, workspace, key, silence setting, profile ID and quota remain. Saving persists the upgraded settings. Grant the streaming model permission before use; migration cannot grant cloud permissions.

- **Billing:** use current Model Studio pricing. Portal counts audio once and one request per task; cumulative token reports debit only their increase. The final task report settles the total. Token-limited streams sharing an account are serialized. Missing final usage blocks token-limited accounts until the budget is reset or token limits are removed; cancellation retains known usage. Final settlement may exceed the remaining budget.
- **Model authorization error:** return to the new workspace and confirm that model invocation is **Authorized**, then verify that the key belongs to this workspace.
- **Invalid key:** check that you copied the complete Model Studio API key, selected the correct region, and omitted any `Bearer` prefix.
- **The endpoint cannot be saved or requests fail:** check the Workspace ID, region, WSS scheme and `/api-ws/v1/inference` path. Use the workspace endpoint matching the key.
- **Client setup:** clients use an ASR key derived by Portal; the Bailian API key belongs in Portal's upstream settings. Save the profile after testing the connection.

## Official references

- [Workspace permission management](https://help.aliyun.com/zh/model-studio/permission-management-overview)
- [Obtain and configure an API key](https://help.aliyun.com/zh/model-studio/get-api-key)
- [Regions and endpoints](https://help.aliyun.com/zh/model-studio/regions)
- [Streaming WebSocket connection](https://help.aliyun.com/en/model-studio/qwen-audio-asr-streaming-websocket-api)
- [Client events](https://help.aliyun.com/en/model-studio/qwen-audio-asr-streaming-client-events) · [Server events](https://help.aliyun.com/en/model-studio/qwen-audio-asr-streaming-server-events)
