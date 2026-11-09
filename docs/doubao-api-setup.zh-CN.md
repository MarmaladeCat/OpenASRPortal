# 开通豆包语音 API 并接入 Portal

[English](doubao-api-setup.md) | **简体中文**

本文介绍如何在火山引擎中创建项目、开通**豆包流式语音识别 2.0**，然后将 API Key 绑定到 OpenASRPortal **1.1.0** 的上游。

## 1. 登录火山引擎

打开 [火山引擎豆包语音控制台](https://console.volcengine.com/speech/new/overview?projectName=default)，登录账号。没有账号时先注册，并按页面提示完成实名认证及首次服务开通。

## 2. 新增项目

1. 点击页面最上方的**项目选择**下拉框。
2. 点击 **管理项目**，进入项目管理页面。
3. 新增一个项目，填写项目名称，例如 `openasr`，然后确认创建。
4. 返回豆包语音控制台，在顶部项目选择中选中刚创建的项目。

后续开通模型和创建 API Key 都在这个项目下完成。

## 3. 开通流式语音识别 2.0

1. 点击左侧 **开通管理**。
2. 找到 **豆包流式语音识别模型 2.0**，点击 **开通**。
3. 按页面提示确认服务协议并完成开通。本教程使用**小时版**。

新用户一般赠送 **20 小时**免费使用额度，免费额度用完后，按量计费价格为 **1 元/小时**。赠送资格、额度有效期和实际价格以控制台显示为准，可在资源及费用页面查看。

## 4. 创建 API Key

1. 确认顶部仍选中刚创建的项目。
2. 进入 **API Key 管理**（部分页面称 **API 管理**）。
3. 创建一个 API Key，按页面要求填写名称，例如 `openasrportal`。
4. 复制并保存完整的 API Key，下一步填写到 Portal 中。

这里使用新版豆包语音控制台的 **API Key**。如果页面显示的是旧版 `APP ID` 和 `Access Token`，请切换到新版控制台获取 Key。

## 5. 将 API Key 绑定到 Portal 上游

1. 打开 Portal 管理页，本机默认地址为 `http://127.0.0.1:10087/admin`，登录后进入 **上游 ASR 接入 → 增加服务接入**。
2. 按下表填写：

| 字段 | 填写内容 |
| --- | --- |
| 配置 ID | 例如 `doubao-main` |
| 显示名称 | 例如“豆包语音 2.0” |
| 提供商 | 豆包 · 实时语音识别 |
| 上游 API Key | 刚创建的 API Key，只填写 Key 本身 |
| WebSocket 地址 | 保留页面提供的只读地址 |
| 模型资源 | 2.0 小时版：`volc.seedasr.sauc.duration` |
| 二遍识别 | 保留默认开启 |

3. 点击 **测试上游连接**，成功后点击 **保存接入配置**。
4. 如需默认使用豆包，在该上游卡片点击 **设为默认**。

至此，豆包 API Key 已绑定到 Portal 上游。可在客户端选择该档案，录制一句短语验证识别结果。客户端连接配置见 [Portal 使用手册](user-guide.zh-CN.md)。

## 常见问题

- **提示无权限或资源未开通**：确认模型和 API Key 在同一个项目中，模型资源选择了 `volc.seedasr.sauc.duration`。
- **提示鉴权失败**：重新核对完整 Key，不要添加 `Bearer` 前缀，也不要填写旧版 Access Token。
- **免费额度用完后无法识别**：检查火山引擎账户余额及服务状态，同时检查 Portal 上游档案的本地额度。Portal 本地额度不等于云账户余额。
- **测试成功但客户端不能使用**：确认已保存并启用档案。客户端应使用 Portal 派生的 ASR Key，云平台 API Key 填在 Portal 上游中。

## 官方参考

- [控制台指引：项目、模型开通与 API Key](https://docs.volcengine.com/docs/6561/2485392?lang=zh)
- [双向流式语音识别 WebSocket](https://docs.volcengine.com/docs/6561/2630027?lang=zh)
- [计费说明](https://docs.volcengine.com/docs/DoubaoVoice/Billinginstructions-21?lang=zh)
