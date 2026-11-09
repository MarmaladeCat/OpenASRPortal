# OpenASRPortal

[English](README.md) | **简体中文**

**1.1.1** · 统一语音识别接入服务。向客户端提供 HTTP/WebSocket v1，会话、上游档案、客户端 Key、热词、配额和管理网页；上游可连接云服务或 OpenLocalASR。

## 文档导航

系统语音输入请配合 [OpenASRInput](https://github.com/MarmaladeCat/OpenASRInput) 使用；其 [下载页](https://github.com/MarmaladeCat/OpenASRInput/releases) 也是 Input + Portal 合体安装包的分发入口。详见 [安装生命周期与语言选择](docs/installation.zh-CN.md)。

- **部署和操作**：[Windows / Linux 使用手册](docs/user-guide.zh-CN.md)。
- **云端 API 开通**：[豆包语音](docs/doubao-api-setup.zh-CN.md)、[百炼流式识别](docs/bailian-api-setup.zh-CN.md)、[Soniox 实时 STT](docs/soniox-api-setup.zh-CN.md)、[Boson AI Higgs STT](docs/boson-api-setup.zh-CN.md)，开通服务、创建 Key 并接入 Portal。
- **本地识别接入**：[连接 OpenLocalASR](docs/localasr-setup.zh-CN.md)，准备活动模型、服务 Key、网络地址和 Portal 上游卡片。
- **客户端开发**：[识别与个人热词 API v1](docs/API.zh-CN.md)。
- **管理工具开发**：[管理协议 v1](docs/MANAGEMENT.zh-CN.md)，包含认证、公共词表和用量计量。
- **内部实现**：[架构设计](docs/architecture.zh-CN.md)。
- **源码和交付**：[开发与发布](docs/development.zh-CN.md)。
- **验收要求**：[测试环境与约束](docs/testing.zh-CN.md)。
- **版本变化**：[1.1.1 版本说明](docs/release.zh-CN.md)。

源码服务需要 Python 3.10+，不需要 Node.js、Electron 或本地模型；原生安装包携带私有 Python。默认仅监听本机，首次打开 `/admin` 设置管理密码，再创建客户端 Key。

本仓库独立管理依赖、配置与 `portal.db`，不读取其他产品数据库。文档人工维护，演示截图可纳入源码；真实数据和凭据不可提交。

## 许可证

Copyright (C) 2026 OpenASRPortal contributors.

原创代码与文档按 **GNU GPL v3（GPL-3.0-only）** 授权，允许在该许可条件下使用、修改和再分发，包括商业用途；不提供担保。完整条款见 [LICENSE](LICENSE)。第三方组件保留各自版权和许可。分发软件包时应提供与其对应的源码和构建说明。
