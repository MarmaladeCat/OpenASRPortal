# OpenASRPortal 测试约束

[English](testing.md) | **简体中文**

## 代理验证

代理检查使用一次性 HTTP/HTTPS CONNECT 代理和本地受信任的 WSS 回显/协议服务，覆盖二进制、文本与空文本帧，代理/上游认证隔离，显式直连、不回退、认证拒绝、超时与取消清理，加密持久化、仅管理端可见的脱敏设置、公开连接测试/识别路由及双语设置界面。这些模拟端点验证传输，不代表云端识别验收。开发解释器之外，还需在打包运行时重跑传输测试。

百炼和 Soniox 通过模拟 WebSocket 测试停止前 partial、稳定且不重复的 final、服务端错误、完成标记、原始 PCM 和状态上限。公开 v1 测试覆盖配额截断、探测、取消/超时、累计 Token 计量和限额账户串行，迁移保留旧 Key/地域/额度。UI 覆盖流式模型字段、移除预览间隔、Soniox 配置及中英文。这些测试不代表真实云端识别或延迟；真实验收需要提供商凭据、公开中英文音频、停止前 partial、结束到定稿计时及 test-results/ 中的实际用量记录。安装器和原生输入仍需按平台验收。

本文件是本产品开发与发布的验收约束；测试清单见 [可执行场景](../tests/functional/manifest.json)。
必须能在只克隆本仓库的环境运行，不依赖父仓库或其他产品的源码/解释器。

## 本仓库内启动测试

Python 3.10+；网页回归使用 Node.js 22.13+/Electron 测试工具，服务本身不依赖它们。Linux UI 使用 Xvfb，Windows 使用隔离交互桌面。

```bash
python scripts/test.py list --suite core
python scripts/test.py setup --suite unit
python scripts/test.py run --suite unit --allow-skips
python scripts/test.py setup --suite core
python scripts/test.py run --suite core
python scripts/test.py setup --suite ui
python scripts/test.py run --suite ui
```

`setup` 只在本产品 `.cache/functional/` 建立 Python 测试环境；桌面依赖放本产品 node_modules/，浏览器测试工具放本产品 `.cache/test-lab/ui/`。
实际应用运行仍使用自己的运行时。每次 run 在本产品 test-results/functional/ 下产生新的报告与日志。
`--case <ID>` 可以定位单项，不能用单项通过代表整个产品通过。

## 必须覆盖的行为

Boson 适配测试使用模拟 WebSocket 覆盖手动轮次初始化、定稿顺序与去重、空音频、错误与断连、有界积压、等待转写时取消、公开 v1 定稿、时长额度和探测计量。配置 UI 测试覆盖 Boson 字段、中英文切换和密钥保留。真实云端验收使用仓库外的临时 Boson Key，回放公开的 16 kHz PCM 讲话音频，包含两个有停顿的语段；音频哈希、事件耗时/finalCount 和用量保存在 test-results/。静音探测、真实识别、麦克风输入及安装包验收分别记录。

| 层次               | 必测内容                                                                                               |
| ------------------ | ------------------------------------------------------------------------------------------------------ |
| unit / core        | 首次设置、认证/退出、profile 和 Key 隔离、HTTP/WS v1、revision/final/取消、配额/用量、热词与重启持久化 |
| UI                 | 首次设置/登录/注销、profile 增改查删与密钥保留；模拟上游                                               |
| 原生 / 安装 / 服务 | Docker 健康/认证/数据卷重建；Linux deb、Windows MSI 安装/升级/卸载；真实上游需单独配置临时 Key         |
| 性能               | 建会话与 WS ready 延迟、首字/尾字延迟、并发吞吐、错误率、CPU/RSS                                       |

包级检查入口示例（须先构建匹配平台的候选包）：

```bash
python tests/check_container.py --image openasrportal:test
```

## 结果规则

- 测试失败返回非零；环境、依赖或真实设备不足记录为阻塞，不能改为 passed。
- unittest 的 skipped 计入报告，状态为 incomplete；默认返回非零。日常 `--allow-skips` 可允许退出成功，但报告仍不完整，不能作为平台发布验收。
- 仅测试模拟上游/合成音频时，只能声明业务/协议通过，不能声明真实识别、真实麦克风或实机输入通过。
- 发布目标按 OS、CPU、桌面/输入框架、安装形态分别验收。未测的平台不能复制其他平台的通过状态。
- 构建后源码、依赖锁或资源变化应重新确认候选包与源码的一致性。不能用历史报告替代当前候选。
- 测试使用临时 HOME、端口、配置、数据库和虚构 Key，不访问正式用户数据，不重启用户桌面/输入法。

## 性能回归约束

同一机器/系统/解释器/依赖、固定输入和固定资源哈希；固定 CPU 线程与服务配置。
先预热，再交错运行基线与候选各至少 5 次，记录全部原始样本以及中位数、p95、错误率和峰值内存。
功能与准确率必须同时满足。核心指标中位数劣化超过 10% 或 p95 超过 15% 时，阻止“性能无退化”结论并调查；噪声或样本不足标为未确认。
`core` 的整套执行耗时只是回归耗时，不能代替用户操作延迟或真实 ASR RTF。
基线、测量报告和性能采样放 test-results/，不在源码中保存旧产品发布状态。

## 测试环境归属

Dockerfile、Compose 模板、测试脚本与依赖锁属于可复现源码，可以提交。
容器导出、镜像层、VM 磁盘、ISO、快照、配置秘密、录音和运行报告均放 `.cache/` 或 test-results/，不得纳入 Git。
仅回收本次测试创建的进程、容器和卷；共享 VM 必须隔离实例与正式数据。

## 使用手册配图来源

`docs/images/linux-admin.png`：1.0 源码服务，Linux amd64/Chrome；`windows-admin.png`：1.0.0 MSI 解包的服务，Windows 11 amd64/Edge。每次使用新数据目录、回环端口和浏览器 profile，通过真实管理 API 完成初始化并建立“本机识别（演示配置）”，进入“上游 ASR 接入”后捕获。

图中 Key 为仅用于临时实例的演示值，界面不展开原值；没有发起云识别或 LocalASR 连接测试。图用于说明档案、默认项和余额操作，不是安装服务、真实识别或额度计量验收。原始脚本、日志、数据库留在 test-results/，只提交人工审核的截图。
