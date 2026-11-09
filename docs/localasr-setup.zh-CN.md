# 将 OpenLocalASR 接入 Portal

[English](localasr-setup.md) | **简体中文**

适用于 Portal 1.1.1 与 OpenLocalASR 0.14.0。LocalASR 在自己的机器运行模型，没有独立设置网页。安装及准备模型权重见 [LocalASR 使用手册](https://github.com/MarmaladeCat/OpenLocalASR/blob/main/docs/user-guide.zh-CN.md)。

## 准备识别服务

1. 选择匹配 CPU 的 Linux/Windows 包或 Linux Docker 部署。软件包不包含模型权重；将所需模型下载到服务启动时使用的同一模型目录。
2. 为服务设置并保存私有的 `OPENLOCALASR_API_KEY`，在 Portal 上游填写同一值。它与 Portal 客户端 ASR Key 是不同的凭据。
3. 启动 LocalASR 并加载模型，首次可用 `funasr_sensevoice_small`。检查公开 `/health` 和需认证的 `/v1/models`：服务应为 ready，活动模型须与预期一致。API 可达或权重已下载都不等于推理就绪；每个实例只有一个活动模型。

## 填写 Portal 卡片

打开 `/admin` → **上游 ASR 接入 → 增加服务接入**；修改已有卡片时先点 **编辑**。

| 字段 | 首次填写 |
| --- | --- |
| 配置 ID / 名称 | 例如 `local-main` / “本地识别” |
| 提供商 | OpenLocalASR |
| WebSocket 地址 | 同机且非容器服务：`ws://127.0.0.1:10095/api-ws/v1/inference` |
| 模型 | 实际活动模型 ID，首次可用 `funasr_sensevoice_small`，不是文件路径 |
| 上游 API Key | 服务的 `OPENLOCALASR_API_KEY` 值 |
| 使用代理 | 本机/局域网接入通常关闭 |

此地址由 Portal 访问，不是浏览器访问。两个容器应使用共同网络中的服务名，例如实际服务名为 `localasr` 时可用 `ws://localasr:10095/api-ws/v1/inference`。容器内回环地址指容器自身。远程 TLS 部署使用证书有效的 `wss://` 地址，路径保持一致。

点击 **测试上游连接**，测试使用当前表单/代理选择，结果显示在卡片内。成功不代表保存：点击 **保存**、保持 **启用**，再设为默认或从客户端选择。**取消**放弃修改。确需代理时先配置并测试全局 HTTP/HTTPS 代理，已开启但不可用时不会回退直连。

## 验证识别与排查

客户端填写 Portal 的 HTTP(S) 地址和 Portal 派生的 ASR Key。使用支持中英文的模型分别录制短句，停止后等待定稿。页面语言下拉框不是模型语言设置；此适配器没有语言列表字段，识别语种和预览能力取决于所选 LocalASR 模型。

- 连接拒绝/超时：检查服务监听地址、发布端口、容器网络及后端路由。
- 未授权：上游填写 LocalASR 服务 Key，不是 Portal 管理密码或客户端 ASR Key。
- 模型不匹配/未就绪：检查 `/v1/models`、权重目录和 loading/error 状态。切换模型影响整个 LocalASR 实例。
- 健康检查正常但识别失败：检查模型运行依赖并用真实音频验证，健康检查只表示服务存活。此上游不支持会话热词和 Token 计量，应使用时长额度。
