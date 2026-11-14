# OpenASRPortal 1.2.0 版本说明

[English](release.md) | **简体中文**

## 上游代理

上游面板支持就地只读/编辑、启用与代理开关及面板内测试结果；代理可用性与耗时测试；语言下拉框及页面刷新图标。新建 Soniox 档案使用 `zh,en` 提示，面向大量中文夹杂少量英文；提示顺序不代表权重。

全局 HTTP/HTTPS Proxy 设置支持加密保存可选认证，每个上游档案独立选择是否使用。连接测试和识别使用相同路由；代理失败不静默回退直连。

[OpenASRInput](https://github.com/MarmaladeCat/OpenASRInput) 通过 Portal 提供系统语音输入，合体包计划放在 [Input Release 页](https://github.com/MarmaladeCat/OpenASRInput/releases)。每个安装包配同名 `文件名.sha256`，每份只含对应包的一行校验记录。

1.2.0 安装包包含百炼/Soniox 流式识别、Boson AI Higgs STT、每上游独立代理选择、统一目录、保留配置重装、按需首次设置和中英文切换，详见 [安装说明](installation.zh-CN.md)。

产品与包工具版本均为 1.2.0；客户端与管理协议均保持 v1。全部文档提供英文默认入口及中文链接。本说明描述功能范围，具体平台验收随候选包单独记录。

## 本版能力

- 类型化上游结果形成按音频顺序的不可变前缀与可替换预览尾部，支持交错二遍结果。上传排空与识别分别计时，真实 commit／body 写出完成后才开始识别预算。
- 独立 [OpenAI 文件 JSON/SSE 与 Realtime](openai-api-setup.zh-CN.md) 档案，以及完整录音 LocalASR HTTP。[能力及有效限制](recognition-contract.zh-CN.md) 区分录音中预览和停止后出字。文件仅提交一次，源 PCM、request/item Token、duration 和 unknown 用量分别计量。

- 独立读取控制消息，初始化、上传与最终发送阻塞时仍可取消；有界上传队列、协调的 ready 预算、鉴权/配置错误的不可重试分类，以及豆包缓存音频实时配速。上游音频提交完成后才开始定稿计时。

- 百炼改为 `qwen-audio-3.1-asr-flash-streaming` 真正双向流式调用，支持旧 HTTP 档案迁移及累计 Token 计量；移除重复 HTTP 预览与间隔设置。
- Soniox `stt-rt-v6` 实时 STT，支持稳定/临时词处理、语义端点、上下文热词、取消及音频时长额度。见[配置与计费口径](soniox-api-setup.zh-CN.md)。

- Boson AI Higgs STT：完整实时上传音频，仅在录音结束时手动提交整轮，支持语言提示和时长额度。移除本地静音裁剪与 15 秒强制切段。详见[开通与限制](boson-api-setup.zh-CN.md)。
- Soniox 默认关闭端点检测，豆包新档案关闭二遍 VAD，静音窗口为 300–5000 ms、默认 5000。豆包旧越界值迁移到最近边界，合法值和二遍开关保留。百炼独立保留 200–6000 ms 范围及新档案默认 6000 ms；文本标点仍由上游决定。
- v1 增加显式版本/能力、创建参数冲突检测、收尾期间取消及唯一终态/未定稿检查；[独立 Python 客户端](python-client.zh-CN.md)可用于第三方接入。
- 录音与提供方收尾使用独立截止时间。Boson 大帧上传逐传输块让出调度，同时保持有界积压。豆包终包不会把非 definite 文本升级为定稿；Soniox 正常结束允许撤回临时尾部，只提交稳定文本，必要时通过空 final 清除预览。

- HTTP 创建会话、一次性 WS ticket、统一 partial/final 和结束/取消事件。
- 数据库管理密码、短期管理会话、多客户端 ASR Key、撤销和加密查看。
- 云服务与 LocalASR 档案、默认选择、额度和顺序切换。
- 个人热词、公共推荐表、版本冲突保护及真实用量计量。
- 独立管理网页；Linux 本地、Docker 与 Windows 服务部署。

## 下载与文档

软件包使用 `OpenASRPortal_1.2.0_<系统>_<架构>.<后缀>`：Linux 服务为 `.deb`，Docker 部署为 `.tar.gz`，Windows 为 `.msi`；按 amd64/arm64 选择。独立安装不自动配置录音客户端。

GitHub Release 附件只保留软件包及各自的 `.sha256`。在线阅读[使用手册](user-guide.zh-CN.md)、[客户端协议](API.zh-CN.md)和[管理协议](MANAGEMENT.zh-CN.md)。本地构建目录保留文档归档、manifest.json 和 SHA256SUMS。Docker 部署包包含镜像及部署材料，实际运行部署命令使用包内平铺布局。

## 升级和兼容

先备份整个数据目录，包括 portal.db 与 asr-key-vault.key。迁移保留档案、识别 Key、撤销状态、热词、配额与用量。管理员密码不从旧环境变量导入；没有管理员记录时在本机首次设置。旧的纯环境变量识别 Key 需要重新派生。

默认回环监听。健康成功只表示服务存活；真实识别仍需要可用上游。LocalASR 不支持会话热词；Token 缺失不算零用量。安装、升级、卸载、远程 HTTPS 与真实云识别各自验收。
