# 将 Boson AI Higgs STT 接入 Portal

[English](boson-api-setup.md) | **简体中文**

Portal 通过 Boson 的 Higgs Realtime WebSocket 启用 `higgs-stt-3.1` 输入转写。录音时实时上传音频，提交分段后获得文本；该接口目前返回已完成的输入转写，不提供逐字 partial。

## 账号和配置

1. 按 Boson 的[账号开通说明](https://docs.boson.ai/set-up-your-account)创建 API key，确认额度和模型权限。
2. 打开 Portal `/admin`，登录后选择 **上游 ASR 接入 → 增加服务接入**。
3. 选择 **Boson AI · Higgs STT**，填写唯一的配置 ID、名称和 API key；不要加 `Bearer` 前缀。
4. 保留只读地址 `wss://api.boson.ai/v1/realtime` 和转写模型 `higgs-stt-3.1`。底层会话模型 `higgs-realtime` 由适配器自动设置。
5. 识别语种使用 `auto` 自动检测，或填写 `zh`、`en` 等 ISO-639-1 提示。Boson 可能忽略不认识的语言提示。断句静音可设 600–3000 毫秒，默认 800 毫秒。
6. 测试上游连接后保存。测试会提交 200 毫秒静音并等待转写响应，消耗少量上游用量；验证的是模型调用权限，不只是 WebSocket 连通。
7. 设为默认档案，或在客户端明确选择此档案。客户端仍使用 Portal 派生的 ASR Key。

## 识别行为

- Portal 将 16 kHz 单声道 PCM16 编为 base64 分块上传。本地按音量断句，在停顿、连续音频达到 15 秒或结束录音时提交。低音量背景静音丢弃，保留最多 200 毫秒前置音频。过轻的讲话和背景噪声会影响断句，可调整麦克风音量及静音参数。
- 每段完成后产生稳定 final；没有预测预览或热词提示。公开能力中 `partialResults` 为 false，`latencyClass` 为 `segmented`。
- 使用手动提交模式（`turn_detection: null`），避免自动生成对话回复。Portal 不发送 `response.create`，也不把助手输出当作识别文字。Boson 目前不支持 OpenAI 的纯转写会话，不能仅替换 OpenAI 地址接入。
- 下一段等待上一段转写完成，避免 Boson 用后来的语段替换尚未完成的转写。上游卡住时报告失败，不静默丢段。取消时关闭连接，不提交缓冲中的讲话。
- Portal 时长额度按接受的客户端音频计算，包含静音；上游经过静音过滤后的计费时长可能不同，以云账单为准。Portal 按每个流式会话记录一次请求，不按 commit 次数计数，不将时长换算成 Token。此提供商应使用时长额度，不设 Token 额度。

## 排查和参考

延迟分为连接/会话初始化、等待语段边界、提交到定稿三个阶段。录音中的默认 800 ms 静音等待会叠加上游耗时；`audio.end` 在待完成的上一段之后立即提交剩余音频。此接口没有逐字预览。背景噪声持续高于本地能量阈值时，可能直到 15 秒上限才分段；先检查麦克风音量和噪声，再考虑降低静音时长（最低 600 ms）。上一段转写慢也会阻塞后续音频上传，以避免丢段。

INFO 日志中的 `Boson timing` 记录随机会话关联 ID、`ready_ms`、语段音频起止位置、`commit_ack_ms`、`final_after_commit_ms` 和排队音频时长，不记录 Key、识别文本或音频。提交本身晚通常涉及分段/积压；提交及时但定稿慢则指向上游/网络路径。客户端计时不能再区分服务端排队与模型推理。可用同一公开音频与直连手动分段会话对照，不能用连接测试耗时代替语音转写延迟。

鉴权或模型调用失败时，检查 Key、模型权限、余额及 Portal 后端到 Boson 的网络。在停顿前不出字属于正常行为；连续讲话最长 15 秒强制分段。连接测试成功不等于麦克风准确率或原生输入验收通过。

- [连接与会话](https://docs.boson.ai/models/higgs-realtime/guides/connections-and-sessions)
- [协议兼容差异](https://docs.boson.ai/models/higgs-realtime/migrate-an-existing-integration)
- [客户端事件](https://docs.boson.ai/api-reference/realtime/client-events)
- [服务端事件与转写计量](https://docs.boson.ai/api-reference/realtime/server-events)
- [价格](https://docs.boson.ai/pricing)
