"""Generate the fixed GSM8K test pilot from OpenAI's original JSONL."""

import argparse
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha1, sha256
from importlib.metadata import version
import json
from pathlib import Path
import re
import shlex
from urllib.request import urlopen

from harbor.models.task.task import Task


HARBOR_VERSION = "0.24.0"
REVISION = "3101c7d5072418e28b9008a6636bde82a006892c"
SOURCE_PATH = "grade_school_math/data/test.jsonl"
SOURCE_BLOB = "e4c2ff4942b9a78bd74f04141224c11e28d12dc9"
SOURCE_SIZE = 749738
SOURCE_URL = f"https://raw.githubusercontent.com/openai/grade-school-math/{REVISION}/{SOURCE_PATH}"
DEFAULT_IMAGE = "quay.io/fedora/python-311@sha256:d12ae9699d4c0af68366e8589c43339db948df57837de06c3c1536b3ec852520"
TEMPLATES = Path(__file__).with_name("task_template")
GOLD_LINE = re.compile(r"#### (-?[0-9]+(?:\.[0-9]+)?)")
ANSWER_PATH = "/app/output/answer.txt"
WRAPPER = (f"\n\nWrite the final number on its own in `{ANSWER_PATH}`. "
           "Use standard decimal notation, with an optional minus sign and properly grouped "
           "thousands separators. Omit redundant leading zeros and decimal places. "
           "Keep any work or units outside that file.\n")


@dataclass(frozen=True)
class Example:
    row: int
    line_sha256: str
    question: str
    upstream_answer: str
    gold: str

    @property
    def task_name(self):
        return f"gsm8k-test-{self.row:04d}"


def require_harbor():
    if version("harbor") != HARBOR_VERSION:
        raise ValueError(f"Harbor {HARBOR_VERSION} is required")


def check_source(data):
    header = f"blob {len(data)}\0".encode("ascii")
    if len(data) != SOURCE_SIZE or sha1(header + data).hexdigest() != SOURCE_BLOB:
        raise ValueError("Source must match the pinned OpenAI test.jsonl Git blob")


def fetch_source(destination):
    with urlopen(SOURCE_URL, timeout=40) as response:
        data = response.read(SOURCE_SIZE + 1)
    check_source(data)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write(data)


def parse_example(index, line):
    record = json.loads(line)
    question, answer = record["question"], record["answer"]
    if not isinstance(question, str) or not question.strip() or "\x00" in question:
        raise ValueError(f"Invalid question at source row {index}")
    if not isinstance(answer, str) or answer.count("####") != 1:
        raise ValueError(f"Expected one answer marker at source row {index}")
    match = GOLD_LINE.fullmatch(answer.rstrip().splitlines()[-1].replace(",", ""))
    if match is None:
        raise ValueError(f"Invalid final answer at source row {index}")
    return Example(index, sha256(line).hexdigest(), question, answer, match[1])


def read_source(data):
    check_source(data)
    lines = data.splitlines()
    if len(lines) != 1319:
        raise ValueError("Unexpected GSM8K test row count")
    return [parse_example(index, line) for index, line in enumerate(lines)]


def select_pilot(examples):
    ordered = sorted(examples, key=lambda item: (not item.gold.startswith("-"),
                                                 sha256(item.task_name.encode()).digest()))
    groups = ([], [], [])
    for item in ordered:
        magnitude = abs(Decimal(item.gold))
        groups[int(magnitude >= 100) + int(magnitude >= 1000)].append(item)
    if any(len(group) < 8 for group in groups):
        raise ValueError("Source does not support the fixed 8/8/8 pilot")
    return sorted((item for group in groups for item in group[:8]), key=lambda item: item.row)


def oracle_script(gold):
    return ("#!/bin/sh\nset -eu\nmkdir -p /app/output\n"
            f"printf '%s\\n' {shlex.quote(gold)} > {ANSWER_PATH}\n")


def write_task(root, example, image):
    path = root / example.task_name
    for folder in ("environment", "tests", "solution"):
        (path / folder).mkdir(parents=True, exist_ok=False)
    config = (TEMPLATES / "task.toml").read_text()
    config += f"\n[metadata]\nsource_revision = \"{REVISION}\"\nsource_split = \"test\"\nsource_row = {example.row}\n"
    (path / "task.toml").write_text(config)
    (path / "instruction.md").write_text(example.question + WRAPPER, encoding="utf-8")
    (path / "environment/Dockerfile").write_text(f"FROM {image}\nUSER 0\nENTRYPOINT []\nWORKDIR /app\nRUN mkdir -p /app/output\n")
    for name in ("test.sh", "grade.py"):
        (path / "tests" / name).write_bytes((TEMPLATES / name).read_bytes())
    (path / "tests/gold.txt").write_text(example.gold + "\n")
    (path / "solution/solve.sh").write_text(oracle_script(example.gold))
    (path / "solution/solve.sh").chmod(0o755)
    (path / "tests/test.sh").chmod(0o755)
    return path


def describe_task(path, example):
    if not Task.is_valid_dir(path):
        raise ValueError(f"Harbor rejected {path.name}")
    task = Task(path)
    if task.instruction != example.question + WRAPPER:
        raise ValueError(f"Harbor changed the instruction for {path.name}")
    return {
        "task_name": task.name, "source_row": example.row,
        "source_line_sha256": example.line_sha256,
        "question_sha256": sha256(example.question.encode()).hexdigest(),
        "harbor_checksum": task.checksum,
        "files": {file.relative_to(path).as_posix(): sha256(file.read_bytes()).hexdigest()
                  for file in sorted(path.rglob("*")) if file.is_file()},
    }


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def build_pilot(source, output, image=DEFAULT_IMAGE):
    require_harbor()
    if not re.fullmatch(r"[a-zA-Z0-9._:/-]+@sha256:[0-9a-f]{64}", image):
        raise ValueError("The task image must be pinned by SHA256 digest")
    data = source.read_bytes()
    examples = select_pilot(read_source(data))
    output.mkdir(parents=True, exist_ok=False)
    tasks_dir = output / "tasks"
    tasks_dir.mkdir()
    tasks = [describe_task(write_task(tasks_dir, example, image), example) for example in examples]
    manifest = {
        "adapter": "gsm8k-pilot-v1", "harbor_version": HARBOR_VERSION, "image": image,
        "source": {"repository": "openai/grade-school-math", "revision": REVISION,
                   "split": "test", "path": SOURCE_PATH, "git_blob": SOURCE_BLOB,
                   "sha256": sha256(data).hexdigest()},
        "task_count": len(tasks), "tasks": tasks, "training_admitted": False,
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="Download and verify the pinned source blob")
    fetch.add_argument("--source", type=Path, required=True)
    build = commands.add_parser("build", help="Materialize the fixed 24-task pilot offline")
    build.add_argument("--source", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--image", default=DEFAULT_IMAGE)
    args = parser.parse_args()
    if args.command == "fetch":
        fetch_source(args.source)
    else:
        manifest = build_pilot(args.source, args.output, args.image)
        print(f"Generated {manifest['task_count']} tasks in {args.output}")


if __name__ == "__main__":
    main()
