"""Pin the Dockerfile's base image to the digest its tag points at now (D28).

uv run python scripts/pin_base_image.py            resolve the tag, write FROM <image>:<tag>@sha256:<digest>
uv run python scripts/pin_base_image.py --check    exit 1 if the tag has moved since the pin (a rebuild is due)

Needs Docker (`docker buildx imagetools inspect`, a registry query: nothing is pulled). The tag stays in the line so
a reader sees what was pinned; the digest is what Docker uses.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
FROM = re.compile(r"^FROM (?P<image>[^\s@]+:[^\s@]+)(?:@(?P<digest>sha256:[0-9a-f]{64}))?(?P<rest>.*)$", re.M)


def base(text: str) -> re.Match:
    found = list(FROM.finditer(text))
    if len(found) != 1:
        raise SystemExit(f"FAIL expected one FROM <image>:<tag> line in the Dockerfile, found {len(found)}")
    return found[0]


def pinned(text: str, digest: str) -> str:
    m = base(text)
    return f"{text[: m.start()]}FROM {m['image']}@{digest}{m['rest']}{text[m.end() :]}"


def current_digest(image: str) -> str:
    cmd = ["docker", "buildx", "imagetools", "inspect", image, "--format", "{{.Manifest.Digest}}"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603, S607
    digest = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise SystemExit(f"FAIL could not resolve {image}: {result.stderr.strip()[-200:] or digest}")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if the tag points elsewhere now")
    args = parser.parse_args()
    text = DOCKERFILE.read_text(encoding="utf-8")
    m = base(text)
    digest = current_digest(m["image"])
    if args.check:
        if m["digest"] == digest:
            print(f"OK   {m['image']} still at {digest}")
            return 0
        print(f"FAIL {m['image']} moved: pinned {m['digest']}, now {digest}")
        return 1
    if m["digest"] == digest:
        print(f"unchanged {m['image']}@{digest}")
        return 0
    DOCKERFILE.write_text(pinned(text, digest), encoding="utf-8")
    print(f"pinned {m['image']}@{digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
