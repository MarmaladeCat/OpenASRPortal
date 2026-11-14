# 第三方 Python 快速接入

[English](python-client.md) | **简体中文**

从[可复制 Python 示例](../examples/python/README.zh-CN.md)开始：`openasr_client.py`、WAV 命令行及一个依赖。只使用 Portal 公开 HTTP/WS，只需要客户端 ASR Key，不需要上游 Key 或数据库。

## 协议范围与扩展性

[v1 完整参考](API.zh-CN.md)覆盖能力发现、档案选择、会话/票据、PCM 传输、预览/修订、稳定定稿、取消、错误终态、额度和个人热词，适合第三方录音客户端。麦克风采集、任意音频编码、录音断点续传、翻译以及用 ASR Key 管理上游账号不属于该接口范围。

客户端读取 `/v1/capabilities` 的 `protocolVersion`、音频、事件类型和可选 `features`。可忽略新增字段；不兼容的新事件语义必须协商能力或升级协议版本。创建时可填写 `protocolVersion: 1` 和 `requiredFeatures`，不支持的版本/能力会在分配会话前拒绝。旧 Portal 缺少可选能力字段时，应视为能力不可用，而非默认支持。

## 生命周期保证

- 相同调用方/请求 ID/创建参数可复用未连接且未过期的描述；参数变化返回 `REQUEST_CONFLICT`，已连接返回 `SESSION_STARTED`。已完成会话不是永久幂等记录。
- ready 后才发音频，并行上传和接收。重复 audio.end 幂等；结束后继续音频返回 `INVALID_STATE`。等待定稿时仍可通过同一 WS 取消，也可用带认证的 DELETE。
- 序号和修订检测缺口/旧结果；唯一 final 不可改写，finalCount 与未定稿预览检查避免虚假成功。取消/定稿竞争时只产生一个终态。断连不等于成功。
- 接受的 PCM（含停顿）完整转发，传输块不负责断句。Boson 在音频结束时提交，Soniox 默认关闭端点检测，豆包/百炼仍有上游语义处理；不能保证上游标点与用户心中的句界完全一致。

示例拒绝 HTTP/WS 重定向，并核对精确的同源 streamPath；不会自动重连或重放，会回收上传/接收任务并只清理自己创建的会话。HTTP 错误读 `error.code`，WS 错误读 `session.error`，按错误码而非翻译文案分支。限制及恢复方式见 API 参考。

## 验证

从独立 Portal 仓库运行 `python scripts/test.py run --suite unit --allow-skips`。示例测试使用本机 HTTP/WS 和模拟文本，检查 ready 前不上传、仅返回定稿、重定向、异常断连及取消。这些检查不代表真实云识别、麦克风质量或平台安装验收。
