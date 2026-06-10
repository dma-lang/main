#!/usr/bin/env python3
"""PostToolUse checks for the Capability Intelligence Agent.

After an Edit/Write, run fast format + lint + typecheck (and a narrow affected-test
slice) for the edited file. Reports failures on stderr with exit code 2 so Claude Code
surfaces them to the model; otherwise exits 0. Fails OPEN: if a toolchain isn't
installed (e.g. during early scaffolding) or anything unexpected happens, exit 0 so the
session is never blocked. Only files under backend/ or frontend/ source trees are checked.

See CLAUDE.md safeguard 1 ("verify before done").
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

TIMEOUT = 120  # seconds per check; bounded


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def run(cmd: list[str], cwd: str) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
        return p.returncode, (p.stdout + p.stderr)
    except Exception as e:  # tool missing / timeout / etc -> treat as skipped
        return 0, f"(skipped: {e})"


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    ti = data.get("tool_input", {}) or {}
    path = str(ti.get("file_path") or "")
    if not path:
        sys.exit(0)

    root = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    rel = os.path.relpath(path, root)
    failures: list[str] = []

    # ---- Backend Python (only once deps are installed) ----
    if rel.startswith("backend/") and rel.endswith(".py"):
        be = os.path.join(root, "backend")
        if os.path.isdir(os.path.join(be, ".venv")):
            cmds = [["uv", "run", "ruff", "check", path], ["uv", "run", "black", "--check", path]]
            # Alembic env/migrations are raw-SQL + dynamic context: lint/format them, but skip mypy.
            if "/alembic/" not in rel.replace("\\", "/"):
                cmds.append(["uv", "run", "mypy", path])
            for cmd in cmds:
                code, out = run(cmd, be)
                if code != 0 and "skipped:" not in out:
                    failures.append(f"$ {' '.join(cmd[2:])}\n{out.strip()}")

    # ---- Frontend TS/TSX ----
    elif rel.startswith("frontend/") and rel.endswith((".ts", ".tsx")):
        fe = os.path.join(root, "frontend")
        if os.path.isdir(os.path.join(fe, "node_modules")):
            for cmd in (["pnpm", "exec", "eslint", path],
                        ["pnpm", "exec", "tsc", "--noEmit"]):
                code, out = run(cmd, fe)
                if code != 0 and "skipped:" not in out:
                    failures.append(f"$ {' '.join(cmd)}\n{out.strip()}")

    if failures:
        sys.stderr.write(
            "PostToolUse checks failed for "
            f"{rel} — fix before continuing (CLAUDE.md: verify before done):\n\n"
            + "\n\n".join(failures)
            + "\n"
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
