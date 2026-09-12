#!/usr/bin/env python3
"""Generate PocketCHIRP Engine's neutral build-time radio chooser catalog."""
from __future__ import annotations
import argparse
import json
import os
import sys


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--python-root", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--chirp-commit", default="")
    args = p.parse_args()

    python_root = os.path.abspath(args.python_root)
    sys.path.insert(0, python_root)
    import bridge  # noqa: E402

    root = bridge._build_bundled_catalog_from_chirp()
    radios = root.get("radios") or []
    if not radios:
        raise SystemExit("Generated radio catalog is empty")
    # This file is stock CHIRP only. Runtime custom rows must never be baked in.
    radios = [r for r in radios if not r.get("customDriver")]
    root["radios"] = radios
    root["loadedCount"] = len(radios)
    root["customDriverCount"] = 0
    root["prebuiltBootstrap"] = True
    root["chirpCommit"] = str(args.chirp_commit or "")

    output = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    tmp = output + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(root, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write("\n")
    os.replace(tmp, output)
    print("PocketCHIRP Engine: generated prebuilt radio catalog with %d entries" % len(radios))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
