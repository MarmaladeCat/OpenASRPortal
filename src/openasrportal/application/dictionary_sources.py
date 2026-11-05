"""Explicit online imports from a small public catalog; no arbitrary server-side URLs."""

import hashlib
from pathlib import Path

import httpx

from ..domain.dictionaries import FORMATS, MAX_BYTES, MAX_DICTIONARIES, MAX_WORDS, parse_dictionary

SOURCES = [
    {
        "id": "tech-ai",
        "title": "人工智能 / AI 入门词库",
        "format": "text",
        "url": "",
        "license": "项目维护的术语列表",
        "description": "离线可用的大模型、机器学习与 AI 工具术语",
    },
    {
        "id": "tech-computing",
        "title": "计算机入门词库",
        "format": "text",
        "url": "",
        "license": "项目维护的术语列表",
        "description": "操作系统、数据库、数据结构等术语",
    },
    {
        "id": "tech-programming",
        "title": "编程入门词库",
        "format": "text",
        "url": "",
        "license": "项目维护的术语列表",
        "description": "编程语言、开发工具、容器和数据库名称",
    },
    {
        "id": "thuocl-it",
        "title": "THUOCL IT",
        "format": "tsv",
        "url": "https://raw.githubusercontent.com/thunlp/THUOCL/master/data/THUOCL_IT.txt",
        "homepage": "https://github.com/thunlp/THUOCL",
        "license": "THUOCL 开放条款（见项目 README）",
        "description": "约 16000 条计算机术语；Tab 分隔词语和文档频率，语料主要来自 2014–2016 年",
    },
    {
        "id": "rime-ice-en-ext",
        "title": "雾凇拼音 · 扩展英文",
        "format": "rime",
        "url": "https://raw.githubusercontent.com/iDvel/rime-ice/main/en_dicts/en_ext.dict.yaml",
        "homepage": "https://github.com/iDvel/rime-ice",
        "license": "GPL-3.0-only",
        "description": "包含编程、软件、AI 名称，也包含其他英文缩写；按需启用",
    },
]


def seed_public_dictionaries(store):
    records = []
    for source in SOURCES:
        if source["url"]:
            continue
        content = bundled_content(source["id"])
        records.append(
            (
                source["id"],
                {key: source[key] for key in ("title", "description", "license")},
                parse_dictionary(content, source["format"]),
                {**source, "sha256": hashlib.sha256(content.encode()).hexdigest()},
            )
        )
    store.seed(records)


def catalog(store):
    public = [
        {
            "id": row["id"],
            "title": row["title"],
            "description": row["description"],
            "license": row["license"],
            "homepage": row["homepage"],
            "format": row["format"],
            "url": "",
            "kind": "portal-public",
            "revision": row["revision"],
            "wordCount": row["wordCount"],
            "downloadPath": "/v1/hotwords/catalog/" + row["id"],
        }
        for row in store.listing(published_only=True)
    ]
    return {
        "formats": list(FORMATS),
        "maxBytes": MAX_BYTES,
        "maxWords": MAX_WORDS,
        "maxDictionaries": MAX_DICTIONARIES,
        "recommendationOnly": True,
        "sources": public + [{**source, "kind": "external"} for source in SOURCES if source["url"]],
    }


def bundled_content(identity):
    content = (Path(__file__).parents[1] / "presentation/dictionaries/tech-ai.txt").read_text(
        encoding="utf-8"
    )
    section, words = "", []
    for line in content.splitlines():
        if line.startswith("# ["):
            section = line[3:].strip().strip("[]")
        elif (
            section == identity.removeprefix("tech-") and line.strip() and not line.startswith("#")
        ):
            words.append(line)
    return "\n".join(words)


async def source_content(identity):
    source = next((row for row in SOURCES if row["id"] == identity and row["url"]), None)
    if source is None:
        raise ValueError("未知的公开词库来源")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10, connect=5), follow_redirects=False
    ) as client:
        async with client.stream("GET", source["url"]) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise ValueError("公开词库超过 4 MiB，请下载并拆分后上传")
            content = data.decode("utf-8-sig")
    return (
        content,
        source["format"],
        {**source, "sha256": hashlib.sha256(content.encode()).hexdigest()},
    )
