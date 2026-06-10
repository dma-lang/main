#!/usr/bin/env python3
"""Extract the self-contained CIA prototype HTML into reviewable sources.

The prototype (docs/specs/prototype/) is a single HTML file with three inline bundler blocks:
  <script type="__bundler/manifest">      {uuid: {data: base64, compressed: bool, mime}}
  <script type="__bundler/ext_resources"> [{id: friendlyName, uuid}]  (RES() lookup map)
  <script type="__bundler/template">      JSON-encoded HTML document that loads assets by uuid

Output (untracked, .gitignored):
  .prototype/assets/<uuid>.<ext>   every decoded asset
  .prototype/named/<friendly>      content-sniffed copies (ui.jsx, config.js, design-system.css …)
  .prototype/template.html         the template with uuid refs rewritten to assets/ paths —
                                   opens from file:// for visual-reference passes (scripts/qa_visual.mjs)
  .prototype/index.json            uuid -> {mime, bytes, name}

Usage: python3 scripts/extract_prototype.py [--src path/to/prototype.html] [--out .prototype]
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SRC = REPO / "docs/specs/prototype/Capability_Intelligence_Agent_prototype.html"

EXT = {
    "image/png": "png",
    "font/ttf": "ttf",
    "text/javascript": "js",
    "application/javascript": "js",
    "text/css": "css",
    "application/json": "json",
}


def block(html: str, kind: str) -> str:
    m = re.search(rf'<script type="__bundler/{kind}">(.*?)</script>', html, re.S)
    if not m:
        raise SystemExit(f"no __bundler/{kind} block — not a bundled prototype?")
    return m.group(1)


def sniff(name_hint: str, mime: str, data: bytes) -> str | None:
    """Friendly name for the assets fidelity work actually reads."""
    if mime == "font/ttf":
        return "dmsans.ttf"
    if mime.endswith("javascript"):
        head = data[:200_000].decode("utf-8", "replace")
        if "window.PAGES[" in head:
            return "ui.jsx"  # the unminified compiled app source
        if "CIA_APP" in head:
            return "config.js"  # subverticals / offerings / valueChain / chains
        if "CIA_CATALOG" in head:
            return "catalog.js"  # 851-subcap mock catalogue
        if "CIA_STORIES" in head:
            return "stories.js"
        if "react-dom" in head[:2000] or "ReactDOM" in head:
            return "react-dom.js"
        return "react.js"  # remaining vendor lib (loaded before the app bundle)
    if mime == "text/css":
        return None  # css lives in the template, not the manifest
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--out", type=Path, default=REPO / ".prototype")
    args = ap.parse_args()

    html = args.src.read_text(encoding="utf-8")
    manifest: dict[str, dict] = json.loads(block(html, "manifest"))
    ext_resources: list[dict] = json.loads(block(html, "ext_resources"))
    template: str = json.loads(block(html, "template"))

    assets = args.out / "assets"
    named = args.out / "named"
    assets.mkdir(parents=True, exist_ok=True)
    named.mkdir(parents=True, exist_ok=True)

    friendly = {e["uuid"]: e["id"] for e in ext_resources}
    index: dict[str, dict] = {}
    for uuid, entry in manifest.items():
        data = base64.b64decode(entry["data"])
        if entry.get("compressed"):
            data = gzip.decompress(data)
        ext = EXT.get(entry.get("mime", ""), "bin")
        (assets / f"{uuid}.{ext}").write_bytes(data)
        name = friendly.get(uuid) or sniff(uuid, entry.get("mime", ""), data)
        if name:
            suffix = "" if "." in name else f".{ext}"
            (named / f"{name}{suffix}").write_bytes(data)
        index[uuid] = {"mime": entry.get("mime"), "bytes": len(data), "name": name}
        # the template references assets by bare uuid; rewrite to the decoded file
        template = template.replace(uuid, f"assets/{uuid}.{ext}")

    # the inline stylesheets ARE the design system — split them out for diffing
    for i, css in enumerate(re.findall(r"<style[^>]*>(.*?)</style>", template, re.S)):
        (named / f"style-{i}.css").write_text(css, encoding="utf-8")

    (args.out / "template.html").write_text(template, encoding="utf-8")
    (args.out / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    total = sum(v["bytes"] for v in index.values())
    print(f"extracted {len(index)} assets ({total / 1e6:.1f} MB) -> {args.out}")
    for uuid, v in sorted(index.items(), key=lambda kv: -kv[1]["bytes"]):
        print(f"  {uuid[:13]}  {v['bytes']:>9}  {v['mime']:<24} {v['name'] or ''}")


if __name__ == "__main__":
    main()
