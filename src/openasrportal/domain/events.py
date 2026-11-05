"""将提供商事件转成有稳定语句标识的公开 v1 事件。"""

import json


class EventStream:
    def __init__(self, session_id):
        self.session_id = session_id
        self.seq = 0
        self.utterance = 1
        self.revision = 0
        self.final_count = 0
        self.final_keys = set()

    def event(self, kind, **fields):
        self.seq += 1
        return {"type": kind, "sessionId": self.session_id, "seq": self.seq, **fields}

    def transcript(self, raw):
        kind = raw.get("type")
        if kind not in ("partial_result", "final_result"):
            return None
        results = raw.get("nbest", [])
        if isinstance(results, str):
            results = json.loads(results)
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            return None
        result = results[0]
        text = result.get("sentence")
        if not isinstance(text, str):
            return None
        pieces = result.get("word_pieces", [])
        starts = [
            p["start"]
            for p in pieces
            if isinstance(p, dict) and type(p.get("start")) in (int, float)
        ]
        ends = [
            p["end"] for p in pieces if isinstance(p, dict) and type(p.get("end")) in (int, float)
        ]
        start, end = min(starts, default=None), max(ends, default=None)
        if end is None or start is None or end <= start:
            start, end = None, None
        final = kind == "final_result"
        key = (start, end)
        if start is not None and key in self.final_keys:
            return None
        self.revision += 1
        event = self.event(
            "transcript.final" if final else "transcript.partial",
            utteranceId=f"{self.session_id}:{self.utterance}",
            revision=self.revision,
            text=text,
            startMs=start,
            endMs=end,
            source=raw.get("source", ""),
        )
        if final:
            if start is not None:
                self.final_keys.add(key)
            self.final_count += 1
            self.utterance += 1
            self.revision = 0
        return event
