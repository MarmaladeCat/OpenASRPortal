# OpenASRPortal 1.0.0 版本说明

[English](release.md) | **简体中文**

产品与包工具版本均为 1.0.0；客户端与管理协议均保持 v1。全部文档提供英文默认入口及中文链接。本说明描述功能范围，具体平台验收随候选包单独记录。

## 本版能力

- HTTP 创建会话、一次性 WS ticket、统一 partial/final 和结束/取消事件。
- 数据库管理密码、短期管理会话、多客户端 ASR Key、撤销和加密查看。
- 云服务与 LocalASR 档案、默认选择、额度和顺序切换。
- 个人热词、公共推荐表、版本冲突保护及真实用量计量。
- 独立管理网页；Linux 本地、Docker 与 Windows 服务部署。

## 下载与文档

Linux deb 为 `*_local-service.deb`，镜像包为 `*_docker.tar.gz`，Windows 为 `*_native.msi`；按 amd64/arm64 选择。独立安装不自动配置录音客户端。

完整人工文档在 `OpenASRPortal_1.0.0_docs.zip`，解压后从 README.md 阅读，用户操作在 docs/user-guide.md，客户端协议在 docs/API.md，管理对接在 docs/MANAGEMENT.md。归档还保留 LICENSE、部署说明、Compose/NGINX 模板及证书脚本的源码相对路径；实际运行部署命令使用 Docker 部署包的平铺布局。核对 manifest.json 和 SHA256SUMS。

## 升级和兼容

先备份整个数据目录，包括 portal.db 与 asr-key-vault.key。迁移保留档案、识别 Key、撤销状态、热词、配额与用量。管理员密码不从旧环境变量导入；没有管理员记录时在本机首次设置。旧的纯环境变量识别 Key 需要重新派生。

默认回环监听。健康成功只表示服务存活；真实识别仍需要可用上游。LocalASR 不支持会话热词；Token 缺失不算零用量。安装、升级、卸载、远程 HTTPS 与真实云识别各自验收。
