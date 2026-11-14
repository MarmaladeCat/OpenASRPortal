# 接入 Soniox 实时 STT

[English](soniox-api-setup.md) | **简体中文**

在 [Soniox 控制台](https://console.soniox.com/) 创建 API Key，确认余额和模型权限。在 Portal **上游 ASR 接入 → 增加服务接入** 选择 **Soniox · 实时语音识别**，填写唯一档案 ID、名称及不带 Bearer 前缀的 Key，测试后保存。

- 提供商 ID：`soniox_realtime`；模型：`stt-rt-v6`。
- 地址：`wss://stt-rt.soniox.com/transcribe-websocket`（只读）。
- 语种：新档案默认中文、英文提示（`zh,en`），面向大量中文中夹杂少量英文。提示顺序不代表语言权重，也不限制其他语种识别。下拉框可选自动识别或单一语种；API 支持最多十个逗号分隔的两位提示代码。已有选择保留，需要时手动将旧档案改为 `zh,en`。
- 上游自动端点检测（`endpointDetection`）默认**关闭**。稳定 token 到达时按音频顺序提交，可变 token 保留为整体替换的预览；开启检测后上游另发端点标记。已有选择保留，缺少字段时使用关闭。
- 最大端点延迟：500–3000 ms，默认 2000，仅开启端点检测时使用；不保证网络或完整响应延迟。全部音频及静音始终上传，文本标点仍由上游模型决定。

Portal 在 WebSocket 握手时用 Bearer 头鉴权，先发配置，再上传 16 kHz 单声道 PCM16，转发真实 partial。稳定 token 批次立即形成有序 final，只提交一次；临时词整体替换尾部。`<end>` / `<fin>` 可用空 final 关闭已撤回尾部。结束音频发送空文本帧，等待 `finished: true`，不重复提交之前的稳定文字；空 final 计入 v1 `finalCount`。终态仍有新临时词、上游错误或结束超时均明确报错。取消直接关闭流，不伪造定稿；空闲连接发送 keepalive。

个人热词通过 `context.terms` 发送，不发送数值权重。Portal 保守限制所选上下文为 7000 UTF-8 字节，低于 Soniox 的 8000-token 上下文上限；只发送选中的词。

Portal 提供本地**已提交音频时长**配额；Soniox 按**流连接时长**计费，包括保活空闲时间。两者口径不同，本地配额不是云费用上限。Soniox 文本 token 是识别片段，不是计费用量报告，因此不支持 Token 配额。连接测试上传 200 ms 静音并等待完成，会消耗真实上游用量；通过不代表识别准确率或麦克风验收。

连接测试失败时检查 Key 权限、余额和后端网络，新流需要当前模型权限。验收需重放公开中英文音频，检查停止前 partial、稳定定稿无重复词、取消及实测尾部延迟。密钥不要进入源码。

官方参考：[WebSocket API](https://soniox.com/docs/api-reference/stt/websocket-api)、[实时转写](https://soniox.com/docs/stt/rt/real-time-transcription)、[端点检测](https://soniox.com/docs/stt/rt/endpoint-detection)、[上下文](https://soniox.com/docs/stt/concepts/context)。
