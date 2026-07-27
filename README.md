# Obsidian Agent MCP Server

Local MCP server for managing an Obsidian vault as a personal knowledge system.

The server keeps your Markdown vault as the source of truth, then adds a local
SQLite index for search, note graph diagnostics, curated knowledge graph data,
safe edits, audit logs, and restorable backups.

## Requirements

- Python with `fastmcp` installed
- Dependencies from `requirements.txt`

```powershell
pip install -r requirements.txt
```

This project uses only the Python standard library beyond `fastmcp`.

Optional editable install:

```powershell
pip install -e .
```

After installation, the CLI is available as:

```powershell
obsidian-agent rebuild
obsidian-agent search "ranking"
```

## Vault Path

By default, the server uses a project-local `obsidian_vault` folder.

Set `OBSIDIAN_VAULT_PATH` to point at your real Obsidian vault:

```powershell
$env:OBSIDIAN_VAULT_PATH="C:\Users\minso\Documents\Obsidian Vault"
```

You can also use a TOML config file. By default the server looks for
`obsidian_agent.toml` next to `server.py`; set `OBSIDIAN_AGENT_CONFIG` to use a
different path.

```toml
vault_path = "C:/Users/minso/Documents/Obsidian Vault"
ignored_folders = [".obsidian_agent", ".trash", "templates"]
```

`OBSIDIAN_VAULT_PATH` takes precedence over `vault_path` from the config file.

The server stores internal data under:

```text
.obsidian_agent/
  index.sqlite3
  audit.log
  backups/
```

Files under `.obsidian_agent` are excluded from note indexing.

## Run

```powershell
python server.py
```

The server runs with MCP `stdio` transport.

Example MCP client configuration:

```json
{
  "mcpServers": {
    "obsidian-agent": {
      "command": "python",
      "args": ["C:\\Users\\minso\\Desktop\\Min\\Dev\\github\\obsidian_agent\\server.py"],
      "env": {
        "OBSIDIAN_VAULT_PATH": "C:\\Users\\minso\\Documents\\Obsidian Vault"
      }
    }
  }
}
```

If `python` is not on PATH, replace it with the full Python executable path.

## Test

```powershell
C:\Users\minso\AppData\Local\Python\pythoncore-3.14-64\python.exe -m unittest test_server.py
```

Or run unittest discovery against the split test package:

```powershell
C:\Users\minso\AppData\Local\Python\pythoncore-3.14-64\python.exe -m unittest discover
```

The tests use temporary vaults and do not touch your real Obsidian vault.

Test files are split by responsibility:

```text
tests/
  helpers.py
  test_server_integration.py
  test_utilities.py
```

`test_server.py` remains as a compatibility entry point for the older single-file
test command.

## Project Structure

```text
server.py                 MCP tool/resource/prompt registration and CLI compatibility
obsidian_agent/
  cli.py                  CLI argument parsing and command dispatch
  config.py               TOML/env configuration loading
  notes.py                Note path, frontmatter, tag, and wiki-link helpers
  index.py                SQLite schema, FTS, and index row helpers
  services.py             Note search, index sync, graph, and status services
  knowledge.py            Curated entity/relation graph persistence
  extraction.py           Rule-based entity and relation proposals
  safety.py               Safe edits, backups, restore, and audit logs
  workflows.py            Daily notes, inbox capture, and personal workflows
tests/                    Integration and unit tests
```

## CLI

The CLI exposes small maintenance commands. These run without starting the MCP
server.

```powershell
python server.py rebuild
python server.py sync
python server.py search "ranking" --limit 5
python server.py graph
python server.py graph --resolved-only
python server.py missing-links
python server.py orphans
python server.py knowledge-graph
python server.py export-kg
python server.py status
```

Use the same `OBSIDIAN_VAULT_PATH` environment variable for CLI commands.
If installed with `pip install -e .`, replace `python server.py` with
`obsidian-agent`.

## Core Tools

### Note Files

- `create_note(title, content, tags=None)`
- `append_to_note(title, content)`
- `create_daily_note(day=None)`
- `capture_inbox(content, source="")`
- `add_review_item(content, source="")`
- `list_review_queue()`
- `complete_review_item(line)`
- `read_note(title)`
- `list_notes()`
- `search_notes(query)`

Titles may include `/` for folders. Invalid Windows filename characters are
sanitized, and paths are constrained to the configured vault.

`create_daily_note()` creates `Daily/YYYY-MM-DD.md` with a daily template.
`capture_inbox()` appends timestamped capture items to `Inbox.md`.
`add_review_item()` appends unchecked review tasks to `Review Queue.md`, and
`list_review_queue()` returns pending review items with source metadata and line
numbers. `complete_review_item()` marks one pending item done by line number.

### Project Memory

- `create_project_workspace(project_name)`
- `log_project_update(project_name, content)`
- `record_project_decision(project_name, decision, rationale="")`
- `capture_project_idea(project_name, idea)`

These tools are designed for agents working inside another development project.
They create and update project-specific notes under:

```text
Projects/<project_name>/
  Overview.md
  Dev Log.md
  Decisions.md
  Ideas.md
  Changes.md
```

Use them when an agent should record implementation progress, architectural
decisions, open ideas, or context from a separate codebase into Obsidian.

Agents do not need per-project copied instructions to discover the intended
workflow. This MCP server exposes its own usage guide:

Resource:

- `vault://project-memory-guide`

Prompt:

- `project_memory_prompt(project_name)`

An agent should read the guide/prompt and map natural language requests such as
"record this decision", "log today's changes", or "save this idea" to the
project memory tools.

### Indexing And Search

- `rebuild_note_index()`
- `sync_note_index()`
- `get_indexed_notes()`
- `search_indexed_notes(query, limit=10)`

`rebuild_note_index()` scans all Markdown notes. `sync_note_index()` updates only
added, changed, and removed notes by comparing content hashes.

The index captures:

- path
- title
- modified time
- size
- SHA-256 content hash
- Obsidian tags
- wiki links
- FTS5 searchable title/content

### Obsidian Graph

- `get_note_graph(include_unresolved=True)`
- `find_missing_links()`
- `find_orphan_notes()`

The graph is built from indexed `[[Wiki Links]]`.

Missing links are unresolved targets grouped by source notes. Orphan notes are
notes with no incoming or outgoing resolved note links.

### Knowledge Graph

- `upsert_entity(name, entity_type="Concept", observations=None)`
- `add_relation(source, relation, target)`
- `get_knowledge_graph()`
- `export_knowledge_graph()`
- `import_knowledge_graph(data, merge=True)`
- `propose_entities_from_note(title)`
- `accept_entity_proposals(title, min_confidence=0.6, link_note=False, relation="references")`
- `propose_relations_from_note(title)`
- `extract_with_provider(title, provider="rule_based")`
- `link_note_to_entity(title, entity_name, relation="references")`
- `get_entity_notes(entity_name)`

The knowledge graph is curated separately from the note-link graph. Entity
proposals are non-writing suggestions; use `upsert_entity()` to store approved
entities, or `accept_entity_proposals()` to store suggestions above a confidence
threshold. When `link_note=True`, accepted entities are also connected back to
the source note.

### Safe Editing

- `preview_note_update(title, new_content)`
- `replace_note(title, new_content, reason="")`
- `preview_replace_section(title, heading, new_body)`
- `replace_section(title, heading, new_body, reason="")`

Preview tools return unified diffs without writing. Replace tools write audit
log entries and sync the note index after saving.

### Backup And Restore

- `backup_note(title, reason="")`
- `restore_note_version(backup_id, reason="")`
- `list_audit_log(limit=50)`
- `list_note_backups(title=None)`
- `get_backup_metadata(backup_id)`

Backups are stored under `.obsidian_agent/backups`. Restore writes an audit log
entry and syncs the index afterward.

### Status

- `get_system_status()`

Returns a compact operational summary with note count, missing link count,
orphan note count, entity/relation counts, backup count, and recent audit log
entries.

### MCP Resources And Prompts

Resources:

- `vault://status`
- `vault://graph-summary`
- `vault://project-memory-guide`

Prompt:

- `safe_edit_prompt(title, requested_change)`
- `project_memory_prompt(project_name)`

These expose status, graph summaries, and a safe-edit workflow to MCP clients
that support resources and prompts.

## Recommended Workflow

1. Set `OBSIDIAN_VAULT_PATH`.
2. Run `rebuild_note_index()` once.
3. Use `sync_note_index()` after edits or external Obsidian changes.
4. Use `search_indexed_notes()` and `get_note_graph()` for navigation.
5. Use `preview_*` tools before edits.
6. Use `backup_note()` before risky changes.
7. Use `propose_entities_from_note()` before adding curated graph entities.

## Safety Notes

- The server rejects paths outside the configured vault.
- `.obsidian_agent` internals are excluded from indexing.
- Destructive note updates should go through preview and backup first.
- Audit logs are append-only JSONL records, not a full version history by
  themselves. Use backups for restoration.
