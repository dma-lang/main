#!/usr/bin/env python3
"""Fetch the local MiniLM sentence-embedding model (ONNX) into backend/models/minilm/.

Downloads the PINNED revision of sentence-transformers/all-MiniLM-L6-v2 (fp32 ONNX export +
tokenizer) from the HuggingFace CDN, verifies each file's SHA-256, and installs atomically
(tmp file -> rename). Idempotent: files already present with the right hash are kept.

This model is the LOCAL, deterministic, zero-spend embedder behind the hermetic dense half
(app/intelligence/local_embeddings.py). It is NOT committed to git (~90MB): dev machines and
the Docker build run this script; when the files are absent the app degrades to the token-hash
stub exactly as before, so nothing hard-fails on a missing model.

Usage:  python scripts/fetch_minilm.py [--dest backend/models/minilm]
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
import urllib.request
from pathlib import Path

REPO = "sentence-transformers/all-MiniLM-L6-v2"
# pinned snapshot (main as of 2026-07): model card lists the fp32 onnx export + fast tokenizer
REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
BASE = f"https://huggingface.co/{REPO}/resolve/{REVISION}"

# file -> (url path, sha256). SHA pins make the fetch reproducible and tamper-evident; refresh
# them deliberately when bumping REVISION (run with --print-hashes on the new revision).
FILES: dict[str, str] = {
    "model.onnx": f"{BASE}/onnx/model.onnx",
    "tokenizer.json": f"{BASE}/tokenizer.json",
}
SHA256: dict[str, str] = {
    "model.onnx": "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452",
    "tokenizer.json": "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, attempts: int = 4) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for n in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=120) as r, tmp.open("wb") as out:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            tmp.replace(
                dest
            )  # atomic install — an interrupted run never corrupts the model
            return
        except (
            Exception
        ) as exc:  # noqa: BLE001 - retry transient network errors with backoff
            wait = 2**n
            print(
                f"[fetch_minilm] {url} attempt {n}/{attempts} failed: {exc}; retry in {wait}s"
            )
            time.sleep(wait)
    raise SystemExit(
        f"[fetch_minilm] FAILED to download {url} after {attempts} attempts"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="backend/models/minilm")
    ap.add_argument(
        "--print-hashes",
        action="store_true",
        help="print SHA-256 of fetched files (for pinning)",
    )
    args = ap.parse_args()
    dest = Path(args.dest)
    for name, url in FILES.items():
        target = dest / name
        want = SHA256.get(name)
        if target.exists() and want and _sha256(target) == want:
            print(f"[fetch_minilm] {name}: present + hash ok, skipping")
            continue
        print(f"[fetch_minilm] downloading {name} …")
        _download(url, target)
        got = _sha256(target)
        if want and got != want:
            target.unlink(missing_ok=True)
            raise SystemExit(
                f"[fetch_minilm] {name}: SHA-256 mismatch (got {got}, want {want})"
            )
        print(
            f"[fetch_minilm] {name}: ok sha256={got} ({target.stat().st_size:,} bytes)"
        )
        if args.print_hashes:
            print(f'    "{name}": "{got}",')
    print(f"[fetch_minilm] model ready in {dest}")


if __name__ == "__main__":
    sys.exit(main())
