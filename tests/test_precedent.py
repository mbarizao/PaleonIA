import unittest

from paleonia.reading.precedent import (
    forms_from_texts,
    gap_query,
    has_gap,
    neighbor_texts,
    revise_gap_texts,
)


class PrecedentTests(unittest.TestCase):
    def test_repeated_forms_skip_the_gap_marker_and_function_words(self):
        lines = ["pagou a saca de trigo ao Dn", "pagou a saca de milho ao Dn", "pagou a saca ao Dn"]
        forms = forms_from_texts(lines + ["[ilegível]", "[ilegível]", "[ilegível]"])
        self.assertIn("saca", forms)
        self.assertIn("Dn", forms)
        self.assertNotIn("de", forms)
        self.assertNotIn("ilegível", forms)
        self.assertNotIn("trigo", forms)

    def test_a_word_repeated_in_one_line_counts_once(self):
        forms = forms_from_texts(["saca saca saca", "outra linha", "mais uma"])
        self.assertNotIn("saca", forms)

    def test_gap_query_keeps_the_readable_phrase(self):
        self.assertTrue(has_gap("pagou a [ilegível] de trigo"))
        self.assertEqual(gap_query("pagou a [Ilegível] de trigo"), "pagou a de trigo")
        self.assertFalse(has_gap("pagou a saca"))

    def test_neighbors_keep_only_close_hits(self):
        hits = [
            {"text": "pagou a saca de trigo", "score": 0.8},
            {"text": "  pagou a saca de trigo  ", "score": 0.9},
            {"text": "outra conta", "score": 0.4},
        ]
        self.assertEqual(neighbor_texts(hits), ["pagou a saca de trigo"])

    def test_second_reading_replaces_only_the_gap(self):
        def lookup(query):
            self.assertIn("pagou", query)
            return ["pagou a saca de trigo"]

        def reread(neighbors):
            self.assertEqual(neighbors, ["pagou a saca de trigo"])
            return ["pagou a saca de trigo", "linha firme"]

        revised = revise_gap_texts(
            ["pagou a [ilegível] de trigo", "linha firme"],
            lookup=lookup,
            reread=reread,
        )
        self.assertEqual(revised, ["pagou a saca de trigo", "linha firme"])

    def test_second_reading_is_skipped_without_a_close_line(self):
        calls = {"reread": 0}

        def reread(_neighbors):
            calls["reread"] += 1
            return ["não devia"]

        revised = revise_gap_texts(
            ["pagou a [ilegível] de trigo"],
            lookup=lambda _query: [],
            reread=reread,
        )
        self.assertEqual(revised, ["pagou a [ilegível] de trigo"])
        self.assertEqual(calls["reread"], 0)

    def test_a_failed_reread_keeps_the_first_text(self):
        def reread(_neighbors):
            raise RuntimeError("modelo indisponível")

        revised = revise_gap_texts(
            ["pagou a [ilegível] de trigo"],
            lookup=lambda _query: ["pagou a saca de trigo"],
            reread=reread,
        )
        self.assertEqual(revised, ["pagou a [ilegível] de trigo"])
