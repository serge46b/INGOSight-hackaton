import unittest

from app.textutil import (
    MailLink,
    chunk_text,
    group_indices,
    normalize_subject,
    postprocess,
    strip_subject,
)


class TextUtilTests(unittest.TestCase):
    def test_subject_prefixes(self):
        self.assertEqual(normalize_subject("Re: Ответ: Договор"), "договор")
        self.assertEqual(strip_subject("Re: Договор"), "Договор")

    def test_threads_follow_references_and_subject(self):
        messages = [
            MailLink("a@fixture.local", "", "", "Договор"),
            MailLink("b@fixture.local", "a@fixture.local", "<a@fixture.local>", "Re: Договор"),
            MailLink("c@fixture.local", "", "", "Другая тема"),
        ]
        groups = group_indices(messages)
        sizes = sorted(len(group) for group in groups)
        self.assertEqual(sizes, [1, 2])

    def test_chunks_overlap(self):
        text = " ".join(f"w{i}" for i in range(10))
        chunks = chunk_text(text, size=4, overlap=1)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("w0"))

    def test_postprocess_strips_wrapper_and_empty(self):
        cleaned = postprocess('```\nКонечно! Вот саммари:\n"Срок"\n```')
        self.assertNotIn("Конечно", cleaned)
        self.assertIn("«Срок»", cleaned)
        self.assertEqual(postprocess("   "), "")

    def test_postprocess_keeps_list_markers(self):
        cleaned = postprocess("Договорённости:\n- срок 15 марта\n- оплата")
        self.assertIn("\n- срок 15 марта", cleaned)

    def test_postprocess_limits_length(self):
        cleaned = postprocess("а" * 50, limit=20)
        self.assertIn("Ответ сокращён", cleaned)
        self.assertLess(len(cleaned), 50)


if __name__ == "__main__":
    unittest.main()
