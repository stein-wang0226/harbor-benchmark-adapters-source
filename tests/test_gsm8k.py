import json
from pathlib import Path
from runpy import run_path
from tempfile import TemporaryDirectory
import unittest

from gsm8k.adapter import TEMPLATES, parse_example, select_examples


grader = run_path(str(TEMPLATES / "tests/grade.py"))
MAX_BYTES, read_submission, score = (grader[name] for name in ("MAX_BYTES", "read_submission", "score"))


class GraderTests(unittest.TestCase):
    def test_canonical_submissions_agree_with_reference(self):
        cases = ((b"12,345\n", b"12345", 1), (b"-11\n", b"-11", 1), (b"0\n", b"1", 0),
                 (b"42.0\n", b"42", 0), (b"", b"42", 0), (b"not a number\n", b"42", 0))
        for submission, gold, expected in cases:
            with self.subTest(submission=submission, gold=gold):
                self.assertEqual(score(submission, gold), expected)

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

    def test_task_selection_is_split_safe_and_retains_source_order(self):
        raw = b'{"question":"What is the balance?","answer":"#### 3"}'
        rows = [parse_example(index, raw) for index in range(3)]
        chosen = select_examples(rows, ["gsm8k-test-0002", "gsm8k/gsm8k-test-0000"], limit=1)
        self.assertEqual(chosen, rows[:1])
        with self.assertRaisesRegex(ValueError, "Unknown task IDs"):
            select_examples(rows, ["gsm8k-train-0002"])
