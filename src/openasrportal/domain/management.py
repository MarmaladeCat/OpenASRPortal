"""管理协议 v1：提供方拥有表单字段契约，所有客户端按协议渲染。"""

from .config import BAILIAN_LANGUAGES, DOUBAO_RESOURCES, config_defaults


def field(key, label, kind="text", **attributes):
    return {"key": key, "label": label, "type": kind, **attributes}


def contract():
    secret = field("apiKey", "上游 API Key", "secret", required=True, retainWhenOmitted=True)
    languages = [{"value": value, "label": {
        "auto": "自动识别（含英文、中文）", "en": "英文", "zh": "中文",
    }.get(value, value)} for value in BAILIAN_LANGUAGES]
    definitions = [
        (
            "openlocalasr",
            "OpenLocalASR · 本地语音识别",
            [
                field("endpoint", "WebSocket 地址", required=True),
                field("model", "服务端当前模型", required=True),
                secret,
            ],
        ),
        (
            "openlocalasr_file",
            "OpenLocalASR · 完整录音文件",
            [
                field("endpoint", "HTTP WAV 地址", required=True),
                field("model", "服务端当前模型", required=True),
                secret,
            ],
        ),
        (
            "doubao_realtime",
            "豆包 · 实时语音识别",
            [
                field("endpoint", "官方 WebSocket 地址", readOnly=True),
                secret,
                field(
                    "resourceId",
                    "模型资源",
                    "select",
                    options=[{"value": value, "label": value} for value in DOUBAO_RESOURCES],
                ),
                field("enableNonstream", "二遍识别", "boolean",
                      description="开启会启用上游静音断句；关闭时使用上游语义分句。"),
                field("silenceMs", "断句静音（毫秒）", "number", min=300, max=5000, step=100,
                      description="仅二遍识别生效；默认 5000 毫秒以容纳思考停顿，允许 300–5000 毫秒。"),
            ],
        ),
        (
            "bailian_qwen_asr",
            "百炼 · Qwen ASR Streaming",
            [
                field(
                    "endpoint",
                    "百炼 WebSocket 地址（DashScope）",
                    required=True,
                    description=(
                        "使用北京或新加坡业务空间的 WSS 地址，路径为 /api-ws/v1/inference。"
                    ),
                ),
                field("model", "模型", readOnly=True),
                secret,
                field(
                    "language",
                    "识别语种",
                    "select",
                    options=languages,
                ),
                field("silenceMs", "断句静音（毫秒）", "number", min=200, max=6000, step=100,
                      description="由百炼上游断句；建议 6000 毫秒以容纳思考停顿。"),
                field("keepDialect", "保留方言表达", "boolean"),
            ],
        ),
        (
            "soniox_realtime",
            "Soniox · 实时语音识别",
            [
                field("endpoint", "官方 WebSocket 地址", readOnly=True),
                field("model", "模型", readOnly=True),
                secret,
                field("language", "识别语种", "select", required=True,
                      options=[{"value": "zh,en", "label": "中文为主，夹杂英文"},
                               {"value": "en,zh", "label": "英文、中文"}, *languages],
                      description="默认 zh,en，面向中文为主、夹杂英文；提示顺序不代表语言权重。"),
                field("endpointDetection", "上游自动端点检测", "boolean",
                      description="默认关闭；稳定 token 有序提交，可变尾部继续预览。开启后上游另发端点标记。"),
                field("endpointDelayMs", "最大端点延迟（毫秒）", "number", min=500, max=3000, step=100),
            ],
        ),
        (
            "boson_realtime",
            "Boson AI · Higgs STT",
            [
                field("endpoint", "官方 WebSocket 地址", readOnly=True),
                field("model", "模型", readOnly=True),
                secret,
                field(
                    "language", "识别语种", "select", required=True, options=languages,
                    description="auto 自动识别，或 zh / en 等两位语言代码；完整上传，停止录音后返回文本，无逐字预览。",
                ),
            ],
        ),
    ]
    providers = []
    for name, title, options in (
        ("openai_file", "OpenAI · 完整录音文件", [
            field("model", "模型", readOnly=True),
            field("responseMode", "文件响应模式", "select", options=[
                {"value": "json", "label": "完整结果"}, {"value": "sse", "label": "停止后逐步出字"}]),
        ]),
        ("openai_realtime", "OpenAI · Realtime 转写", [
            field("model", "模型", "select", options=[
                {"value": "gpt-live-transcribe", "label": "gpt-live-transcribe · 录音中预览"},
                {"value": "gpt-transcribe", "label": "gpt-transcribe · 提交后转写"}]),
            field("delay", "实时预览延迟档位", "select", options=[
                {"value": value, "label": value or "服务默认"}
                for value in ("", "minimal", "low", "medium", "high", "xhigh")]),
        ]),
    ):
        definitions.append((name, title, [field("endpoint", "官方转写地址", readOnly=True), secret,
                                        *options, field("languages", "预期语种（逗号分隔）"),
                                        field("prompt", "转写背景提示（最多 4096 字符）")]))
    for provider, title, fields in definitions:
        fields.append(field("useProxy", "使用全局 Proxy 代理", "boolean"))
        defaults = config_defaults(provider)
        providers.append(
            {
                "id": provider,
                "title": title,
                "fields": [
                    {
                        **definition,
                        **(
                            {"default": defaults[definition["key"]]}
                            if definition["key"] in defaults
                            else {}
                        ),
                    }
                    for definition in fields
                ],
            }
        )
    return {
        "protocol": "OpenASRPortal.Management",
        "version": 1,
        "providers": providers,
        "profilesPath": "/v1/admin/profiles",
        "settingsPath": "/v1/admin/settings",
        "proxyTestPath": "/v1/admin/proxy/test",
        "asrKeysPath": "/v1/admin/asr-keys",
        "usagePath": "/v1/admin/usage",
        "keyQuotaPath": "/v1/admin/asr-keys/{id}/quota",
        "profileQuotaPath": "/v1/admin/profiles/{id}/quota",
        "usageVersion": 1,
        "hotwordsVersion": 1,
        "keyHotwordsPath": "/v1/admin/asr-keys/{id}/hotwords",
        "hotwordCatalogPath": "/v1/admin/hotwords/catalog",
        "publicDictionariesPath": "/v1/admin/hotwords/public-dictionaries",
        "managementPage": "/admin",
    }
