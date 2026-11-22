# Harbor Benchmark Adapters

Version `v0.1.0` converts a fixed 24-question sample from the original GSM8K test split into native Harbor tasks. The sample is intended for integration checks and verifier regression tests. It was selected in equal groups by absolute answer magnitude and is best used to exercise the submission and grading path. [Pinned OpenAI source](https://github.com/openai/grade-school-math/tree/3101c7d5072418e28b9008a6636bde82a006892c)

## Rebuild the preview

From a fresh checkout, install Python 3.12 dependencies with `uv`. The `fetch` command checks the exact upstream Git blob. The build and package commands use fresh output paths.

```bash
uv sync --locked --python 3.12
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m adapters.gsm8k.adapter fetch \
  --source runs/source/gsm8k-test.jsonl
.venv/bin/python -m adapters.gsm8k.adapter build \
  --source runs/source/gsm8k-test.jsonl --output runs/gsm8k-pilot
.venv/bin/python -m adapters.gsm8k.package \
  --pilot runs/gsm8k-pilot --output runs/pilot-tasks.tar.gz
shasum -a 256 runs/gsm8k-pilot/manifest.json runs/pilot-tasks.tar.gz
```

| Hugging Face v0.1.0 file | SHA-256 |
| --- | --- |
| pilot-manifest.json | fdfcae510fb15ed0c6303196ffa92af5409955c4794b3a83618b2a995fa92e17 |
| pilot-tasks.tar.gz | 3e418f1ce9528a93f7bd13e4403806662b4dee79e3356e5ee7d7372b96c12c2f |

The locally generated `manifest.json` corresponds to `pilot-manifest.json` in the dataset release. It lists source rows, Harbor checksums, and SHA-256 for each task file. Tar headers and the gzip timestamp are fixed. If gzip implementations produce different compressed bytes, compare the unpacked manifest and task file hashes.

## Run Harbor controls

Use a running Podman backend and Harbor 0.24.0 from the lockfile. The manifest identifies the pinned image required by the backend. The agent and the separate verifier run without network access. Download the pinned upstream scorer before running the controls.

```bash
mkdir -p runs/reference
curl -fsSL \
  https://raw.githubusercontent.com/openai/grade-school-math/3101c7d5072418e28b9008a6636bde82a006892c/grade_school_math/dataset.py \
  -o runs/reference/openai-dataset.py
.venv/bin/python -m adapters.gsm8k.acceptance \
  --source runs/source/gsm8k-test.jsonl --scorer runs/reference/openai-dataset.py \
  --pilot runs/gsm8k-pilot --work runs/gsm8k-native-check --provider podman
```

The script runs 24 Oracle trials, 24 wrong-answer trials, and three format controls. It checks the trial stages, task checksum, the SHA-256 of the collected submission, and the Harbor and upstream rewards for those same bytes. Use `--case oracle`, `--case wrong`, `--case empty`, `--case malformed`, or `--case comma` to reproduce specific controls in a fresh work directory. The preview recorded 51 scored controls and one infrastructure failure that was retained as unscored and replayed successfully.

The agent writes a single decimal number to `/app/output/answer.txt`. Keep the task's `tests/` and `solution/` paths outside the agent workspace when integrating another runner. The file-based protocol accepts fewer response formats than the upstream completion extractor.

## Licensing

The project-authored adapter, task templates, and verifier are available under the MIT License. The original GSM8K material retains OpenAI's MIT notice. The task archive includes both notices. [Project license](LICENSE) · [OpenAI license](adapters/gsm8k/LICENSE.openai)
