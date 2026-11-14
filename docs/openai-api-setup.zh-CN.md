# OpenAI 转写接入

[English](openai-api-setup.md) | **简体中文**

在 [OpenAI 平台](https://platform.openai.com/api-keys)创建具有转写模型权限的 API Key，在 Portal 添加以下明确的上游类型。Key 仅保存在 Portal，不填入 Input；有需要时启用既有全局代理选项。

- **OpenAI · 完整录音文件**（`openai_file`）：`gpt-transcribe`，地址 `https://api.openai.com/v1/audio/transcriptions`。JSON 返回完整文字；SSE 在处理已经录好的文件时展示修订。二者都在停止后仅上传一次，不提供麦克风录音中的预览。
- **OpenAI · Realtime 转写**（`openai_realtime`）：`wss://api.openai.com/v1/realtime?intent=transcription`。`gpt-live-transcribe` 录音中预览；`gpt-transcribe` 在 commit 后开始转写。每轮 Input 对应一个手动 turn，禁用 VAD。

可选的逗号分隔预期语种、背景 prompt 是提示，不保证输出。Portal 限制 prompt 为 4096 字符。个人热词转换为无权重 keywords，本地限制 100 个词／4096 UTF-8 字节；关键词禁止 `<`、`>`、回车和换行。语种留空表示自动识别。delay 的 `minimal` 至 `xhigh` 档位仅用于 live 模型，是可选项，不是保证毫秒数。

Realtime 等有效 `session.updated` 后才 ready，以 SoXR 连续将源 16 kHz PCM 转成 24 kHz，保留 commit 前 delta，并按已提交 item 匹配完成结果。定稿全文替换候选，不伪造词时间、说话人或置信度。文件保持 16 kHz WAV；Portal 五分钟录音限制小于服务 25 MB 文件限制。

取消关闭本轮 I/O，不调用对话响应取消接口，不承诺已提交 ASR 不收费。Token 与 duration 报告独立；账户／工作流不返回 token 时应使用时长配额。缺少用量不算零。

构建与运行依赖包含 numpy、SoXR；16 kHz 上游不加载它们。Linux amd64/arm64、Windows 的实际候选包都需验证转换库；源码安装缺组件时在 ready 前明确失败。

连接测试提交短静音请求，可能产生用量。真实验收还需公开语音、live 模型停录前文字、定稿全文替换、停止／取消延迟及实际用量。遵循[测试要求](testing.zh-CN.md)，模拟协议夹具不代表云端可用性或识别质量。

参考：[文件转写](https://developers.openai.com/api/docs/guides/speech-to-text)、[实时转写](https://developers.openai.com/api/docs/guides/realtime-transcription)、[转写总览](https://developers.openai.com/api/docs/guides/transcription)。当前配置使用 `gpt-transcribe`／`gpt-live-transcribe`，不使用已公告于 2027-02-26 停用的旧模型。
