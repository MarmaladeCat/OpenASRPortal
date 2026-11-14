"""Project ordered provider results into v1's stable prefix and one preview tail."""

from .transcript import TranscriptLedger


class EventStream:
    def __init__(self, session_id):
        self.session_id = session_id
        self.seq = 0
        self.utterance = 1
        self.revision = 0
        self.final_count = 0
        self.pending_text = ""
        self.ledger = TranscriptLedger()

    def event(self, kind, **fields):
        self.seq += 1
        return {"type": kind, "sessionId": self.session_id, "seq": self.seq, **fields}

    def _text(self, items, final):
        text = "".join(item.text for item in items)
        starts = [item.start_ms for item in items]
        ends = [item.end_ms for item in items]
        start = min(starts) if starts and all(x is not None for x in starts) else None
        end = max(ends) if ends and all(x is not None for x in ends) else None
        if start is None or end is None or end <= start:
            start = end = None
        self.revision += 1
        event = self.event(
            "transcript.final" if final else "transcript.partial",
            utteranceId=f"{self.session_id}:{self.utterance}", revision=self.revision,
            text=text, startMs=start, endMs=end,
            source=items[-1].source if items else "",
        )
        self.pending_text = "" if final else text
        if final:
            self.final_count += 1
            self.utterance += 1
            self.revision = 0
        return event

    def apply(self, events):
        for event in events:
            self.ledger.accept(event)
        result = []
        prefix = self.ledger.stable_prefix()
        if prefix:
            result.append(self._text(prefix, True))
        tail = self.ledger.tail()
        text = "".join(item.text for item in tail)
        if text != self.pending_text:
            result.append(self._text(tail, False))
        return result

    def finish(self):
        self.ledger.finish()
