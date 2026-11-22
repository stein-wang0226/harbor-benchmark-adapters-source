"""Package the fixed v0.1.0 preview for distribution as a Harbor task archive."""

import argparse
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory


MANIFEST_SHA256 = "fdfcae510fb15ed0c6303196ffa92af5409955c4794b3a83618b2a995fa92e17"


def add_bytes(archive, data, name, executable=False):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o755 if executable else 0o644
    archive.addfile(info, BytesIO(data))


def archive_task(archive, pilot, task):
    for name, digest in task["files"].items():
        path = f"tasks/{task['task_name']}/{name}"
        data = (pilot / path).read_bytes()
        if sha256(data).hexdigest() != digest:
            raise ValueError(f"Task file differs from the release manifest: {path}")
        add_bytes(archive, data, path, executable=name.endswith(".sh"))


def write_archive(pilot, destination, manifest):
    license_path = Path(__file__).with_name("LICENSE.openai")
    with destination.open("xb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w|") as archive:
            add_bytes(archive, license_path.read_bytes(), "LICENSE.openai")
            add_bytes(archive, manifest, "manifest.json")
            for task in json.loads(manifest)["tasks"]:
                archive_task(archive, pilot, task)


def package_pilot(pilot, output):
    manifest = (pilot / "manifest.json").read_bytes()
    if sha256(manifest).hexdigest() != MANIFEST_SHA256:
        raise ValueError("Expected the exact manifest for the 24-task v0.1.0 preview")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as directory:
        candidate = Path(directory) / "preview.tar.gz"
        write_archive(pilot, candidate, manifest)
        output.hardlink_to(candidate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package_pilot(args.pilot, args.output)


if __name__ == "__main__":
    main()
