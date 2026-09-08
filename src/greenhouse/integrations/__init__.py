"""Integrations seam — see base.py for the Exporter protocol and README.md
for how to add a real exporter (Obsidian, Notion, Trello, Asana, …)."""

from .base import (  # noqa: F401
    Document,
    Exporter,
    ExportResult,
    OpenQuestionItem,
    available_exporters,
    get_exporter,
    load_config,
)
