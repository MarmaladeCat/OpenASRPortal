# 开通阿里云百炼 API 并接入 Portal

[English](bailian-api-setup.md) | **简体中文**

本文介绍如何在阿里云百炼中新建业务空间、授权 **`qwen-audio-3.1-asr-flash`** 模型，并创建绑定该业务空间的 API Key，供 OpenASRPortal **1.0.1** 上游使用。

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
3. 搜索完整模型名称 **`qwen-audio-3.1-asr-flash`**。
4. 开通该模型的**模型调用**权限，确认状态为 **已授权**。

当前 Portal 使用的就是这个完整型号。选择时不要误选带 `-streaming`、`-message` 或 `-filetrans` 后缀的模型。如果无法操作授权，请联系账号或业务空间管理员。

## 4. 创建并绑定 API Key

1. 进入 **API Key 管理**页面（[北京地域入口](https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key)）。
2. 点击 **创建 API Key**。
3. 在**归属业务空间**中，选择刚刚创建并授权模型的业务空间；按页面要求选择归属账号，完成创建。
4. 立即复制并保存完整的 API Key。新版 Key 通常只在创建成功时完整显示一次。

关键是让这个 API Key **归属于刚授权的业务空间**。如果额外设置了 Key 的自定义模型权限，也要包含 `qwen-audio-3.1-asr-flash`。

## 5. 将 API Key 绑定到 Portal 上游

1. 打开 Portal 管理页，本机默认地址为 `http://127.0.0.1:10087/admin`，登录后进入 **上游 ASR 接入 → 增加服务接入**。
2. 按下表填写：

| 字段 | 填写内容 |
| --- | --- |
| 配置 ID | 例如 `bailian-main` |
| 显示名称 | 例如“百炼语音识别” |
| 提供商 | 百炼 · Qwen ASR Flash |
| 上游 API Key | 刚创建并绑定业务空间的 API Key，只填 Key 本身 |
| HTTPS 地址 | 该业务空间的 DashScope 地址，见下方说明 |
| 模型 | 保留只读的 `qwen-audio-3.1-asr-flash` |
| 其他识别选项 | 首次使用保留默认值 |

在百炼控制台该业务空间的接入信息中取得 **Workspace ID**。北京地域可填写：

```text
https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1
```

将 `{WorkspaceId}` 连同花括号替换为刚创建的业务空间 ID，不是空间名称。Portal 会自动补齐识别路径。这里使用 **DashScope HTTP 地址**，不要填写通用聊天接口的 `/compatible-mode/v1`。

若使用新加坡地域，使用该地域业务空间和 Key，并将地址改为：

```text
https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/api/v1
```

3. 点击 **测试上游连接**，成功后点击 **保存接入配置**。
4. 如需默认使用百炼，在该上游卡片点击 **设为默认**。

至此，百炼 API Key 已绑定到 Portal 上游。可在客户端选择该档案，录制一句短语验证识别结果。客户端连接配置见 [Portal 使用手册](user-guide.zh-CN.md)。

## 费用与常见问题

- **计费**：该模型按输入、输出 Token 计费，价格及免费额度以百炼控制台为准。Portal 的预览会重复提交当前语段音频；增大预览间隔或关闭预览可减少这部分请求和用量。
- **提示模型无权限**：回到刚创建的业务空间，确认模型的调用状态是 **已授权**，再确认 API Key 归属于这个空间。
- **提示 Key 无效**：确认复制了完整的百炼 API Key，地域正确，输入框里没有 `Bearer` 前缀。
- **地址无法保存或请求失败**：核对 Workspace ID、地域和 `/api/v1` 路径，使用与 Key 匹配的空间地址。
- **客户端配置**：客户端使用 Portal 派生的 ASR Key，百炼 API Key 填在 Portal 上游中。测试连接后仍需保存档案。

## 官方参考

- [业务空间权限管理](https://help.aliyun.com/zh/model-studio/permission-management-overview)
- [获取与配置 API Key](https://help.aliyun.com/zh/model-studio/get-api-key)
- [地域与接入域名](https://help.aliyun.com/zh/model-studio/regions)
- [`qwen-audio-3.1-asr-flash` 模型详情与价格](https://help.aliyun.com/zh/model-studio/qwen-audio-3-1-asr-flash)
- [Qwen-Audio-ASR HTTP API](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-http-api)
