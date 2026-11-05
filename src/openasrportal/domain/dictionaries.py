"""Text dictionary import. RIME headers are metadata, never executable YAML."""

import csv
import io
import json
import math
import re

from .hotwords import term_text

MAX_BYTES = 4 * 1024 * 1024
MAX_WORDS = 50000
MAX_DICTIONARIES = 8
FORMATS = ("auto", "text", "tsv", "csv", "json", "rime")


def frequency(value):
    if value in (None, ""):
        return 0.0
    if isinstance(value, bool):
        raise ValueError("词频无效")
    result = float(str(value).strip().removesuffix("%"))
    if not math.isfinite(result) or result < 0:
        raise ValueError("词频须为非负有限数值")
    return result


def rime_rows(lines):
    end = next((i for i, line in enumerate(lines) if line.strip() == "..."), None)
    if end is None:
        raise ValueError("RIME 词库缺少 YAML 结束标记 ...")
    columns = ["text", "code", "weight"]
    imports = []
    section = None
    for line in lines[:end]:
        clean = line.split("#", 1)[0].strip()
        if clean.startswith("columns:"):
            value = clean.split(":", 1)[1].strip()
            if value:
                if not value.startswith("[") or not value.endswith("]"):
                    raise ValueError("RIME columns 请使用列表格式")
                columns = [item.strip().strip("\"'") for item in value[1:-1].split(",")]
                section = None
            else:
                columns, section = [], "columns"
        elif clean.startswith("import_tables:"):
            section = "imports"
        elif clean.startswith("- ") and section:
            value = clean[2:].strip().strip("\"'")
            (columns if section == "columns" else imports).append(value)
        elif clean and clean != "---":
            section = None
    if "text" not in columns or len(columns) != len(set(columns)):
        raise ValueError("RIME columns 必须包含唯一的 text 列")
    rows = []
    for line in lines[end + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = line.split("\t")
        row = dict(zip(columns, cells))
        rows.append({"text": row.get("text"), "frequency": row.get("weight", 0)})
    return rows, (
        ["import_tables 引用不自动展开；请另行导入：" + "、".join(imports)] if imports else []
    )


def parse_dictionary(content, format_name="auto"):
    if not isinstance(content, str) or not content.strip():
        raise ValueError("请提供 UTF-8 文本词库")
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise ValueError("单个词库文件最多 4 MiB，请拆分大词库")
    if "\0" in content or format_name not in FORMATS:
        raise ValueError("不支持此词库格式或二进制文件")
    content = content.lstrip("\ufeff")
    lines = content.splitlines()
    meaningful = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not meaningful:
        raise ValueError("词库没有正文")
    if format_name == "auto":
        first = meaningful[0].strip()
        format_name = (
            "rime"
            if first == "---"
            else "json"
            if first.startswith(("[", "{"))
            else "tsv"
            if "\t" in first
            else "csv"
            if "," in first
            else "text"
        )
    warnings = []
    if format_name == "rime":
        rows, warnings = rime_rows(lines)
    elif format_name == "json":
        data = json.loads(content)
        if isinstance(data, dict):
            data = data.get("words", data.get("hotwords", data.get("vocabulary", data)))
        if isinstance(data, dict):
            rows = [{"text": word, "weight": weight} for word, weight in data.items()]
        elif isinstance(data, list):
            rows = [({"text": item} if isinstance(item, str) else item) for item in data]
        else:
            raise ValueError("JSON 词库须为词语数组或词语/权重对象")
    elif format_name in ("tsv", "csv"):
        cells = list(
            csv.reader(
                io.StringIO("\n".join(meaningful)), delimiter="\t" if format_name == "tsv" else ","
            )
        )
        aliases = {
            "text": "text",
            "word": "text",
            "词语": "text",
            "词": "text",
            "frequency": "frequency",
            "freq": "frequency",
            "词频": "frequency",
            "weight": "weight",
            "权重": "weight",
            "code": "code",
            "编码": "code",
        }
        header = [aliases.get(cell.strip().lower(), "") for cell in cells[0]]
        rows = []
        if "text" in header and sum(bool(field) for field in header) >= min(2, len(header)):
            rows = [dict(zip(header, row)) for row in cells[1:]]
        else:
            for row in cells:
                value = {"text": row[0]} if row else {}
                if len(row) > 1:
                    if len(row) > 2:
                        value["frequency"] = row[2]
                    else:
                        try:
                            value["frequency"] = frequency(row[1])
                        except ValueError:
                            pass  # RIME/custom-phrase text + phonetic code.
                rows.append(value)
    else:
        rows = []
        for line in meaningful:
            word, separator, weight = line.strip().rpartition("|")
            rows.append(
                {"text": word if separator else line.strip(), "weight": weight if separator else 4}
            )
    words = {}
    skipped, duplicates = 0, 0
    for position, row in enumerate(rows):
        try:
            if not isinstance(row, dict):
                raise ValueError("词条须为对象")
            word = term_text(row.get("text", row.get("word")))
            raw_weight = row.get("weight", 4)
            if isinstance(raw_weight, bool) or not re.fullmatch(r"[1-5]", str(raw_weight).strip()):
                raise ValueError("ASR 权重须为 1–5")
            item = {
                "text": word,
                "weight": int(raw_weight),
                "frequency": frequency(row.get("frequency", 0)),
                "position": position,
            }
        except (ValueError, TypeError):
            skipped += 1
            continue
        identity = word.casefold()
        if identity in words:
            duplicates += 1
            words[identity]["frequency"] = max(words[identity]["frequency"], item["frequency"])
        else:
            words[identity] = item
        if len(words) > MAX_WORDS:
            raise ValueError("一个词库最多 50000 个有效词，请拆分后导入")
    if not words:
        raise ValueError("没有有效热词；RIME 入口文件须导入其 import_tables 引用的正文词库")
    ordered = sorted(words.values(), key=lambda item: (-item["frequency"], item["position"]))
    return {
        "format": format_name,
        "words": ordered,
        "report": {
            "rows": len(rows),
            "wordCount": len(words),
            "skipped": skipped,
            "duplicates": duplicates,
            "warnings": warnings,
            "sample": ordered[:20],
        },
    }
