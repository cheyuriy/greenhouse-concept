# Integrations

The seam through which greenhouse content reaches external systems — a docs
destination (Obsidian, Notion) or a task tracker (Trello, Asana). Only the
contract and a `noop` reference implementation exist today; vendor code is
deliberately deferred.

## The contract (`base.py`)

An exporter is a class that:

1. is constructed with its config dict (from
   `[integrations.<name>]` in the workspace `greenhouse.toml`, or legacy
   `[tool.greenhouse.integrations.<name>]` in a `pyproject.toml` at its root);
2. implements the `Exporter` protocol:
   - `name: str`
   - `push_document(project, Document) -> ExportResult`
   - `upsert_task(project, OpenQuestionItem) -> ExportResult`
   - `health() -> bool` — cheap "can I reach the remote" check.

`Document` is typically a `final/` shard or `SPEC.md`; `OpenQuestionItem`
mirrors an open question into a tracker. Return honest `ExportResult`s —
`ok=False` with a detail beats a raised exception for expected failures.

## Adding a real exporter (the recipe)

1. Create `src/greenhouse/integrations/<name>.py` copying the shape of
   `noop.py`. Vendor SDK dependencies go in `pyproject.toml` as an optional
   extra: `[project.optional-dependencies] obsidian = [...]`.
2. Register the entry point:

   ```toml
   [project.entry-points."greenhouse.exporters"]
   obsidian = "greenhouse.integrations.obsidian:ObsidianExporter"
   ```

3. Configure it:

   ```toml
   [tool.greenhouse.integrations.obsidian]
   vault = "~/Vaults/specs"
   ```

4. `uv sync`, then it is reachable as `get_exporter("obsidian", workspace)`
   and via the MCP `export_document` tool.

Credentials never go in pyproject — read them from the environment inside the
exporter and fail `health()` clearly when absent.

Obsidian is the recommended first real exporter: it is files-on-disk, needs no
auth, and exercises the whole seam.
