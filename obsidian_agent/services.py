import json
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from obsidian_agent.index import markdown_note_paths, note_index_row, replace_index_row
from obsidian_agent.notes import note_name, note_path


ConnectionFactory = Callable[[], sqlite3.Connection]
SchemaInitializer = Callable[[sqlite3.Connection], None]


def list_notes_in_vault(vault_path: Path) -> list[str]:
    return sorted(note_name(path, vault_path) for path in vault_path.rglob("*.md") if path.is_file())


def read_note_from_vault(title: str, vault_path: Path) -> str:
    try:
        file_path = note_path(title, vault_path)
        if not file_path.exists():
            return f"ERROR: note '{title}' was not found."
        return file_path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        return f"ERROR: failed to read note: {exc}"


def search_notes_in_vault(query: str, vault_path: Path) -> list[str]:
    normalized_query = query.strip().lower()
    if not normalized_query:
        return []

    results = []
    for path in vault_path.rglob("*.md"):
        if not path.is_file():
            continue
        try:
            title = note_name(path, vault_path)
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if normalized_query in title.lower() or normalized_query in content.lower():
            results.append(title)

    return sorted(results)


def rebuild_index(
    connect: ConnectionFactory,
    ensure_schema: SchemaInitializer,
    vault_path: Path,
    ignored_folders: set[str],
) -> str:
    indexed_at = datetime.now().isoformat(timespec="seconds")
    rows = []

    try:
        for path in markdown_note_paths(vault_path, ignored_folders):
            rows.append(note_index_row(path, vault_path, indexed_at))

        connection = connect()
        try:
            ensure_schema(connection)
            connection.execute("DELETE FROM notes")
            connection.execute("DELETE FROM notes_fts")
            connection.executemany(
                """
                INSERT INTO notes (path, title, mtime, size_bytes, content_hash, tags, links, indexed_at)
                VALUES (:path, :title, :mtime, :size_bytes, :content_hash, :tags, :links, :indexed_at)
                """,
                rows,
            )
            connection.executemany(
                """
                INSERT INTO notes_fts (path, title, content)
                VALUES (:path, :title, :content)
                """,
                rows,
            )
            connection.commit()
        finally:
            connection.close()

        return f"OK: indexed {len(rows)} notes."
    except (OSError, sqlite3.Error) as exc:
        return f"ERROR: failed to rebuild note index: {exc}"


def sync_index(
    connect: ConnectionFactory,
    ensure_schema: SchemaInitializer,
    vault_path: Path,
    ignored_folders: set[str],
) -> str:
    indexed_at = datetime.now().isoformat(timespec="seconds")
    counts = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0}

    try:
        connection = connect()
        try:
            ensure_schema(connection)
            existing_rows = connection.execute("SELECT path, content_hash FROM notes").fetchall()
            existing_hashes = {row["path"]: row["content_hash"] for row in existing_rows}
            current_paths = {
                note_name(path, vault_path) + ".md": path
                for path in markdown_note_paths(vault_path, ignored_folders)
            }

            for removed_path in sorted(set(existing_hashes) - set(current_paths)):
                connection.execute("DELETE FROM notes WHERE path = ?", (removed_path,))
                connection.execute("DELETE FROM notes_fts WHERE path = ?", (removed_path,))
                counts["removed"] += 1

            for relative_path, path in sorted(current_paths.items()):
                row = note_index_row(path, vault_path, indexed_at)
                old_hash = existing_hashes.get(relative_path)
                if old_hash is None:
                    replace_index_row(connection, row)
                    counts["added"] += 1
                elif old_hash != row["content_hash"]:
                    replace_index_row(connection, row)
                    counts["updated"] += 1
                else:
                    counts["unchanged"] += 1

            connection.commit()
        finally:
            connection.close()

        return (
            "OK: synced index "
            f"(added={counts['added']}, updated={counts['updated']}, "
            f"removed={counts['removed']}, unchanged={counts['unchanged']})."
        )
    except (OSError, sqlite3.Error) as exc:
        return f"ERROR: failed to sync note index: {exc}"


def get_indexed_note_rows(
    connect: ConnectionFactory,
    ensure_schema: SchemaInitializer,
) -> list[dict[str, object]]:
    try:
        connection = connect()
        try:
            ensure_schema(connection)
            rows = connection.execute(
                """
                SELECT path, title, mtime, size_bytes, content_hash, tags, links, indexed_at
                FROM notes
                ORDER BY path
                """
            ).fetchall()
        finally:
            connection.close()
        notes = []
        for row in rows:
            note = dict(row)
            note["tags"] = json.loads(note["tags"])
            note["links"] = json.loads(note["links"])
            notes.append(note)
        return notes
    except sqlite3.Error:
        return []


def search_indexed_note_rows(
    connect: ConnectionFactory,
    ensure_schema: SchemaInitializer,
    query: str,
    limit: int = 10,
) -> list[dict[str, str]]:
    normalized_query = query.strip()
    if not normalized_query:
        return []

    safe_limit = max(1, min(int(limit), 50))
    try:
        connection = connect()
        try:
            ensure_schema(connection)
            rows = connection.execute(
                """
                SELECT title, path
                FROM notes_fts
                WHERE notes_fts MATCH ?
                ORDER BY rank, title
                LIMIT ?
                """,
                (normalized_query, safe_limit),
            ).fetchall()
        finally:
            connection.close()
        return [dict(row) for row in rows]
    except (ValueError, sqlite3.Error):
        return []


def build_note_graph(notes: list[dict[str, object]], include_unresolved: bool = True) -> dict[str, list[dict[str, object]]]:
    note_ids = {note["title"] for note in notes}
    nodes = [
        {
            "id": note["title"],
            "path": note["path"],
            "tags": note["tags"],
        }
        for note in notes
    ]
    edges = []

    for note in notes:
        for link in note["links"]:
            edge = {
                "source": note["title"],
                "target": link,
                "resolved": link in note_ids,
            }
            if include_unresolved or edge["resolved"]:
                edges.append(edge)

    return {
        "nodes": sorted(nodes, key=lambda node: node["id"]),
        "edges": sorted(edges, key=lambda edge: (edge["source"], edge["target"])),
    }


def find_missing_links_in_graph(graph: dict[str, list[dict[str, object]]]) -> list[dict[str, object]]:
    sources_by_target: dict[str, set[str]] = {}

    for edge in graph["edges"]:
        if not edge["resolved"]:
            sources_by_target.setdefault(edge["target"], set()).add(edge["source"])

    return [
        {"target": target, "sources": sorted(sources)}
        for target, sources in sorted(sources_by_target.items())
    ]


def find_orphan_notes_in_graph(graph: dict[str, list[dict[str, object]]]) -> list[str]:
    note_ids = {node["id"] for node in graph["nodes"]}
    connected_ids = set()

    for edge in graph["edges"]:
        connected_ids.add(edge["source"])
        connected_ids.add(edge["target"])

    return sorted(note_ids - connected_ids)


def system_status(
    vault_path: Path,
    index_path: Path,
    notes: list[dict[str, object]],
    missing_links: list[dict[str, object]],
    orphan_notes: list[str],
    knowledge_graph: dict[str, list[dict[str, object]]],
    backups: list[dict[str, object]],
    recent_audit: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "vault_path": str(vault_path),
        "index_path": str(index_path),
        "note_count": len(notes),
        "missing_link_count": len(missing_links),
        "orphan_note_count": len(orphan_notes),
        "entity_count": len(knowledge_graph["entities"]),
        "relation_count": len(knowledge_graph["relations"]),
        "backup_count": len(backups),
        "recent_audit": recent_audit,
    }
