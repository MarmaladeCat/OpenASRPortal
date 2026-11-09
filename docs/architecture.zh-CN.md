# OpenASRPortal 架构与设计

[English](architecture.md) | **简体中文**

Portal 是协议与权限边界：下游只看到统一识别会话，上游细节由服务端适配。它不采集麦克风、不操纵输入法，也不加载本地模型权重。

## 源码分层

`src/openasrportal/entrypoints` 负责服务与离线管理入口；`api` 处理 aiohttp 路由、认证、请求与 WS 生命周期；`application` 编排会话、用量与热词；`domain` 定义规则与能力；`providers` 封装云服务和 LocalASR 的差异；`storage` 管理本产品 SQLite 与密钥保管；`presentation` 提供静态管理网页和内置推荐资源。

服务启动组合 `Store` 与 `Portal`。生产运行、Windows 服务和测试都使用同一业务组合点，外层工作区不能导入这些实现。

## 会话生命周期

创建时验证 ASR Key、音频、档案、额度与容量，固定提供商配置和热词快照，签发短期一次性 ticket。WS 消费 ticket 后连接上游，ready 后允许 PCM；正常结束 flush 尾部音频并等待定稿，取消和错误进入独立终态。

Portal 将不同上游结果转换为 `seq/utteranceId/revision` 账本。partial 可替换，final 稳定，finished 携带唯一 final 数量。默认档案变化影响下一会话；活动会话不在多个模型之间拼接正文。额度、停用与撤销仍在提交阶段实时核验。

## 认证与数据归属

- 管理密码以随机盐 scrypt 哈希保存；登录令牌只保存摘要，默认 30 分钟过期。
- ASR Key 的认证摘要与可选查看用加密副本分开。Fernet 保管文件 `asr-key-vault.key` 与 `portal.db` 需要一起备份。
- 上游 Key 仅在 Portal 使用；配置查询脱敏。短期管理 token 不授权识别，ASR Key 不授权管理。
- 每 Key 的热词与快照互相隔离，公共推荐表独立持久化并有自己的 revision。下载推荐不等于启用个人词。

用量与余额在事务中更新，流式音频样本只计量一次。百炼累计 Token 只扣增量，任务结束结算；最终用量缺失时暂停 Token 限额账户。限额流持有账户锁直到清理，重启标记中断但不抹去已知用量。Soniox 按连接时长计费，与 Portal 本地音频配额不同。Portal 不持久保存录音或转写全文；可选词频学习只存词级统计。

## 扩展方式

百炼使用 `qwen-audio-3.1-asr-flash-streaming`、DashScope 双向任务、二进制 PCM 和服务端分句，没有重复 HTTP 识别。旧 HTTP 档案读取时迁移模型/协议/路径，保存后持久化，保留 Key 和账户身份。Soniox 使用 `stt-rt-v6`、握手鉴权、稳定前缀/临时后缀更新和语义 `<end>` 边界。结束音频需等待上游完成；断连不能把临时文字提升为定稿。见 [百炼](bailian-api-setup.zh-CN.md) 和 [Soniox](soniox-api-setup.zh-CN.md)。

Boson 适配器流式发送 PCM，使用手动轮次及 `higgs-stt-3.1` 输入转写。本地静音或 15 秒边界触发提交，同一时刻仅允许一段待定稿；反压避免后段替换未完成转写。仅匹配当前分段的输入转写完成事件产生 final，重复 item ID 和助手输出被忽略。详见 [Boson 配置](boson-api-setup.zh-CN.md)。

增加 provider 时实现能力、连接、事件转换、计量及错误映射，并通过管理 `contract` 暴露字段。客户端按契约渲染，不能复制提供商内部配置逻辑。先验证模拟协议与边界，再用真实上游验证准确率、延迟和预算，见 [测试约束](testing.zh-CN.md)。

[客户端协议](API.zh-CN.md) 定义外部承诺，[管理协议](MANAGEMENT.zh-CN.md) 定义管理操作；数据库结构和 Python 类不属于跨产品 API。
