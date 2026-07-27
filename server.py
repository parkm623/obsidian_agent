import os
import json
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from obsidian_agent.cli import cli_entry as run_cli_entry
from obsidian_agent.cli import cli_main as run_cli_main
from obsidian_agent.config import load_settings
from obsidian_agent.extraction import (
    extract_with_provider_from_content,
    propose_entities,
    propose_relations,
)
from obsidian_agent.index import (
    connect as connect_index,
    ensure_schema,
)
from obsidian_agent.knowledge import (
    add_relation_record,
    get_entity_note_records,
    get_knowledge_graph_records,
    import_knowledge_graph_records,
    link_note_to_entity_record,
    upsert_entity_record,
)
from obsidian_agent.notes import (
    frontmatter,
    note_name,
    note_path,
    unique_path,
)
from obsidian_agent.safety import (
    create_backup,
    get_backup_metadata as read_backup_metadata,
    list_audit_entries,
    list_backups,
    preview_note_update as preview_note_update_for_path,
    preview_section_update,
    restore_backup,
    write_note_replacement,
    write_section_replacement,
)
from obsidian_agent.services import (
    build_note_graph,
    find_missing_links_in_graph,
    find_orphan_notes_in_graph,
    get_indexed_note_rows,
    list_notes_in_vault,
    read_note_from_vault,
    rebuild_index,
    search_indexed_note_rows,
    search_notes_in_vault,
    sync_index,
    system_status,
)
from obsidian_agent.workflows import (
    add_review_item as add_review_item_to_queue,
    capture_inbox as capture_inbox_item,
    capture_project_idea as capture_project_idea_item,
    complete_review_item as complete_review_queue_item,
    create_daily_note as create_daily_note_file,
    create_project_workspace as create_project_workspace_files,
    list_review_queue as list_review_queue_items,
    log_project_update as log_project_update_entry,
    record_project_decision as record_project_decision_entry,
)


SETTINGS = load_settings(Path(__file__).resolve().parent)
CONFIG = SETTINGS.config
VAULT_PATH = SETTINGS.vault_path
VAULT_PATH.mkdir(parents=True, exist_ok=True)
INDEX_PATH = SETTINGS.index_path
AUDIT_LOG_PATH = SETTINGS.audit_log_path
BACKUP_PATH = SETTINGS.backup_path
IGNORED_FOLDERS = SETTINGS.ignored_folders

mcp = FastMCP("Obsidian Note Manager")


def _note_path(title: str) -> Path:
    return note_path(title, VAULT_PATH)


def _note_name(path: Path) -> str:
    return note_name(path, VAULT_PATH)


def _index_connection() -> sqlite3.Connection:
    return connect_index(INDEX_PATH)


def _ensure_index_schema(connection: sqlite3.Connection) -> None:
    ensure_schema(connection)


@mcp.tool()
def create_note(title: str, content: str, tags: object = None) -> str:
    """Create a markdown note in the Obsidian vault."""
    try:
        file_path = unique_path(_note_path(title))
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(frontmatter(tags) + content, encoding="utf-8")
        return f"OK: created '{_note_name(file_path)}'."
    except (OSError, ValueError) as exc:
        return f"ERROR: failed to create note: {exc}"


@mcp.tool()
def append_to_note(title: str, content: str) -> str:
    """Append content to a markdown note, creating the note if it does not exist."""
    try:
        file_path = _note_path(title)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        needs_newline = file_path.exists() and file_path.stat().st_size > 0
        with file_path.open("a", encoding="utf-8") as note_file:
            if needs_newline:
                note_file.write("\n")
            note_file.write(f"{content}\n")

        return f"OK: appended to '{_note_name(file_path)}'."
    except (OSError, ValueError) as exc:
        return f"ERROR: failed to append note: {exc}"


@mcp.tool()
def create_daily_note(day: str | None = None) -> str:
    """Create a dated daily note under Daily/YYYY-MM-DD."""
    try:
        result = create_daily_note_file(VAULT_PATH, day)
        if result.startswith("OK: created"):
            sync_result = sync_note_index()
            if sync_result.startswith("ERROR:"):
                return sync_result
        return result
    except ValueError as exc:
        return f"ERROR: invalid daily note date: {exc}"
    except OSError as exc:
        return f"ERROR: failed to create daily note: {exc}"


@mcp.tool()
def capture_inbox(content: str, source: str = "") -> str:
    """Capture a timestamped item into Inbox.md."""
    try:
        result = capture_inbox_item(VAULT_PATH, content, source)
        if result.startswith("OK:"):
            sync_result = sync_note_index()
            if sync_result.startswith("ERROR:"):
                return sync_result
        return result
    except (OSError, ValueError) as exc:
        return f"ERROR: failed to capture inbox item: {exc}"


@mcp.tool()
def add_review_item(content: str, source: str = "") -> str:
    """Add an unchecked item to Review Queue.md."""
    try:
        result = add_review_item_to_queue(VAULT_PATH, content, source)
        if result.startswith("OK:"):
            sync_result = sync_note_index()
            if sync_result.startswith("ERROR:"):
                return sync_result
        return result
    except (OSError, ValueError) as exc:
        return f"ERROR: failed to add review item: {exc}"


@mcp.tool()
def list_review_queue() -> list[dict[str, object]]:
    """List unchecked review queue items."""
    try:
        return list_review_queue_items(VAULT_PATH)
    except (OSError, ValueError):
        return []


@mcp.tool()
def complete_review_item(line: int) -> str:
    """Mark one Review Queue.md item complete by line number."""
    try:
        result = complete_review_queue_item(VAULT_PATH, line)
        if result.startswith("OK:"):
            sync_result = sync_note_index()
            if sync_result.startswith("ERROR:"):
                return sync_result
        return result
    except (OSError, ValueError) as exc:
        return f"ERROR: failed to complete review item: {exc}"


def _sync_after_project_result(result: str) -> str:
    if result.startswith("OK:"):
        sync_result = sync_note_index()
        if sync_result.startswith("ERROR:"):
            return sync_result
    return result


@mcp.tool()
def create_project_workspace(project_name: str) -> str:
    """Use when starting work on a development project; creates Projects/<name> memory notes."""
    try:
        return _sync_after_project_result(create_project_workspace_files(VAULT_PATH, project_name))
    except (OSError, ValueError) as exc:
        return f"ERROR: failed to create project workspace: {exc}"


@mcp.tool()
def log_project_update(project_name: str, content: str) -> str:
    """Use during coding to record implementation progress, debugging results, and notable changes."""
    try:
        return _sync_after_project_result(log_project_update_entry(VAULT_PATH, project_name, content))
    except (OSError, ValueError) as exc:
        return f"ERROR: failed to log project update: {exc}"


@mcp.tool()
def record_project_decision(project_name: str, decision: str, rationale: str = "") -> str:
    """Use when the project makes an architecture, product, scope, or complexity decision worth remembering."""
    try:
        return _sync_after_project_result(
            record_project_decision_entry(VAULT_PATH, project_name, decision, rationale)
        )
    except (OSError, ValueError) as exc:
        return f"ERROR: failed to record project decision: {exc}"


@mcp.tool()
def capture_project_idea(project_name: str, idea: str) -> str:
    """Use for future project ideas, follow-ups, and improvement thoughts that should not interrupt current work."""
    try:
        return _sync_after_project_result(capture_project_idea_item(VAULT_PATH, project_name, idea))
    except (OSError, ValueError) as exc:
        return f"ERROR: failed to capture project idea: {exc}"


@mcp.tool()
def preview_note_update(title: str, new_content: str) -> dict[str, object]:
    """Return a unified diff for replacing a note without writing changes."""
    try:
        file_path = _note_path(title)
        return preview_note_update_for_path(file_path, VAULT_PATH, new_content)
    except (OSError, ValueError) as exc:
        return {"title": title, "path": "", "exists": False, "diff": "", "error": str(exc)}


@mcp.tool()
def replace_note(title: str, new_content: str, reason: str = "") -> str:
    """Replace a note body, write an audit entry, and sync the search index."""
    try:
        file_path = _note_path(title)
        result = write_note_replacement(file_path, VAULT_PATH, AUDIT_LOG_PATH, new_content, reason)
        sync_result = sync_note_index()
        if sync_result.startswith("ERROR:"):
            return sync_result
        return result
    except (OSError, ValueError) as exc:
        return f"ERROR: failed to replace note: {exc}"


@mcp.tool()
def preview_replace_section(title: str, heading: str, new_body: str) -> dict[str, object]:
    """Preview replacing a Markdown heading section without writing changes."""
    try:
        file_path = _note_path(title)
        preview = preview_section_update(file_path, VAULT_PATH, heading, new_body)
        if preview.get("error") == "note not found":
            return {"title": title, "path": "", "exists": False, "diff": "", "error": "note not found"}
        return preview
    except (OSError, ValueError) as exc:
        return {"title": title, "path": "", "exists": False, "diff": "", "error": str(exc)}


@mcp.tool()
def replace_section(title: str, heading: str, new_body: str, reason: str = "") -> str:
    """Replace one Markdown heading section, audit it, and sync the index."""
    try:
        file_path = _note_path(title)
        if not file_path.exists():
            return f"ERROR: note '{title}' was not found."

        result = write_section_replacement(file_path, VAULT_PATH, AUDIT_LOG_PATH, heading, new_body, reason)
        if result.startswith("ERROR:"):
            return result
        sync_result = sync_note_index()
        if sync_result.startswith("ERROR:"):
            return sync_result
        return result
    except (OSError, ValueError) as exc:
        return f"ERROR: failed to replace section: {exc}"


@mcp.tool()
def backup_note(title: str, reason: str = "") -> dict[str, object]:
    """Create a restorable backup snapshot for a note."""
    try:
        file_path = _note_path(title)
        if not file_path.exists():
            return {"error": f"note '{title}' was not found"}

        return create_backup(file_path, VAULT_PATH, BACKUP_PATH, AUDIT_LOG_PATH, reason)
    except (OSError, ValueError) as exc:
        return {"error": str(exc)}


@mcp.tool()
def restore_note_version(backup_id: str, reason: str = "") -> str:
    """Restore a note from a backup snapshot."""
    result = restore_backup(BACKUP_PATH, VAULT_PATH, AUDIT_LOG_PATH, backup_id, reason)
    if result.startswith("OK:"):
        sync_result = sync_note_index()
        if sync_result.startswith("ERROR:"):
            return sync_result
    return result


@mcp.tool()
def list_audit_log(limit: int = 50) -> list[dict[str, object]]:
    """Return recent audit log entries, newest first."""
    return list_audit_entries(AUDIT_LOG_PATH, limit)


@mcp.tool()
def get_backup_metadata(backup_id: str) -> dict[str, object]:
    """Return metadata for one backup snapshot."""
    return read_backup_metadata(BACKUP_PATH, backup_id)


@mcp.tool()
def list_note_backups(title: str | None = None) -> list[dict[str, object]]:
    """List backup metadata, optionally filtering by note title."""
    return list_backups(BACKUP_PATH, title)


@mcp.tool()
def get_system_status() -> dict[str, object]:
    """Return a compact operational summary for the vault and indexes."""
    notes = get_indexed_notes()
    missing_links = find_missing_links()
    orphan_notes = find_orphan_notes()
    knowledge_graph = get_knowledge_graph()
    backups = list_note_backups()
    return system_status(
        VAULT_PATH,
        INDEX_PATH,
        notes,
        missing_links,
        orphan_notes,
        knowledge_graph,
        backups,
        list_audit_log(limit=5),
    )


@mcp.tool()
def list_notes() -> list[str]:
    """List markdown notes in the configured vault."""
    return list_notes_in_vault(VAULT_PATH)


@mcp.tool()
def read_note(title: str) -> str:
    """Read a markdown note by title or nested path."""
    return read_note_from_vault(title, VAULT_PATH)


@mcp.tool()
def search_notes(query: str) -> list[str]:
    """Search note names and markdown content for a case-insensitive query."""
    return search_notes_in_vault(query, VAULT_PATH)


@mcp.tool()
def rebuild_note_index() -> str:
    """Rebuild the SQLite metadata index from markdown files in the vault."""
    return rebuild_index(_index_connection, _ensure_index_schema, VAULT_PATH, IGNORED_FOLDERS)


@mcp.tool()
def sync_note_index() -> str:
    """Synchronize the SQLite index with changed markdown files."""
    return sync_index(_index_connection, _ensure_index_schema, VAULT_PATH, IGNORED_FOLDERS)


@mcp.tool()
def get_indexed_notes() -> list[dict[str, object]]:
    """Return rows from the SQLite note metadata index."""
    return get_indexed_note_rows(_index_connection, _ensure_index_schema)


@mcp.tool()
def search_indexed_notes(query: str, limit: int = 10) -> list[dict[str, str]]:
    """Search the SQLite FTS index and return matching note titles and paths."""
    return search_indexed_note_rows(_index_connection, _ensure_index_schema, query, limit)


@mcp.tool()
def get_note_graph(include_unresolved: bool = True) -> dict[str, list[dict[str, object]]]:
    """Return a note-link graph from the current SQLite index."""
    return build_note_graph(get_indexed_notes(), include_unresolved)


@mcp.tool()
def find_missing_links() -> list[dict[str, object]]:
    """Return unresolved wiki-link targets grouped by target note title."""
    return find_missing_links_in_graph(get_note_graph(include_unresolved=True))


@mcp.tool()
def find_orphan_notes() -> list[str]:
    """Return notes with neither incoming nor outgoing resolved note links."""
    return find_orphan_notes_in_graph(get_note_graph(include_unresolved=False))


@mcp.tool()
def upsert_entity(name: str, entity_type: str = "Concept", observations: object = None) -> str:
    """Create or update a knowledge-graph entity and optional observations."""
    return upsert_entity_record(_index_connection, _ensure_index_schema, name, entity_type, observations)


@mcp.tool()
def add_relation(source: str, relation: str, target: str) -> str:
    """Add a directed relation between two knowledge-graph entities."""
    return add_relation_record(_index_connection, _ensure_index_schema, source, relation, target)


@mcp.tool()
def get_knowledge_graph() -> dict[str, list[dict[str, object]]]:
    """Return manually curated entities, observations, and relations."""
    return get_knowledge_graph_records(_index_connection, _ensure_index_schema)


@mcp.tool()
def export_knowledge_graph() -> dict[str, list[dict[str, object]]]:
    """Export the curated knowledge graph as portable JSON-compatible data."""
    return get_knowledge_graph()


@mcp.tool()
def import_knowledge_graph(data: dict[str, object], merge: bool = True) -> str:
    """Import curated knowledge graph data."""
    return import_knowledge_graph_records(_index_connection, _ensure_index_schema, data, merge)


@mcp.tool()
def propose_entities_from_note(title: str) -> list[dict[str, object]]:
    """Propose entity candidates from a note without writing to the knowledge graph."""
    try:
        file_path = _note_path(title)
        if not file_path.exists():
            return []
        content = file_path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return []

    return propose_entities(_note_name(file_path), content)


@mcp.tool()
def accept_entity_proposals(
    title: str,
    min_confidence: float = 0.6,
    link_note: bool = False,
    relation: str = "references",
) -> str:
    """Store proposed entities above a confidence threshold, optionally linking the note."""
    proposals = propose_entities_from_note(title)
    accepted = [
        proposal
        for proposal in proposals
        if float(proposal["confidence"]) >= float(min_confidence)
    ]

    for proposal in accepted:
        upsert_result = upsert_entity(
            name=str(proposal["name"]),
            entity_type=str(proposal["entity_type"]),
            observations=None,
        )
        if upsert_result.startswith("ERROR:"):
            return upsert_result
        if link_note:
            link_result = link_note_to_entity(title, str(proposal["name"]), relation=relation)
            if link_result.startswith("ERROR:"):
                return link_result

    return f"OK: accepted {len(accepted)} entity proposals from '{title}'."


@mcp.tool()
def propose_relations_from_note(title: str) -> list[dict[str, object]]:
    """Propose relation candidates from a note without writing to the knowledge graph."""
    try:
        file_path = _note_path(title)
        if not file_path.exists():
            return []
        content = file_path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return []

    return propose_relations(_note_name(file_path), content)


@mcp.tool()
def extract_with_provider(title: str, provider: str = "rule_based") -> dict[str, object]:
    """Extract entity and relation proposals through a named provider interface."""
    try:
        file_path = _note_path(title)
        if not file_path.exists():
            return {"provider": provider, "entities": [], "relations": [], "error": "note not found"}
        content = file_path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        return {"provider": provider, "entities": [], "relations": [], "error": str(exc)}

    return extract_with_provider_from_content(_note_name(file_path), content, provider)


@mcp.resource("vault://status")
def vault_status_resource() -> str:
    """MCP resource: current vault/index status as JSON."""
    return json.dumps(get_system_status(), ensure_ascii=False, indent=2)


@mcp.resource("vault://graph-summary")
def graph_summary_resource() -> str:
    """MCP resource: compact note graph summary as JSON."""
    graph = get_note_graph(include_unresolved=True)
    missing_links = find_missing_links()
    orphan_notes = find_orphan_notes()
    summary = {
        "node_count": len(graph["nodes"]),
        "edge_count": len(graph["edges"]),
        "missing_link_count": len(missing_links),
        "orphan_note_count": len(orphan_notes),
        "missing_links": missing_links,
        "orphan_notes": orphan_notes,
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


@mcp.resource("vault://project-memory-guide")
def project_memory_guide_resource() -> str:
    """MCP resource: agent guide for using Obsidian as project memory."""
    return (
        "# Obsidian Project Memory Guide\n\n"
        "Use this MCP server to record development context from whatever codebase the agent is working in.\n\n"
        "Core flow:\n"
        "1. At the start of a project, call create_project_workspace(project_name).\n"
        "2. During implementation, call log_project_update(project_name, content) for progress, bugs, fixes, and notable changes.\n"
        "3. When a decision is made, call record_project_decision(project_name, decision, rationale).\n"
        "4. For future ideas or follow-ups, call capture_project_idea(project_name, idea).\n"
        "5. For quick unsorted notes, call capture_inbox(content, source).\n\n"
        "Keep entries concise and factual. Prefer appending small timestamped notes over rewriting project history.\n"
        "Do not require the user to name tool functions; map natural language requests like 'record this', "
        "'log what changed', or 'remember this decision' to the project memory tools.\n"
    )


@mcp.prompt()
def safe_edit_prompt(title: str, requested_change: str) -> str:
    """MCP prompt: guide an agent through safe note editing."""
    return (
        f"Safely edit the Obsidian note '{title}'.\n"
        f"Requested change: {requested_change}\n\n"
        "Workflow:\n"
        "1. Read the note first.\n"
        "2. Create a backup with backup_note() before risky changes.\n"
        "3. Use preview_note_update() or preview_replace_section() to inspect the diff.\n"
        "4. Apply the smallest safe change with replace_note() or replace_section().\n"
        "5. Confirm the index is synced and inspect recent audit log entries if needed.\n"
    )


@mcp.prompt()
def project_memory_prompt(project_name: str) -> str:
    """MCP prompt: guide an agent to record project context in Obsidian."""
    return (
        f"Use Obsidian project memory for the development project '{project_name}'.\n\n"
        "When starting or resuming this project:\n"
        f"- Ensure the workspace exists with create_project_workspace(project_name='{project_name}').\n\n"
        "When the user asks to record project context:\n"
        f"- Use log_project_update(project_name='{project_name}', content=...) for implementation progress, fixes, and changes.\n"
        f"- Use record_project_decision(project_name='{project_name}', decision=..., rationale=...) for decisions and tradeoffs.\n"
        f"- Use capture_project_idea(project_name='{project_name}', idea=...) for future ideas or follow-ups.\n"
        "- Use capture_inbox(content=..., source=...) only for unsorted quick capture.\n\n"
        "Keep entries short, timestamped by the tool, and useful to a future agent reopening the codebase.\n"
    )


@mcp.tool()
def link_note_to_entity(title: str, entity_name: str, relation: str = "references") -> str:
    """Link an existing note to a knowledge-graph entity."""
    clean_entity = entity_name.strip()
    clean_relation = relation.strip() if relation and relation.strip() else "references"
    if not clean_entity:
        return "ERROR: entity name is required."

    try:
        file_path = _note_path(title)
        if not file_path.exists():
            return f"ERROR: note '{title}' was not found."

        note_title = _note_name(file_path)
        note_path = file_path.relative_to(VAULT_PATH).as_posix()
        return link_note_to_entity_record(
            _index_connection,
            _ensure_index_schema,
            note_title,
            note_path,
            clean_entity,
            clean_relation,
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        return f"ERROR: failed to link note to entity: {exc}"


@mcp.tool()
def get_entity_notes(entity_name: str) -> list[dict[str, str]]:
    """Return note links for one knowledge-graph entity."""
    return get_entity_note_records(_index_connection, _ensure_index_schema, entity_name)


def _cli_operations() -> dict[str, object]:
    return {
        "rebuild": rebuild_note_index,
        "sync": sync_note_index,
        "search": search_indexed_notes,
        "graph": get_note_graph,
        "knowledge_graph": get_knowledge_graph,
        "export_knowledge_graph": export_knowledge_graph,
        "missing_links": find_missing_links,
        "orphans": find_orphan_notes,
        "status": get_system_status,
    }


def cli_main(argv: list[str] | None = None) -> int:
    return run_cli_main(_cli_operations(), argv)


def cli_entry() -> int:
    """Console-script entry point."""
    return run_cli_entry(_cli_operations())


if __name__ == "__main__":
    if len(os.sys.argv) > 1:
        raise SystemExit(cli_entry())
    print(f"Obsidian MCP server starting... (vault: {VAULT_PATH})")
    mcp.run(transport="stdio")
