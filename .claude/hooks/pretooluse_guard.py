#!/usr/bin/env python3
"""PreToolUse safety guard for the Capability Intelligence Agent.

Reads the tool-call JSON from stdin and blocks (exit code 2) actions that are
irreversible, costly, prod-affecting, or that would leak secrets. Blocking emits an
explanation on stderr, which Claude Code surfaces to the model. All other tool calls
are allowed (exit 0). The guard fails OPEN on unexpected internal errors so it can
never wedge the session, but fails CLOSED for every pattern it recognises.

See CLAUDE.md safeguards (3, 5, 6, 10) and plan section "Human-in-the-loop gates".
"""
from __future__ import annotations

import json
import re
import sys

# --- Bash command patterns that require explicit human approval (block here) ---
DANGEROUS_BASH: list[tuple[str, str]] = [
    (r"\bgit\s+push\b.*(--force\b|--force-with-lease\b|(?<!\w)-f\b)",
     "Force-push is forbidden (never rewrite shared history)."),
    (r"\bterraform\s+(apply|destroy)\b",
     "terraform apply/destroy is a gated step (§8). Present the plan and get explicit approval; run it yourself."),
    (r"\bgcloud\s+run\b",
     "Cloud Run deploy/job execution is a gated step (§8). Get explicit approval and run it yourself."),
    (r"\bgcloud\s+(services\s+enable|sql\b|secrets\b|iam\b)\b",
     "Enabling APIs / creating Cloud SQL, secrets, or IAM bindings is a gated step (§8)."),
    (r"\bgcloud\b[^\n]*\bdeploy\b",
     "Deploys are a gated step (§8). Get explicit approval and run it yourself."),
    (r"\b(DROP\s+(TABLE|SCHEMA|DATABASE|INDEX)|TRUNCATE\b)",
     "Destructive SQL (DROP/TRUNCATE) requires explicit approval."),
    (r"\bDELETE\s+FROM\b(?!.*\bWHERE\b)",
     "Unbounded DELETE (no WHERE) requires explicit approval."),
]

# --- File paths that must never be written/edited (secrets & keys) ---
SECRET_PATH = re.compile(
    r"(^|/)\.env(\.|$)"            # .env, .env.local, ...
    r"|secret"                     # anything 'secret'
    r"|\.pem$|\.key$"              # key material
    r"|id_rsa"
    r"|credentials.*\.json$"
    r"|service-account.*\.json$"
    r"|.*-key\.json$",
    re.IGNORECASE,
)


def block(reason: str) -> None:
    sys.stderr.write(
        f"BLOCKED by .claude/hooks/pretooluse_guard.py: {reason}\n"
        "If this is intended, the human operator must perform/approve it explicitly (CLAUDE.md §10).\n"
    )
    sys.exit(2)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        # Can't parse input -> don't get in the way.
        sys.exit(0)

    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {}) or {}

    if tool == "Bash":
        cmd = str(ti.get("command", ""))
        for pattern, reason in DANGEROUS_BASH:
            if re.search(pattern, cmd, re.IGNORECASE):
                block(reason)

    elif tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = str(ti.get("file_path") or ti.get("notebook_path") or "")
        # Allow example/template files even if they contain 'env'.
        if path and not path.endswith((".example", ".sample", ".template")):
            if SECRET_PATH.search(path):
                block(f"refusing to write secret/key material at '{path}'. Use Secret Manager.")

    sys.exit(0)


if __name__ == "__main__":
    main()
