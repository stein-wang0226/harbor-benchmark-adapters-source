# Harbor Benchmark Adapters

GSM8K v0.2.0 converts all 7,473 train and 1,319 test examples from the pinned OpenAI release to native Harbor tasks. Both splits include a source manifest and a Harbor Registry dataset manifest. [Download the v0.2.0 archives and acceptance results](https://huggingface.co/datasets/steinwang/gsm8k-harbor/tree/v0.2.0) · [24-task v0.1.0 preview](https://github.com/stein-wang0226/harbor-benchmark-adapters-source/releases/tag/v0.1.0)

## Rebuild

```bash
uv sync --locked --package harbor-gsm8k-adapter --python 3.12
uv run --package harbor-gsm8k-adapter gsm8k --output-dir datasets/gsm8k-test
uv run --package harbor-gsm8k-adapter gsm8k --split train --output-dir datasets/gsm8k-train
```

The adapter can also use local copies of the pinned upstream files through `--source`. Read the [adapter guide](src/gsm8k/README.md) for task selection and Oracle commands.

## Acceptance

The control runner checks Oracle and wrong-answer submissions on each task plus three format controls per split. It compares the transferred answer bytes and verifier reward with the pinned upstream scorer. It records valid zero scores separately from infrastructure failures.

`python -m gsm8k.validation plan --help` describes the input and output layout for the validation plan. Each plan fixes the task digest and expected submission for every control. `python -m gsm8k.validation run --help` and `python -m gsm8k.validation audit --help` describe native execution and readback.

## Licensing

The adapter and task code use the [MIT License](LICENSE). The original GSM8K material retains its [OpenAI MIT notice](src/gsm8k/src/gsm8k/LICENSE.openai).
