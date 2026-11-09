# 开通阿里云百炼 API 并接入 Portal

[English](bailian-api-setup.md) | **简体中文**

本文介绍如何在阿里云百炼中新建业务空间、授权 **`qwen-audio-3.1-asr-flash-streaming`** 模型，并创建绑定该业务空间的 API Key，供 OpenASRPortal **1.1.0** 上游使用。

## 1. 登录百炼控制台

打开 [阿里云百炼控制台](https://bailian.console.aliyun.com/)，登录阿里云账号。首次使用时，按页面提示完成实名认证及模型服务开通。

本教程以 **华北 2（北京）** 地域为例。后续业务空间、API Key 和接入地址保持在同一地域。

## 2. 新增业务空间

1. 点击控制台上方的**业务空间选择**入口。
2. 选择**新增业务空间**，按页面提示填写名称，例如 `openasr`，完成创建。
3. 进入 **业务空间管理**，找到刚创建的业务空间。

## 3. 给业务空间授权模型调用

1. 在 **业务空间管理**中打开刚创建的业务空间。
2. 进入该空间的 **模型权限流控设置**页面。
3. 搜索完整模型名称 **`qwen-audio-3.1-asr-flash-streaming`**。
4. 开通该模型的**模型调用**权限，确认状态为 **已授权**。

必须选择带 `-streaming` 后缀的完整型号。如果无法操作授权，请联系账号或业务空间管理员。

## 4. 创建并绑定 API Key

1. 进入 **API Key 管理**页面（[北京地域入口](https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key)）。
2. 点击 **创建 API Key**。
3. 在**归属业务空间**中，选择刚刚创建并授权模型的业务空间；按页面要求选择归属账号，完成创建。
4. 立即复制并保存完整的 API Key。新版 Key 通常只在创建成功时完整显示一次。

关键是让这个 API Key **归属于刚授权的业务空间**。如果额外设置了 Key 的自定义模型权限，也要包含 `qwen-audio-3.1-asr-flash-streaming`。

## 5. 将 API Key 绑定到 Portal 上游

1. 打开 Portal 管理页，本机默认地址为 `http://127.0.0.1:10087/admin`，登录后进入 **上游 ASR 接入 → 增加服务接入**。
2. 按下表填写：

| 字段 | 填写内容 |
| --- | --- |
| 配置 ID | 例如 `bailian-main` |
| 显示名称 | 例如“百炼语音识别” |
| 提供商 | 百炼 · Qwen ASR Streaming |
| 上游 API Key | 刚创建并绑定业务空间的 API Key，只填 Key 本身 |
| WebSocket 地址 | 该业务空间的 DashScope WSS 地址，见下方说明 |
| 模型 | 保留只读的 `qwen-audio-3.1-asr-flash-streaming` |
| 其他识别选项 | 首次使用保留默认值 |

在百炼控制台该业务空间的接入信息中取得 **Workspace ID**。北京地域可填写：

```text
wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference
```

将 `{WorkspaceId}` 连同花括号替换为刚创建的业务空间 ID，不是空间名称。官方 WSS 根地址也会自动补齐路径。兼容旧共享域名 `wss://dashscope.aliyuncs.com/api-ws/v1/inference`；阿里云推荐业务空间专属域名。

若使用新加坡地域，使用该地域业务空间和 Key，并将地址改为：

```text
wss://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/inference
```

3. 点击 **测试上游连接**，成功后点击 **保存接入配置**。
4. 如需默认使用百炼，在该上游卡片点击 **设为默认**。

至此，百炼 API Key 已绑定到 Portal 上游。可在客户端选择该档案，录制一句短语验证识别结果。客户端连接配置见 [Portal 使用手册](user-guide.zh-CN.md)。

## 费用与常见问题

Portal 发送 `run-task` 并等待 `task-started`，逐块上传一次 16 kHz 单声道 PCM16，转发上游 partial/final 分句。结束时发送 `finish-task`，等待 `task-finished`。服务端静音断句范围 200–6000 ms，默认 800 ms。没有本地 VAD、重复 HTTP 识别、预览间隔或 HTTP 回退。

读取旧 HTTP 档案时自动迁移模型及协议/路径，保留地域、业务空间、Key、静音设置、档案 ID 和配额；保存后持久化新设置。使用前需要授权流式模型，配置迁移不能代替云端授权。

- **计费**：以百炼当前价格为准。Portal 音频只计一次，每个任务计一次请求；累计 Token 只扣增量，任务结束用最终报告结算。共用限额账户的 Token 限额流串行执行。缺少最终用量时暂停 Token 限额账户，需调整预算或去掉 Token 限额；取消保留已知用量。最终结算可能超过剩余预算。
- **提示模型无权限**：回到刚创建的业务空间，确认模型的调用状态是 **已授权**，再确认 API Key 归属于这个空间。
- **提示 Key 无效**：确认复制了完整的百炼 API Key，地域正确，输入框里没有 `Bearer` 前缀。
- **地址无法保存或请求失败**：核对 Workspace ID、地域、WSS 协议及 `/api-ws/v1/inference` 路径，使用与 Key 匹配的空间地址。
- **客户端配置**：客户端使用 Portal 派生的 ASR Key，百炼 API Key 填在 Portal 上游中。测试连接后仍需保存档案。

## 官方参考

- [业务空间权限管理](https://help.aliyun.com/zh/model-studio/permission-management-overview)
- [获取与配置 API Key](https://help.aliyun.com/zh/model-studio/get-api-key)
- [地域与接入域名](https://help.aliyun.com/zh/model-studio/regions)
- [流式 WebSocket 连接](https://help.aliyun.com/en/model-studio/qwen-audio-asr-streaming-websocket-api)
- [客户端事件](https://help.aliyun.com/en/model-studio/qwen-audio-asr-streaming-client-events) · [服务端事件](https://help.aliyun.com/en/model-studio/qwen-audio-asr-streaming-server-events)
