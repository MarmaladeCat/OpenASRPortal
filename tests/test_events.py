import unittest

from openasrportal.domain.asr_protocol import ProviderError
from openasrportal.domain.events import EventStream
from openasrportal.domain.transcript import ProviderEvent, ResultEmitter


class EventTests(unittest.TestCase):
    def test_stable_conflict_and_identical_distinct_sentences(self):
        stream = EventStream("session")
        partial = stream.apply([ProviderEvent("a", 0, 1, "同一句")])[0]
        final = ProviderEvent("a", 0, 2, "同一句。", True)
        published = stream.apply([final])[0]
        self.assertEqual(partial["utteranceId"], published["utteranceId"])
        self.assertGreater(published["revision"], partial["revision"])
        self.assertEqual(stream.apply([final]), [])
        with self.assertRaises(ProviderError):
            stream.apply([ProviderEvent("a", 0, 3, "迟到的改写", True)])
        following = stream.apply([ProviderEvent("b", 1, 1, "同一句。", True)])[0]
        self.assertNotEqual(published["utteranceId"], following["utteranceId"])
        self.assertEqual(stream.final_count, 2)
        self.assertIsNone(following["startMs"])
        stream.finish()

    def test_interleaved_second_pass_orders_finals_for_old_v1_clients(self):
        stream = EventStream("s")
        stream.apply([ProviderEvent("a", 0, 1, "甲")])
        events = stream.apply([ProviderEvent("b", 1, 1, "乙。", True)])
        self.assertEqual([(e["type"], e["text"]) for e in events], [("transcript.partial", "甲乙。")])
        events = stream.apply([ProviderEvent("a", 0, 2, "甲。", True)])
        self.assertEqual([(e["type"], e["text"]) for e in events], [("transcript.final", "甲。乙。")])
        stream.finish()

    def test_prefix_final_then_revised_tail_and_empty_withdrawal(self):
        stream = EventStream("s")
        stream.apply([ProviderEvent("a", 0, 1, "甲"), ProviderEvent("b", 1, 1, "乙")])
        events = stream.apply([ProviderEvent("a", 0, 2, "甲。", True)])
        self.assertEqual([e["text"] for e in events], ["甲。", "乙"])
        self.assertNotEqual(events[0]["utteranceId"], events[1]["utteranceId"])
        self.assertEqual(stream.apply([ProviderEvent("b", 1, 2, "")])[0]["text"], "")
        with self.assertRaises(ProviderError):
            stream.finish()
        empty = stream.apply([ProviderEvent("b", 1, 3, "", True)])[0]
        self.assertEqual(empty["type"], "transcript.final")
        self.assertEqual(stream.final_count, 2)
        stream.finish()

    def test_missing_predecessor_never_relabels_arrival_as_order(self):
        stream = EventStream("s")
        self.assertEqual(stream.apply([ProviderEvent("b", 1, 1, "乙", True, 0, 100)]), [])
        with self.assertRaises(ProviderError):
            stream.finish()
        final = stream.apply([ProviderEvent("a", 0, 1, "甲", True, 0, 100)])[0]
        self.assertEqual(final["text"], "甲乙")
        stream.finish()

    def test_empty_candidate_and_emitter_stable_conflict(self):
        emitter = ResultEmitter()
        emitter.replace("a", 0, "")
        with self.assertRaises(ProviderError):
            emitter.finish()
        emitter.replace("a", 0, "", stable=True)
        emitter.finish()
        with self.assertRaises(ProviderError):
            emitter.replace("a", 0, "new", stable=True)
