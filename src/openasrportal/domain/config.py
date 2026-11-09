"""Portal 上游配置验证与脱敏；客户端不接收提供商 Key。"""

import re
from urllib.parse import urlsplit, urlunsplit

DOUBAO_MODEL = "doubao_realtime"
DOUBAO_ENDPOINT = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
DOUBAO_RESOURCES = (
    "volc.seedasr.sauc.duration",
    "volc.seedasr.sauc.concurrent",
    "volc.bigasr.sauc.duration",
    "volc.bigasr.sauc.concurrent",
)
BAILIAN_MODEL = "bailian_qwen_asr"
BAILIAN_ASR_MODEL = "qwen-audio-3.1-asr-flash-streaming"
BAILIAN_PATH = "/api-ws/v1/inference"
BAILIAN_ENDPOINT = "wss://dashscope.aliyuncs.com" + BAILIAN_PATH
BAILIAN_LANGUAGES = (
    "auto",
    "zh",
    "en",
    "ja",
    "ko",
    "vi",
    "th",
    "id",
    "ms",
    "tl",
    "hi",
    "ar",
    "fr",
    "de",
    "es",
    "pt",
    "ru",
    "it",
    "nl",
    "sv",
    "da",
    "fi",
    "no",
    "el",
    "pl",
    "cs",
    "hu",
    "ro",
    "bg",
    "hr",
    "sk",
)
LOCAL_ASR_MODEL = "openlocalasr"
BOSON_MODEL = "boson_realtime"
BOSON_ENDPOINT = "wss://api.boson.ai/v1/realtime"
BOSON_ASR_MODEL = "higgs-stt-3.1"
SONIOX_MODEL = "soniox_realtime"
SONIOX_ENDPOINT = "wss://stt-rt.soniox.com/transcribe-websocket"
SONIOX_ASR_MODEL = "stt-rt-v6"
REMOTE_MODELS = {DOUBAO_MODEL, BAILIAN_MODEL, LOCAL_ASR_MODEL, BOSON_MODEL, SONIOX_MODEL}


def config_defaults(name):
    return {**provider_defaults(name), "useProxy": False}


def provider_defaults(name):
    if name == SONIOX_MODEL:
        return {"endpoint": SONIOX_ENDPOINT, "model": SONIOX_ASR_MODEL,
                "language": "en,zh", "endpointDelayMs": 2000}
    if name == BOSON_MODEL:
        return {
            "endpoint": BOSON_ENDPOINT,
            "model": BOSON_ASR_MODEL,
            "language": "auto",
            "silenceMs": 800,
        }
    if name == LOCAL_ASR_MODEL:
        return {
            "endpoint": "ws://127.0.0.1:10095/api-ws/v1/inference",
            "model": "funasr_sensevoice_small",
        }
    if name == BAILIAN_MODEL:
        return {
            "endpoint": BAILIAN_ENDPOINT,
            "model": BAILIAN_ASR_MODEL,
            "language": "auto",
            "keepDialect": False,
            "silenceMs": 800,
        }
    return {"endpoint": DOUBAO_ENDPOINT, "resourceId": DOUBAO_RESOURCES[0], "enableNonstream": True}


def migrate_config(name, config):
    """Upgrade stored HTTP profiles without changing their region or credentials."""
    config = dict(config)
    if name == BAILIAN_MODEL:
        config.pop("previewIntervalMs", None)
        if config.get("model") == "qwen-audio-3.1-asr-flash":
            config["model"] = BAILIAN_ASR_MODEL
        endpoint = config.get("endpoint", "")
        if isinstance(endpoint, str) and endpoint.startswith("https://"):
            url = urlsplit(endpoint)
            if url.path.rstrip("/") in ("", "/api/v1", "/api/v1/services/aigc/multimodal-generation/generation"):
                config["endpoint"] = urlunsplit(("wss", url.netloc, BAILIAN_PATH, url.query, url.fragment))
    return config


def validate_config(name, patch, previous=None):
    if name not in REMOTE_MODELS:
        raise ValueError("未知的远程 ASR 提供商")
    if not isinstance(patch, dict):
        raise ValueError("远程 ASR 配置必须为对象")
    defaults = config_defaults(name)
    previous = migrate_config(name, previous or {})
    config = {field: (previous or {}).get(field, default) for field, default in defaults.items()}
    config["apiKey"] = (previous or {}).get("apiKey", "")
    for field in ("apiKey", *defaults):
        if field in patch:
            config[field] = patch[field]
    key = config.get("apiKey", "")
    if (
        not isinstance(key, str)
        or not key.strip()
        or len(key) > 1024
        or any(ord(c) < 32 for c in key)
    ):
        raise ValueError("请填写有效的 ASR API Key")
    config["apiKey"] = key.strip()
    if type(config["useProxy"]) is not bool:
        raise ValueError("使用代理选项必须为布尔值")
    if name == SONIOX_MODEL:
        if config["endpoint"] != SONIOX_ENDPOINT:
            raise ValueError("请使用 Soniox 官方实时 WebSocket 端点")
        if config["model"] != SONIOX_ASR_MODEL:
            raise ValueError("此适配器使用 " + SONIOX_ASR_MODEL)
        if not isinstance(config["language"], str) or not re.fullmatch(r"auto|[a-z]{2}(,[a-z]{2}){0,9}", config["language"]):
            raise ValueError("Soniox 语种须为 auto 或逗号分隔的两位小写语言代码")
        if type(config["endpointDelayMs"]) is not int or not 500 <= config["endpointDelayMs"] <= 3000:
            raise ValueError("Soniox 端点延迟应为 500–3000 毫秒")
        return config
    if name == BOSON_MODEL:
        if config["endpoint"] != BOSON_ENDPOINT:
            raise ValueError("请使用 Boson AI 官方实时 WebSocket 端点")
        if config["model"] != BOSON_ASR_MODEL:
            raise ValueError("此适配器使用 " + BOSON_ASR_MODEL)
        language = config["language"]
        if not isinstance(language, str) or not re.fullmatch(r"auto|[a-z]{2}", language):
            raise ValueError("Boson 语种须为 auto 或两位小写语言代码")
        if type(config["silenceMs"]) is not int or not 600 <= config["silenceMs"] <= 3000:
            raise ValueError("断句静音应为 600–3000 毫秒")
        return config
    if name == LOCAL_ASR_MODEL:
        try:
            url = urlsplit(config["endpoint"])
            valid = (
                url.scheme in ("ws", "wss")
                and url.hostname
                and url.path == "/api-ws/v1/inference"
                and not url.query
                and not url.fragment
                and not url.username
                and not url.password
                and url.port != 0
            )
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise ValueError("请填写 OpenLocalASR 的 ws(s)://主机:端口/api-ws/v1/inference 地址")
        if not isinstance(config["model"], str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", config["model"]
        ):
            raise ValueError("请填写远程服务当前启用的模型名称")
        return config
    if name == BAILIAN_MODEL:
        endpoint = config["endpoint"]
        if not isinstance(endpoint, str):
            raise ValueError("百炼端点必须为官方 WSS 地址")
        try:
            url = urlsplit(endpoint.strip())
            path = url.path.rstrip("/")
            if path == "":
                path = BAILIAN_PATH
            host = url.hostname or ""
            valid_host = host in (
                "dashscope.aliyuncs.com",
                "dashscope-intl.aliyuncs.com",
            ) or re.fullmatch(
                r"[a-zA-Z0-9-]+\.(cn-beijing|ap-southeast-1)\.maas\.aliyuncs\.com", host
            )
            valid = (
                url.scheme == "wss"
                and valid_host
                and path == BAILIAN_PATH
                and not url.query
                and not url.fragment
                and not url.username
                and not url.password
                and url.port in (None, 443)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(
                "请使用百炼北京/新加坡官方 WSS 地址，路径为 /api-ws/v1/inference"
            )
        config["endpoint"] = urlunsplit((url.scheme, url.netloc, path, "", ""))
        if config["model"] != BAILIAN_ASR_MODEL:
            raise ValueError("此适配器使用 " + BAILIAN_ASR_MODEL)
        if config["language"] not in BAILIAN_LANGUAGES:
            raise ValueError("不支持的百炼识别语种")
        if not isinstance(config["keepDialect"], bool):
            raise ValueError("保留方言选项必须为布尔值")
        if type(config["silenceMs"]) is not int or not 200 <= config["silenceMs"] <= 6000:
            raise ValueError("百炼断句静音应为 200–6000 毫秒")
        return config
    if config["endpoint"] != DOUBAO_ENDPOINT:
        raise ValueError("请使用豆包官方实时识别 WebSocket 端点")
    if config["resourceId"] not in DOUBAO_RESOURCES:
        raise ValueError("不支持的豆包模型资源 ID")
    if not isinstance(config["enableNonstream"], bool):
        raise ValueError("二遍识别选项必须为布尔值")
    return config


def public_config(config, name=DOUBAO_MODEL):
    config = config or {}
    return {
        **{field: config.get(field, default) for field, default in config_defaults(name).items()},
        "hasApiKey": bool(config.get("apiKey")),
    }
