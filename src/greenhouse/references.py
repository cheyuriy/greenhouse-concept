"""history/references/ — the extraction cache: distilled
material from ad-hoc links/files, looked up before any fetch, expiring when
volatile, promotable to sources/ when foundational."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import history, mdutil
from .models import GreenhouseError
from .state import today

if TYPE_CHECKING:
    from .state import Project

DEFAULT_EXPIRES_DAYS = 90


def _ref_files(project: Project) -> list[Path]:
    if not project.references_dir.exists():
        return []
    return sorted(project.references_dir.glob("ref-*.md"))


def _record(project: Project, path: Path) -> dict[str, Any]:
    fm, body = mdutil.parse_frontmatter(path.read_text())
    fm = fm or {}
    fm["path"] = str(path.relative_to(project.root))
    fm["body"] = body
    return fm


def list_references(project: Project) -> list[dict[str, Any]]:
    return [_record(project, p) for p in _ref_files(project)]


def get(project: Project, ref_id: str) -> dict[str, Any] | None:
    for p in _ref_files(project):
        if p.name.startswith(f"{ref_id}-") or p.stem == ref_id:
            return _record(project, p)
    return None


# ---------------------------------------------------------------------------
# Add / lookup / staleness
# ---------------------------------------------------------------------------


def add_reference(
    project: Project,
    origin: str,
    title: str,
    body: str,
    freshness: str = "volatile",
    expires_after_days: int = DEFAULT_EXPIRES_DAYS,
    sections: list[str] | None = None,
    retrieved_in: str | None = None,
    origin_hash: str | None = None,
    date: dt.date | None = None,
) -> str:
    """Cache an extraction. The body should include what was pulled out AND an
    explicit 'Not extracted' list marking the cache boundary."""
    if freshness not in ("stable", "volatile"):
        raise GreenhouseError("freshness must be 'stable' or 'volatile'")
    spec = project.spec()
    for sid in sections or []:
        if not spec.section_by_id(sid):
            raise GreenhouseError(f"section {sid!r} does not resolve")

    date = date or today()
    ref_id = project.next_ref_id()
    origin_kind = "url" if re.match(r"https?://", origin) else "file"
    if origin_kind == "file" and origin_hash is None:
        opath = Path(origin).expanduser()
        if opath.exists():
            origin_hash = "sha256:" + hashlib.sha256(opath.read_bytes()).hexdigest()

    fm: dict[str, Any] = {
        "id": ref_id,
        "type": "reference",
        "title": title,
        "origin": origin,
        "origin_kind": origin_kind,
        "origin_hash": origin_hash,
        "retrieved": date,
        "retrieved_in": retrieved_in,
        "sections": sections or [],
        "freshness": freshness,
        "expires_after_days": expires_after_days,
        "supersedes": None,
    }
    project.references_dir.mkdir(parents=True, exist_ok=True)
    path = project.references_dir / f"{ref_id}-{history.slugify_for_filename(title)}.md"
    path.write_text(mdutil.dump_frontmatter(fm, body))
    history.regenerate_index(project)
    return ref_id


def staleness(record: dict[str, Any]) -> str | None:
    """None if fresh; otherwise why the cache entry should be refetched."""
    if record.get("promoted_to"):
        return f"promoted to {record['promoted_to']}"
    if record.get("freshness") == "volatile":
        retrieved = record.get("retrieved")
        days = int(record.get("expires_after_days") or DEFAULT_EXPIRES_DAYS)
        if retrieved and (today() - retrieved).days > days:
            return f"expired ({retrieved} + {days}d)"
    return None


def lookup(project: Project, origin: str) -> dict[str, Any] | None:
    """Hit-or-miss by origin URL/path. Run this BEFORE any fetch; a fresh hit
    means the fetch is skipped (see CLAUDE.md, Sources and references)."""
    origin_norm = origin.rstrip("/")
    for p in _ref_files(project):
        record = _record(project, p)
        if str(record.get("origin", "")).rstrip("/") == origin_norm:
            record["stale"] = staleness(record)
            return record
    return None


def check(project: Project) -> list[dict[str, Any]]:
    """Expired volatile references + origin files that changed on disk."""
    findings: list[dict[str, Any]] = []
    for record in list_references(project):
        stale = staleness(record)
        if stale:
            findings.append({"reference": record["id"], "kind": "stale", "detail": stale})
        if record.get("origin_kind") == "file" and record.get("origin_hash"):
            opath = Path(str(record["origin"])).expanduser()
            if opath.exists():
                digest = "sha256:" + hashlib.sha256(opath.read_bytes()).hexdigest()
                if digest != record["origin_hash"]:
                    findings.append(
                        {"reference": record["id"], "kind": "origin-changed",
                         "detail": f"{record['origin']} differs from cached hash"}
                    )
    return findings


# ---------------------------------------------------------------------------
# Promotion to sources/
# ---------------------------------------------------------------------------


def promote(project: Project, ref_id: str, date: dt.date | None = None) -> str:
    """A throwaway link turned foundational: materialise the extraction under
    sources/, register it, and mark the reference promoted. The reference file
    stays, so existing `ref:` citations keep resolving."""
    from . import sources as sources_mod

    record = get(project, ref_id)
    if record is None:
        raise GreenhouseError(f"Unknown reference: {ref_id}")
    date = date or today()

    dest = project.sources_dir / f"{ref_id}-{history.slugify_for_filename(str(record.get('title', '')))}.md"
    if dest.exists():
        raise GreenhouseError(f"{dest.name} already exists in sources/")
    dest.write_text(
        f"# {record.get('title', ref_id)}\n\n"
        f"> Promoted from reference {ref_id}; origin: {record.get('origin')}\n\n"
        + str(record.get("body", "")).strip()
        + "\n"
    )
    src_id = sources_mod.add_source(
        project,
        str(dest),
        title=str(record.get("title", ref_id)),
        kind="note",
        relates_to=[str(s) for s in record.get("sections") or []],
        note=f"Promoted from {ref_id} ({record.get('origin')})",
        added_by="promotion",
        date=date,
    )

    ref_path = project.root / str(record["path"])
    fm, body = mdutil.parse_frontmatter(ref_path.read_text())
    fm["promoted_to"] = src_id
    ref_path.write_text(mdutil.dump_frontmatter(fm, body))
    history.regenerate_index(project)
    return src_id
