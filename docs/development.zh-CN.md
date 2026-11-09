# OpenASRPortal 开发与发布

[English](development.md) | **简体中文**

旧百炼 HTTP 档案读取时规范化为流式模型及 WSS 路径，保存时持久化；不要重新引入 HTTP 预览请求。流式用量按任务累计，不是每事件独立用量；保留历史数据库预留列兼容，但新流不使用。Soniox 稳定词只累积一次，临时词替换后缀；端点/结束定稿不能重复文字。协议修改需配套提供商测试和双语配置契约。

本服务源码使用 Python 3.10+、aiohttp 与本产品 SQLite。无需 Electron 或模型运行时；浏览器回归的工具另行安装。协议参考 [客户端 API](API.zh-CN.md) 和 [管理 API](MANAGEMENT.zh-CN.md)。

## 本地开发

当前源码目录与迁移见 [安装生命周期](installation.zh-CN.md)。`openasrportal --provision-local-input --installed --client-id ID --output 文件` 是安装所有者命令，调用前停止服务并保护接收者交接文件。`openasrportal --open-setup --url-file 文件` 根据公开认证状态决定是否打开浏览器。合体构建器用 `python scripts/release.py --source-digest` 获取源码指纹。翻译目录由本产品独立维护；UI 测试覆盖两种语言下的首次设置与管理页面，确保不丢失草稿、不翻译用户数据。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m openasrportal --data-dir runtime/portal --host 127.0.0.1 --port 10087
```

Windows 对应使用 `py -3.12 -m venv .venv` 和 `.venv\Scripts\python.exe`，相同模块命令可运行。打开 `/admin` 完成首次密码设置；数据目录独立，不读取真实部署数据库。配置 host、port、data 可用 `OPENASRPORTAL_HOST/PORT/DATA`，管理与识别凭据从数据库管理，旧的凭据环境变量不生效。

## 迭代与验证

```bash
python scripts/test.py setup --suite unit
python scripts/test.py run --suite unit --allow-skips
python scripts/test.py setup --suite core
python scripts/test.py run --suite core
```

网页改动增加 ui；识别适配器改动覆盖事件修订、计量、结束/取消和真实上游。遵守 [测试约束](testing.zh-CN.md)，跳过不能当作完整验收。Python 使用本仓库 Ruff 配置；网页遵循现有 JS/CSS 格式。

## 固定构建环境

```bash
python scripts/build.py --deployment local --arch amd64
python scripts/build.py --deployment docker --arch amd64
# Linux ARM64 改为 --arch arm64；Windows 在隔离客体执行
python scripts/build.py --deployment windows --arch amd64 --wix-bin <WiX目录>
```

deb 使用 Ubuntu 22.04 / SHA256 固定的 Python 3.12.10 / PyInstaller 6.16.0；镜像使用 Python 3.12.10 / Debian 12。DEB 私有解释器支持 HTTPS 代理双层 TLS，并保持 Ubuntu 22.04 的 libc 基线。源码安装使用 HTTPS 代理需 Python 3.11+。MSI 构建编排使用原生 Windows Python 3.12.10 与 WiX 3.14.1，包内私有运行时为 Python 3.13.16、服务包装器 WinSW 2.12.0。构建配方在 packaging/，入口再调用 `build_portable_deb.py`、`build_image.py` 或 `build_windows.py`，不依赖外层源码。

候选在 `.cache/build/artifacts/<系统>/<架构>/<变体>/`，发布到 `release/1.1.0/`。VERSION 与工具包版本均为 1.1.0。目录平铺 deb、镜像部署包、MSI、文档 ZIP、中英文 README、manifest.json 与 SHA256SUMS；Docker 包包含真实 image.tar 和手写部署说明。dist/ 不作为输出目录。

发布器检查来源、唯一候选、版本、架构和哈希后替换目录，同源的其他平台产物合并保留。构建成功不代表已完成服务安装、升级、卸载或真实识别验收；运行记录放 test-results/。

## 部署维护边界

数据库迁移应保留档案、Key、撤销状态、热词及用量。备份整个数据目录，包括 `asr-key-vault.key`。离线密码恢复入口为 `python -m openasrportal.entrypoints.admin --data-dir <实际目录>`，仅交互输入新密码，不接收明文密码参数。

独立安装不自动配置 Input；Windows 联合 MSI 仅通过两产品公开所有者入口和受 ACL 保护的交接文件建立连接，不共享数据库。旧配对 API 为 v1 兼容保留，见管理协议。

## 文档与 Git

公开软件包命名为 `OpenASRPortal_<版本>_<系统>_<架构>.<后缀>`，Docker 部署包也采用该格式，以 `.tar.gz` 结尾。GitHub Release 附件只上传软件包及对应的 `.sha256`，人工版本说明及文档链接放正文。本地发行目录保留文档与来源记录。

单独预览文档时，先创建 `test-results/`，再运行 `python scripts/release.py --docs test-results/product-docs.zip`。全部人工 Markdown、图片和链接附件保留原始字节与相对目录。平铺发行目录在相同内容的 README 副本旁保留 `release.md` / `release.zh-CN.md`，确保语言链接有效。

docs/ 人工维护：用户操作、客户端/管理协议、架构、开发发布、测试约束、版本说明。`docs/release.md` 同时作为发行目录 README 的原文，文档 ZIP 原样保存目录和截图。自动报告、清单和校验和是机器证据，不替代人工说明。

提交源码、模板、锁定依赖、配方、测试、精选演示图与当前文档；忽略真实配置、数据库、Key、日志、测试截图原件、环境、VM 和发布包。保留第三方授权。先发布产品提交再更新外层 gitlink，实际提交由维护者审核。
