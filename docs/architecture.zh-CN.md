# OpenASRPortal 架构与设计

[English](architecture.md) | **简体中文**

Portal 是协议与权限边界：下游只看到统一识别会话，上游细节由服务端适配。它不采集麦克风、不操纵输入法，也不加载本地模型权重。

## 源码分层

`src/openasrportal/entrypoints` 负责服务与离线管理入口；`api` 处理 aiohttp 路由、认证、请求与 WS 生命周期；`application` 编排会话、用量与热词；`domain` 定义规则与能力；`providers` 封装云服务和 LocalASR 的差异；`storage` 管理本产品 SQLite 与密钥保管；`presentation` 提供静态管理网页和内置推荐资源。

服务启动组合 `Store` 与 `Portal`。生产运行、Windows 服务和测试都使用同一业务组合点，外层工作区不能导入这些实现。

## 会话生命周期

创建时验证 ASR Key、音频、档案、额度与容量，固定提供商配置和热词快照，签发短期一次性 ticket。WS 消费 ticket 后连接上游，ready 后允许 PCM；正常结束 flush 尾部音频并等待定稿，取消和错误进入独立终态。

`providers/registry.py` 独立于 legacy bridge 定义构造器、能力和有效限制；`application/recognition.py` 管理接收、排空、定稿、取消、预算和清理。适配器按 wire 协议生成带身份、音频顺序和稳定性的类型化 `ProviderEvent`；`domain/transcript.py` 校验修订与连续稳定前缀，`domain/events.py` 投影为有序 `seq/utteranceId/revision`。partial 整体替换尾部，final 不可变，finished 统计公共发布单位。默认档案影响下一会话；活动文本不跨模型拼接。额度、停用、撤销仍实时检查。

持续上传适配器实现 open/write/finish/receive/close；`finish_input()` 包括内部队列排空与真实 commit 写出。`BufferedFileProvider` 有界预留源 PCM，end 后仅请求一次 JSON/SSE HTTP；固定长度 body 的最后字节写入并 drain，与结果完成独立。零音频及提交前取消不产生文件请求。目前未实现持久异步 job 或轮询适配器。见[识别契约](recognition-contract.zh-CN.md)。

## 认证与数据归属

- 管理密码以随机盐 scrypt 哈希保存；登录令牌只保存摘要，默认 30 分钟过期。
- ASR Key 的认证摘要与可选查看用加密副本分开。Fernet 保管文件 `asr-key-vault.key` 与 `portal.db` 需要一起备份。
- 上游 Key 仅在 Portal 使用；配置查询脱敏。短期管理 token 不授权识别，ASR Key 不授权管理。
- 每 Key 的热词与快照互相隔离，公共推荐表独立持久化并有自己的 revision。下载推荐不等于启用个人词。

用量与余额在事务中更新，本地配额按已接受源样本只扣一次。百炼 task、OpenAI request/item 的 Token 只扣累计增量；duration 和 unknown 独立保存，不换算成 Token。最终 Token 报告缺失时阻断限额账户并保留已知扣费。文件请求计数从提交时开始，而非缓存准入。限额会话持锁至清理，重启标记中断但不抹去用量。Soniox 云端连接时长与本地音频配额不同。Portal 不持久化录音／完整转写；自动学习仅保存词级统计。

## 扩展方式

OpenAI 文件与 Realtime 仅共用该供应商的配置、错误和用量辅助。Realtime 确认有效 transcription 会话，以单个 SoXR 滤波器连续 16→24 kHz 转换，禁用 VAD、每轮仅 commit 一次；文件保持源采样率 WAV。SSE framing、结果账本和文件生命周期可复用，供应商事件身份仍由专用适配器解释。见 [OpenAI 设置](openai-api-setup.zh-CN.md)。

百炼使用 `qwen-audio-3.1-asr-flash-streaming`、DashScope 双向任务、二进制 PCM 和服务端分句，没有重复 HTTP 识别。旧 HTTP 档案读取时迁移模型/协议/路径，保存后持久化，保留 Key 和账户身份。Soniox 使用 `stt-rt-v6`、握手鉴权、稳定前缀/临时后缀更新和语义 `<end>` 边界。结束音频需等待上游完成；断连不能把临时文字提升为定稿。见 [百炼](bailian-api-setup.zh-CN.md) 和 [Soniox](soniox-api-setup.zh-CN.md)。

Boson 适配器完整流式发送每个 PCM 样本，使用手动轮次及 `higgs-stt-3.1` 输入转写。只在音频结束时提交整轮，不做本地静音、能量或 15 秒分段，不裁剪音频。匹配本轮的输入转写完成事件产生 final，重复 item ID 和助手输出被忽略。详见 [Boson 配置](boson-api-setup.zh-CN.md)。

增加 provider 时实现能力、连接、事件转换、计量及错误映射，并通过管理 `contract` 暴露字段。客户端按契约渲染，不能复制提供商内部配置逻辑。先验证模拟协议与边界，再用真实上游验证准确率、延迟和预算，见 [测试约束](testing.zh-CN.md)。

[客户端协议](API.zh-CN.md) 定义外部承诺，[管理协议](MANAGEMENT.zh-CN.md) 定义管理操作；数据库结构和 Python 类不属于跨产品 API。
