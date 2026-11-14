# 识别工作流与有序结果

[English](recognition-contract.md) | **简体中文**

本文补充[公共 v1 API](API.zh-CN.md)。WebSocket、`stream=true` 或 `partialResults=true` 本身不承诺录音中出字。

## 有效能力快照

`GET /v1/profiles` 包含 `capabilities.recognition` 和 `capabilities.limits`。创建响应与 `session.ready` 重复同一份固定的 `profileId`、`capabilities`、`limits`；配置修改仅影响后续会话。

识别字段：

- `upstreamInput`：`continuous` 或 `complete_recording`。
- `processingMode`：`online`、`batch`、`online_with_second_pass` 或 `unknown`；不从传输方式推断未知内部算法。
- `preview`：`supported` 与 `phase`（`during_capture`、`after_commit`、`after_audio_end`、`none`、`unknown`）。
- `stability`：`unit`（`token`、`utterance`、`turn`、`recording`）和 `triggers`；结果稳定不代表会话结束。
- `completion`：`upstream_done`、`http_response`、`sse_done` 或 `committed_items`。
- `sessionEnd` 为 `audio.end`，`portalSegmentation` 为 `none`。
- `secondPass`：support 为 `supported` 或 `unknown`，已知 enabled 为布尔值，否则为 null；保留豆包已保存的二遍选项。

保留兼容字段：`partialResults` 表示可能有 partial；`latencyClass=streaming` 表示录音中预览，其他或未知时机使用旧兼容值 `segmented`。`finalization` 描述结果稳定方式，不表示会话自动完成。Portal 不推断 LocalASR 的内部流式策略。

服务 features 新增 `effectiveSessionLimits`、`recognitionCapabilities`、`realtimePreview`，客户端通过 `requiredFeatures` 协商。`realtimePreview` 必须由选中的配置实际满足。新配置若限制短于 300 秒，必须协商 `effectiveSessionLimits`；旧客户端在创建阶段拒绝，不能任其超长录音。

limits 包含 `maxRecordingMs`、`maxMessageBytes`、`maxQueuedAudioBytes`、`readyTimeoutMs`、`uploadTimeoutMs`、`recognitionTimeoutMs`、`finalizeTimeoutMs`。最后一项为排空预算＋识别预算＋1000 毫秒。以创建/ready 快照为准，不在 UI 按品牌写死时长。

## 可用工作流

| 提供方 | 输入／预览 | 稳定单位／完成边界 | 录音上限 |
| --- | --- | --- | --- |
| 豆包 | 持续上传／录音中 | 分句／上游完成 | 300 秒 |
| 百炼 | 持续上传／录音中 | 分句／上游完成 | 300 秒 |
| LocalASR WS | 持续上传／时机未知 | 分句／上游完成 | 300 秒 |
| Soniox | 持续上传／录音中 | 稳定 token／上游完成 | 300 秒 |
| Boson | 持续上传／无预览 | 手动轮次／匹配结果完成 | 300 秒 |
| LocalASR HTTP | 完整录音／无预览 | 整轮／完整 JSON | 60 秒 |
| OpenAI 文件 JSON | 完整录音／无预览 | 整轮／完整 JSON | 300 秒 |
| OpenAI 文件 SSE | 完整录音／停录后 | 整轮／SSE done | 300 秒 |
| OpenAI live | 持续上传／录音中 | 手动轮次／匹配结果完成 | 300 秒 |
| OpenAI committed-turn | 持续上传／commit 后 | 手动轮次／匹配结果完成 | 300 秒 |

## 有序 v1 输出

公共转写由按音频顺序排列的不可变前缀和一个可替换预览尾部组成。`seq` 是发送顺序，不是音频顺序证据。发布 final 前校验供应商身份及前驱、句号或完整历史。相同文字、相同时间戳不构成重复身份；稳定文本冲突报 `UPSTREAM_PROTOCOL_ERROR`。

一个公共 utterance 可以合并多个上游单位。A 等待修正而 B 已稳定时，二者仍在预览中，直到 A 稳定。若 A 先稳定，则发布 A 的 final，再用新公共 ID 发布剩余 B 预览。因此 final 可以短于先前预览。partial 完整替换当前尾部，允许空文本撤回；空 final 关闭撤回单位并计入 `finalCount`。

所有已登记单位（包括空候选）必须稳定且顺序无缺口才能成功。finalCount 统计公共发布单位，不是上游句子数。缺失前驱、未完成候选、连接 EOF 都不能制造成功。客户端只追加每个唯一 final 一次，不通过回滚已提交文字修补上游改写。

## 音频与生命周期

状态为 connecting → receiving → draining → finalizing → terminal。ready 前音频与 `audio.end` 无效，取消仍可用。end 幂等，只发布一个终态，发送和清理均有界。

源音频保持 PCM16/16 kHz/单声道。零样本本地完成，不提交文件或 commit；非零静音正常交付。持续上传保留供应商节奏；Boson 必须排空内部 uploader 才完成 commit 屏障。文件适配器有界缓存、密封一次、请求一次。固定 Content-Length 的 HTTP body 在最后字节写入并 drain 后确认本地提交，不等待响应，也不以 yield 当作写完。不自动重传音频、不加本地 VAD、不反复提交文件制造预览。

75 秒上传预算从正常或配额触发 end 开始，供应商识别预算从真实提交后开始。排空超时为 `UPLOAD_TIMEOUT`，识别等待超时为 `FINALIZATION_TIMEOUT`。finished 报告源采样率下的 `acceptedAudioSamples`、`submittedAudioSamples`；配额结束另报 `truncated: true` 及既有 reason/scope。配额结束后的在途音频可丢弃。计数不表示逐包供应商 ACK 或处理进度。

完整录音准入按最大源 PCM 大小预留全局 64 MiB 缓存。WAV/base64/multipart 分块封装，不额外生成整份编码副本。音频只驻留内存，上传或清理时释放。当前文件路径是一次有界 HTTP 请求（JSON/SSE），不是轮询任务；没有持久异步 job、恢复或公共长文件上传 API。

OpenAI Realtime 按需加载 numpy/SoXR，每轮保留一个连续 16→24 kHz 转换器，结束仅 flush 一次；其他路径不重采样。见 [OpenAI 设置](openai-api-setup.zh-CN.md)与[验收要求](testing.zh-CN.md)。

## 用量

本地音频配额按已接受源样本只扣一次。供应商报告独立保存：OpenAI 按 request/item 作用域区分 `tokens`、`duration`、`unknown`，累计报告去重，秒数不换算成 token。缺少用量不算零。上游只报 duration 或缺少 token 时，Token 限额账户沿用缺失报告后的阻断规则；取消不承诺云端退费。
