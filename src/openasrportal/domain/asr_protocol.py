"""独立 Portal 的上游适配契约：统一错误及文本事件。"""

import asyncio


class ProviderError(Exception):
    def __init__(self, message, *, code="UPSTREAM_ERROR", retryable=True):
        super().__init__(message)
        self.message, self.code, self.retryable = message, code, retryable

    @classmethod
    def upstream(cls, provider, status=None, kind=None):
        # Match documented identifiers only; never expose upstream messages/credentials.
        value = str(status).lower()
        kind = str(kind).lower()
        if value in {"401", "403", "unauthenticated", "invalid_api_key", "invalidapikey", "forbidden"} or kind in {
            "unauthenticated", "permission_denied", "invalid_api_key", "authentication_error",
        }:
            return cls(f"{provider} 鉴权失败，请检查 API Key 与模型权限",
                       code="UPSTREAM_AUTH_FAILED", retryable=False)
        if value in {"402", "quota_exceeded", "insufficient_quota"} or kind in {
            "quota_exceeded", "insufficient_quota", "payment_required",
        }:
            return cls(f"{provider} 额度不足，请检查账户余额",
                       code="UPSTREAM_QUOTA_EXHAUSTED", retryable=False)
        if value in {"429", "too_many_requests", "throttling"} or kind in {
            "rate_limit_exceeded", "resource_exhausted", "too_many_requests",
        }:
            return cls(f"{provider} 请求受限，请稍后重试", code="UPSTREAM_BUSY")
        if value in {"400", "404", "422", "invalidparameter", "invalid_request"} or kind in {
            "invalid_argument", "invalid_request", "not_found",
        }:
            return cls(f"{provider} 请求参数或模型配置无效",
                       code="UPSTREAM_INVALID_REQUEST", retryable=False)
        return cls(f"{provider} 识别服务异常，请检查网络后重试")


def describe_error(error, provider="远程 ASR"):
    if isinstance(error, ProviderError):
        return str(error)
    if isinstance(error, asyncio.TimeoutError):
        return "%s 连接或识别响应超时，请检查网络后重试" % provider
    return "%s 语音连接异常，请检查后端网络并重试" % provider


def text_event(kind, text, start=0, end=0, source=""):
    return {
        "type": kind,
        "source": source,
        "nbest": [
            {
                "sentence": text,
                "word_pieces": [{"word": text, "start": start, "end": end}],
            }
        ],
    }
