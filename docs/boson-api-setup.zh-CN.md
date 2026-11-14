# 将 Boson AI Higgs STT 接入 Portal

[English](boson-api-setup.md) | **简体中文**

Portal 通过 Boson 的 Higgs Realtime WebSocket 启用 `higgs-stt-3.1` 输入转写。录音时完整实时上传音频，仅在 `audio.end` 提交整轮；该接口返回已完成的输入转写，不提供逐字 partial。

## 账号和配置

1. 登录 [Boson 工作台](https://www.boson.ai/workspace)并完成账号验证，在 [API Keys](https://www.boson.ai/workspace/api-key) 点击 **Create API Key**，显示时复制完整的 `bai-…` Key。现行要求见[账号开通说明](https://docs.boson.ai/set-up-your-account)。符合条件的试用额度需要在 API Keys 或账单页主动领取，创建账号/Key 不代表自动到账；也可充值并确认模型权限。
2. 打开 Portal `/admin`，登录后选择 **上游 ASR 接入 → 增加服务接入**。
3. 选择 **Boson AI · Higgs STT**，填写唯一的配置 ID、名称和 API key；不要加 `Bearer` 前缀。
4. 保留只读地址 `wss://api.boson.ai/v1/realtime` 和转写模型 `higgs-stt-3.1`。底层会话模型 `higgs-realtime` 由适配器自动设置。
5. 中英文自动识别先使用 `auto`，或填写 `zh`、`en` 等单个 ISO-639-1 提示。不要填 `en,zh`，此适配器与 Soniox 不同，只接受一个语言提示。Boson 可能忽略不认识的语言提示。没有本地静音阈值；旧 `silenceMs` 会被忽略，并在保存时移除。
6. 测试前选好 **使用代理**；开启时先在 **设置**中保存并测试全局 HTTP/HTTPS 代理，确保 Portal 后端能访问。修改已有卡片需先点 **编辑**。上游测试使用尚未保存的表单及当前代理开关，在本面板显示结果；提交 200 毫秒静音并等待转写响应，消耗少量用量，检查模型权限而非仅 WebSocket 连通。成功后点 **保存**，**取消**放弃修改。
7. 设为默认档案，或在客户端明确选择此档案。客户端仍使用 Portal 派生的 ASR Key。

保存后保持卡片 **启用**。页面语言下拉框不改变识别语种。请用包含思考停顿的中文和英文录音验证，停止录音后等待整轮结果。代理可用性测试与识别连接测试范围不同；已开启的代理不可用时不会自动直连。

## 识别行为

- Portal 将全部 16 kHz 单声道 PCM16 样本编为 base64 分块上传，包含静音和轻声；没有本地能量阈值、静音切段或 15 秒强制切段。传输分块不代表断句。
- 公开 WS 限制内的大帧拆分时会逐块让上传任务获得调度。15 秒待上传音频上限针对真实上游积压，健康连接不会在上传任务运行前就被突发拆包填满。真正阻塞的连接明确报错，并可取消。
- 每段完成后产生稳定 final；没有预测预览或热词提示。公开能力中 `partialResults` 为 false，`latencyClass` 为 `segmented`。
- 使用手动提交模式（`turn_detection: null`），避免自动生成对话回复。Portal 不发送 `response.create`，也不把助手输出当作识别文字。Boson 目前不支持 OpenAI 的纯转写会话，不能仅替换 OpenAI 地址接入。
- 仅 `audio.end` 或已接收音频额度耗尽时提交整轮。定稿超时明确报错；取消关闭连接，不提交新轮次。录音预算之后，Portal 留出 75 秒排空并真实写出 commit，再给提供方 35 秒识别预算。含 1 秒余量的 `finalizeTimeoutMs` 为 111000 毫秒，客户端读取会话快照，不按品牌写死。
- Portal 时长额度按接受的客户端音频计算，包含静音；云账单仍是实际收费依据。每个流式会话记录一次请求，不将时长换算成 Token。此提供商应使用时长额度，不设 Token 额度。

## 排查和参考

延迟分为连接/会话初始化、等待用户结束录音、提交到定稿三个阶段。`audio.end` 会立即刷新并提交，思考停顿不会触发提交。最终文本内部的标点仍由模型决定，不能保证模型绝不会把停顿理解为句界。

INFO 日志中的 `Boson timing` 记录随机会话关联 ID、`ready_ms`、音频起止位置、`commit_ack_ms`、`final_after_commit_ms` 和排队音频时长，不记录 Key、识别文本或音频。提交及时但定稿慢指向上游/网络路径；客户端计时不能再区分服务端排队与模型推理。可用同一公开音频与直连手动提交会话对照，不能用连接测试耗时代替语音转写延迟。

鉴权或模型调用失败时，检查 Key、模型权限、余额及 Portal 后端到 Boson 的网络。停止录音前不出字属于正常行为。连接测试成功不等于麦克风准确率或原生输入验收通过。

`429 insufficient_quota` 可能是试用额度未领取或余额不足，请检查[账单页](https://www.boson.ai/workspace/billing/overview)；若是请求限流则应检查并发/请求限制。`401` 时核对完整 Key，输入时不加 `Bearer` 前缀。代理超时或 CONNECT 错误先从 Portal 所在机器检查代理，不要先改模型参数。

- [连接与会话](https://docs.boson.ai/models/higgs-realtime/guides/connections-and-sessions)
- [协议兼容差异](https://docs.boson.ai/models/higgs-realtime/migrate-an-existing-integration)
- [客户端事件](https://docs.boson.ai/api-reference/realtime/client-events)
- [服务端事件与转写计量](https://docs.boson.ai/api-reference/realtime/server-events)
- [价格](https://docs.boson.ai/pricing)
