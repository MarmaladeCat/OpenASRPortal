import unittest

from openasrportal.domain.asr_protocol import text_event
from openasrportal.domain.events import EventStream


class EventTests(unittest.TestCase):
    def test_stable_revision_duplicate_final_and_identical_distinct_sentences(self):
        stream = EventStream("session")
        partial = stream.transcript(text_event("partial_result", "同一句", 0, 100))
        final = stream.transcript(text_event("final_result", "同一句。", 0, 200))
        self.assertEqual(partial["utteranceId"], final["utteranceId"])
        self.assertGreater(final["revision"], partial["revision"])
        self.assertIsNone(stream.transcript(text_event("final_result", "同一句。", 0, 200)))
        self.assertIsNone(stream.transcript(text_event("final_result", "迟到的改写", 0, 200)))
        next_final = stream.transcript(text_event("final_result", "同一句。", 300, 500))
        self.assertNotEqual(final["utteranceId"], next_final["utteranceId"])
        self.assertEqual(stream.final_count, 2)

    def test_unknown_timing_is_null(self):
        event = EventStream("session").transcript(text_event("final_result", "文字"))
        self.assertIsNone(event["startMs"])
        self.assertIsNone(event["endMs"])
