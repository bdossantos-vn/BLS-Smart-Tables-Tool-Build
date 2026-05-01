#!/usr/bin/env python3
"""Fail when app code changes without PLAN/STATUS/GUIDE updates.

This is a lightweight repo guard, not a semantic documentation generator.
It ensures that meaningful app changes are accompanied by doc updates in:

- PLAN.md
- STATUS.md
- GUIDE.md
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


DOC_FILES = {"PLAN.md", "STATUS.md", "GUIDE.md"}
WATCHED_PREFIXES = ("app/", "src/", ".streamlit/")
WATCHED_FILES = {"app.py"}


def _git_diff_names(base_ref: str, head_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}..{head_ref}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _is_watched_change(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized in WATCHED_FILES:
        return True
    return normalized.startswith(WATCHED_PREFIXES)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Base git ref or SHA")
    parser.add_argument("--head", required=True, help="Head git ref or SHA")
    args = parser.parse_args()

    changed_files = _git_diff_names(args.base, args.head)
    watched_changes = sorted(path for path in changed_files if _is_watched_change(path))
    doc_changes = sorted(path for path in changed_files if Path(path).name in DOC_FILES)

    if not watched_changes:
        print("docs-sync: no watched app changes detected; skipping doc enforcement.")
        return 0

    if doc_changes:
        print("docs-sync: watched app changes detected and docs were updated.")
        print("Updated docs:", ", ".join(doc_changes))
        return 0

    print("docs-sync: app changes detected without PLAN/STATUS/GUIDE updates.", file=sys.stderr)
    print("", file=sys.stderr)
    print("Changed app files:", file=sys.stderr)
    for path in watched_changes:
        print(f"- {path}", file=sys.stderr)
    print("", file=sys.stderr)
    print("Please update at least one of:", file=sys.stderr)
    for name in sorted(DOC_FILES):
        print(f"- {name}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
