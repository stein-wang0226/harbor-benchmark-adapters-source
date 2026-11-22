"""Run native Harbor controls and reconcile per-trial scoring evidence."""

import argparse
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from harbor.models.trial.result import TrialResult

from .adapter import ANSWER_PATH, describe_task, read_source, require_harbor, select_pilot, write_json
from .reference import load_reference


CASES = ("oracle", "wrong", "empty", "malformed", "comma")
UPSTREAM_EXTRACTOR = re.compile(r"#### (-?[0-9.,]+)")


def upstream_extract(text):
    # Mirrors extract_answer from the pinned OpenAI source, independently of grade.py.
    match = UPSTREAM_EXTRACTOR.search(text)
    return match.group(1).replace(",", "") if match else None


def prediction(example, case):
    gold = upstream_extract(example.upstream_answer)
    if gold is None:
        raise ValueError(f"Upstream scorer found no answer for {example.task_name}")
    if case == "empty":
        return ""
    if case == "malformed":
        return "not a number\n"
    if case == "wrong":
        return f"{Decimal(gold) + 1:f}\n"
    if case == "comma":
        return f"{Decimal(gold):,}\n"
    return f"{gold}\n"


def trial_artifact(trial_dir, path):
    entries = json.loads((trial_dir / "artifacts/manifest.json").read_text())
    matches = [entry for entry in entries if entry["source"] == ANSWER_PATH]
    if len(matches) != 1 or matches[0]["type"] != "file" or matches[0]["status"] != "ok":
        raise ValueError(f"Answer collection incomplete for {trial_dir.name}")
    collected = trial_dir / matches[0]["destination"]
    if (collected.is_symlink() or not collected.is_file()
            or not collected.resolve().is_relative_to(path.resolve())):
        raise ValueError(f"Unexpected collected path for {trial_dir.name}")
    return collected.read_bytes()


def check_trial(trial, expected_checksum, agent, provider):
    phases = (trial.environment_setup, trial.agent_setup, trial.agent_execution, trial.verifier)
    if (trial.exception_info or not trial.finished_at or any(not phase or not phase.started_at
            or not phase.finished_at or phase.finished_at < phase.started_at for phase in phases)):
        raise ValueError(f"Trial did not finish cleanly: {trial.trial_name}")
    if (trial.task_checksum != expected_checksum or trial.verifier_environment_mode != "separate"
            or trial.agent_info.name != agent or trial.agent_info.model_info is not None
            or trial.config.environment.type != provider):
        raise ValueError(f"Unexpected native trial configuration: {trial.trial_name}")


def reconcile_trial(result_path, example, task, case, provider, is_correct):
    raw = result_path.read_bytes()
    trial = TrialResult.model_validate_json(raw)
    agent = "oracle" if case == "oracle" else "gsm8k-answer-replay"
    check_trial(trial, task["harbor_checksum"], agent, provider)
    trial_dir = result_path.parent
    submission = trial_artifact(trial_dir, trial_dir / "artifacts")
    actual_digest = sha256(submission).hexdigest()
    verifier = trial_dir / "verifier"
    evidence = json.loads((verifier / "answer-evidence.json").read_text())
    if evidence != {"status": "read", "bytes_read": len(submission), "sha256": actual_digest}:
        raise ValueError(f"Verifier received different bytes: {trial.trial_name}")
    if submission != prediction(example, case).encode():
        raise ValueError(f"Submission differs from planned bytes: {trial.trial_name}")
    expected = int(is_correct("#### " + submission.decode(), {"answer": example.upstream_answer}))
    if expected != int(case in {"oracle", "comma"}):
        raise ValueError(f"Upstream reward differs from the planned control: {trial.trial_name}")
    reward_bytes = (verifier / "reward.txt").read_bytes()
    if trial.verifier_result.rewards != {"reward": expected} or reward_bytes.strip() != str(expected).encode():
        raise ValueError(f"Harbor and upstream rewards differ: {trial.trial_name}")
    return {"case": case, "task": trial.task_name, "trial_id": str(trial.id), "trial": trial.trial_name,
            "harbor_checksum": trial.task_checksum, "reward": expected, "reference_reward": expected,
            "submission_bytes": len(submission), "submission_sha256": actual_digest,
            "trial_sha256": sha256(raw).hexdigest(), "reward_sha256": sha256(reward_bytes).hexdigest()}


def run_case(pilot, work, args, case, examples, tasks, is_correct):
    job = work / case
    if job.exists():
        raise ValueError(f"Use a fresh work directory. Job already exists: {job}")
    selected = examples
    if case in {"empty", "malformed", "comma"}:
        selected = [next(item for item in examples if abs(Decimal(item.gold)) >= 1000)]
    command = [str(Path(sys.executable).parent / "harbor"), "run", "--path", str(pilot / "tasks"),
               "--env", args.provider, "--jobs-dir", str(work), "--job-name", case,
               "--n-attempts", "1", "--n-concurrent", str(args.concurrency), "--max-retries", "0"]
    if case == "oracle":
        command += ["--agent", "oracle"]
    else:
        answers = {tasks[item.task_name]["files"]["instruction.md"]: prediction(item, case) for item in selected}
        replay_path = work / f"{case}-replay.json"
        write_json(replay_path, answers)
        command += ["--agent", "adapters.gsm8k.controls:AnswerReplayAgent", "--ak", f"answers_path={replay_path}"]
    if len(selected) == 1:
        command += ["--include-task-name", selected[0].task_name]
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]))
    with (work / f"{case}.log").open("x") as log:
        subprocess.run(command, env=env, check=True, timeout=1800, stdout=log, stderr=subprocess.STDOUT)
    summaries = collect_case(job, case, args.provider, selected, tasks, is_correct)
    write_json(work / f"{case}-summary.json", summaries)
    print(f"{case}: {len(summaries)} native trials agree with the upstream scorer", flush=True)


def collect_case(job, case, provider, examples, tasks, is_correct):
    results = [path for path in job.glob("*/result.json")]
    by_name = {json.loads(path.read_text())["task_name"]: path for path in results}
    if len(results) != len(examples) or set(by_name) != {item.task_name for item in examples}:
        raise ValueError(f"Unexpected native trial coverage in {job}")
    return [reconcile_trial(by_name[item.task_name], item, tasks[item.task_name], case, provider, is_correct)
            for item in examples]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--scorer", type=Path, required=True, help="Pinned OpenAI GSM8K dataset.py")
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--provider", choices=("podman", "docker"), default="podman")
    parser.add_argument("--concurrency", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--case", action="append", choices=CASES)
    args = parser.parse_args()
    require_harbor()
    _, is_correct = load_reference(args.scorer)
    pilot = args.pilot.resolve()
    examples = select_pilot(read_source(args.source.read_bytes()))
    tasks = {item.task_name: describe_task(pilot / "tasks" / item.task_name, item) for item in examples}
    if list(tasks.values()) != json.loads((pilot / "manifest.json").read_text())["tasks"]:
        raise ValueError("Task packages do not match the build manifest")
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    for case in args.case or CASES:
        run_case(pilot, work, args, case, examples, tasks, is_correct)


if __name__ == "__main__":
    main()
