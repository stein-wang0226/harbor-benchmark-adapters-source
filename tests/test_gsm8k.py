import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from adapters.gsm8k.acceptance import upstream_extract
from adapters.gsm8k.adapter import parse_example
from adapters.gsm8k.task_template.grade import MAX_BYTES, read_submission, score


class GraderTests(unittest.TestCase):
    def test_canonical_submissions_agree_with_reference(self):
        cases = ((b"12,345\n", b"12345"), (b"-11\n", b"-11"), (b"0\n", b"1"),
                 (b"42.0\n", b"42"), (b"", b"42"), (b"not a number\n", b"42"))
        for submission, gold in cases:
            with self.subTest(submission=submission, gold=gold):
                expected = upstream_extract("#### " + submission.decode()) == gold.decode()
                self.assertEqual(score(submission, gold), int(expected))

    def test_single_number_contract(self):
        for content in (b"42 and 0", b"42\n0", b"#### 42", b"4,2", b" " * MAX_BYTES + b"42"):
            with self.subTest(content=content):
                self.assertEqual(score(content, b"42"), 0)

    def test_reading_rejects_missing_and_symlink_and_bounds_the_read(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "answer.txt"
            self.assertIsNone(read_submission(path))
            content = Path(directory) / "target"
            content.write_bytes(b"1" * (MAX_BYTES + 2))
            path.symlink_to(content)
            self.assertIsNone(read_submission(path))
            self.assertEqual(len(read_submission(content)), MAX_BYTES + 1)


class SourceTests(unittest.TestCase):
    def test_uses_final_marker_and_preserves_problem(self):
        line = json.dumps({"question": "What is the balance?", "answer": "The balance changed.\n#### -1,001"})
        example = parse_example(7, line.encode())
        self.assertEqual((example.task_name, example.question, example.gold),
                         ("gsm8k-test-0007", "What is the balance?", "-1001"))

    def test_rejects_duplicate_markers(self):
        line = b'{"question":"What is the balance?","answer":"#### 3\\n#### 2"}'
        with self.assertRaisesRegex(ValueError, "one answer marker"):
            parse_example(0, line)
