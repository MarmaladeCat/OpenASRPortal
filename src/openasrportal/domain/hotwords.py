"""Provider-neutral personal vocabulary and bounded upstream selection."""

import re
import unicodedata

MAX_TERMS = 2000
DEFAULTS = {
    "enabled": False,
    "autoLearn": False,
    "windowDays": 30,
    "minFrequency": 3,
    "maxWords": 100,
    "manualTerms": [],
    "excludedTerms": [],
}
STOPWORDS = frozenset(
    "这个 那个 我们 你们 他们 可以 需要 然后 就是 一个 没有 不是 什么 时候 "
    "自己 现在 进行 使用 因为 所以 但是 还是 已经 如果 这样 这些 一些 这里 "
    "一下 以及 还有 可能 应该 能够 希望 今天 问题 功能 设置 "
    "the and that this with from have for you are was were not can will please".split()
)


def term_text(value):
    if not isinstance(value, str):
        raise ValueError("热词必须是文本")
    text = " ".join(unicodedata.normalize("NFKC", value).split())
    if (
        not 2 <= len(text) <= 64
        or not any(c.isalnum() for c in text)
        or not all(c.isalnum() or c in " .+#-/_'" for c in text)
    ):
        raise ValueError("热词须为 2–64 字符的词语，可使用文字、数字、空格及常见技术符号 .+#-/_'")
    return text


def validate_settings(patch, previous):
    if not isinstance(patch, dict) or patch.keys() - DEFAULTS.keys():
        raise ValueError("未知的热词设置字段")
    result = {**previous, **patch}
    for name in ("enabled", "autoLearn"):
        if type(result[name]) is not bool:
            raise ValueError(name + " 必须为布尔值")
    for name, low, high in (
        ("windowDays", 1, 90),
        ("minFrequency", 2, 100),
        ("maxWords", 1, MAX_TERMS),
    ):
        if type(result[name]) is not int or not low <= result[name] <= high:
            raise ValueError(f"{name} 必须为 {low}–{high} 的整数")
    manual, seen = [], set()
    if not isinstance(result["manualTerms"], list) or len(result["manualTerms"]) > MAX_TERMS:
        raise ValueError(f"手动热词最多 {MAX_TERMS} 个")
    for item in result["manualTerms"]:
        if not isinstance(item, dict) or item.keys() - {"text", "weight"}:
            raise ValueError("手动热词使用 text / weight 字段")
        text, weight = term_text(item.get("text")), item.get("weight", 4)
        if type(weight) is not int or not 1 <= weight <= 5:
            raise ValueError("热词权重须为 1–5 的整数")
        if text.casefold() in seen:
            raise ValueError("热词不可重复")
        seen.add(text.casefold())
        manual.append({"text": text, "weight": weight})
    excluded = result["excludedTerms"]
    if not isinstance(excluded, list) or len(excluded) > MAX_TERMS:
        raise ValueError(f"排除热词最多 {MAX_TERMS} 个")
    result["manualTerms"] = manual
    result["excludedTerms"] = list(dict.fromkeys(term_text(word).casefold() for word in excluded))
    return result


def capability(provider):
    if provider == "boson_realtime":
        return {"supported": False, "mode": "none", "note": "Boson STT 接口不支持会话级热词增强"}
    if provider == "doubao_realtime":
        return {
            "supported": True,
            "mode": "inline-context",
            "maxTokens": 100,
            "maxTermChars": 9,
            "budgetUnit": "utf8-bytes-conservative",
            "budget": 100,
            "note": "双向流式热词上限 100 tokens；Portal 保守按 UTF-8 字节预算选词，非 100 个词",
        }
    if provider == "bailian_qwen_asr":
        return {
            "supported": True,
            "mode": "inline-vocabulary",
            "maxEntries": 2000,
            "maxNonAsciiChars": 15,
            "maxAsciiWords": 7,
            "weightMin": 1,
            "weightMax": 5,
            "note": "Qwen Audio 3.1 即时热词最多 2000 个；普通权重 1–5",
        }
    if provider == "soniox_realtime":
        return {"supported": True, "mode": "context-terms", "maxEntries": 2000,
                "budgetUnit": "utf8-bytes-conservative", "budget": 7000,
                "note": "Soniox 上下文词不传权重；Portal 保守限制为 7000 UTF-8 字节"}
    return {"supported": False, "mode": "none", "note": "当前本地模型接口不支持会话级热词增强"}


def select_terms(provider, terms, settings):
    limits = capability(provider)
    selected, omitted, budget = [], [], 0
    for term in terms:
        text = term["text"]
        reason = ""
        if not settings["enabled"]:
            reason = "disabled"
        elif not limits["supported"]:
            reason = "unsupported"
        elif len(selected) >= min(settings["maxWords"], limits.get("maxEntries", MAX_TERMS)):
            reason = "count-limit"
        elif provider == "doubao_realtime":
            cost = len(text.encode("utf-8")) + 1
            if len(text) > 9 or any(c.isdigit() or not (c.isalnum() or c == " ") for c in text):
                reason = "term-format"
            elif budget + cost > 100:
                reason = "token-budget"
            else:
                budget += cost
        elif provider == "soniox_realtime":
            cost = len(text.encode("utf-8")) + 4
            if budget + cost > 7000:
                reason = "token-budget"
            else:
                budget += cost
        elif (not text.isascii() and len(text) > 15) or (text.isascii() and len(text.split()) > 7):
            reason = "term-format"
        if reason:
            omitted.append({"text": text, "reason": reason})
        else:
            selected.append(term)
    return {
        "capability": limits,
        "terms": selected,
        "omitted": omitted,
        "appliedCount": len(selected),
        "budgetUsed": budget,
    }


def extract_terms(text, tokenizer):
    # Dictionary segmentation keeps Chinese words intact instead of counting every n-gram.
    tokens = tokenizer.cut(unicodedata.normalize("NFKC", text), HMM=False)
    words = []
    for token in tokens:
        if re.fullmatch(r"[^\W_]{2,64}", token, re.UNICODE) and not token.isdigit():
            if token.casefold() not in STOPWORDS:
                words.append(token.casefold() if token.isascii() else token)
    return words
