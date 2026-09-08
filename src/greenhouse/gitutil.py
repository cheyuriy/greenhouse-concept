"""The only place the package talks to git — and only to *read*.

Committing stays a visible line in the skills (CLAUDE.md git protocol); the
CLI merely resolves revisions so no sha is ever copied by hand.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .models import GreenhouseError

FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def rev_parse(repo_root: Path, rev: str) -> str:
    """Resolve `rev` (HEAD, a branch, a short sha…) to the full commit sha."""
    if FULL_SHA_RE.match(rev):
        return rev
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError as exc:
        raise GreenhouseError("git is not available on PATH") from exc
    sha = out.stdout.strip()
    if out.returncode != 0 or not FULL_SHA_RE.match(sha):
        raise GreenhouseError(f"{rev!r} does not resolve to a commit in {repo_root}")
    return sha
