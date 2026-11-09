"""管理协议 v1：提供方拥有表单字段契约，所有客户端按协议渲染。"""

from .config import BAILIAN_LANGUAGES, DOUBAO_RESOURCES, config_defaults


def field(key, label, kind="text", **attributes):
    return {"key": key, "label": label, "type": kind, **attributes}


def contract():
    secret = field("apiKey", "上游 API Key", "secret", required=True, retainWhenOmitted=True)
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
                field("enableNonstream", "二遍识别", "boolean"),
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
                    options=[
                        {"value": value, "label": "自动" if value == "auto" else value}
                        for value in BAILIAN_LANGUAGES
                    ],
                ),
                field("silenceMs", "断句静音（毫秒）", "number", min=200, max=6000, step=100),
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
                field("language", "识别语种", required=True,
                      description="auto 自动识别，或 zh / en 等两位语言代码。"),
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
                    "language", "识别语种", required=True,
                    description="auto 自动识别，或 zh / en 等两位语言代码；停顿后返回分段文本，无逐字预览。",
                ),
                field("silenceMs", "断句静音（毫秒）", "number", min=600, max=3000, step=100),
            ],
        ),
    ]
    providers = []
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
