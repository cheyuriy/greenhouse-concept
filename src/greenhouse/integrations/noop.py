"""Reference Exporter implementation: does nothing, remembers everything.

The shape every real exporter copies — construction from a config dict, the
three protocol methods, honest ExportResults.
"""

from __future__ import annotations

from typing import Any

from .base import Document, ExportResult, OpenQuestionItem


class NoopExporter:
    name = "noop"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.pushed: list[tuple[str, Document]] = []
        self.tasks: list[tuple[str, OpenQuestionItem]] = []

    def push_document(self, project: str, doc: Document) -> ExportResult:
        self.pushed.append((project, doc))
        return ExportResult(
            ok=True,
            detail=f"noop: would push {doc.path!r} ({len(doc.content)} chars) for {project}",
            remote_ref=None,
        )

    def upsert_task(self, project: str, question: OpenQuestionItem) -> ExportResult:
        self.tasks.append((project, question))
        return ExportResult(
            ok=True,
            detail=f"noop: would upsert task {question.id} ({project}): {question.text}",
        )

    def health(self) -> bool:
        return True
