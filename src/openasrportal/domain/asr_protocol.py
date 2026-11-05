"""独立 Portal 的上游适配契约：统一错误及文本事件。"""

import asyncio


class ProviderError(Exception):
    pass


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
