import hashlib
import json
import sqlite3
from pathlib import Path

from obsidian_agent.notes import extract_links, extract_tags


def connect(index_path: Path) -> sqlite3.Connection:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(index_path)
    connection.row_factory = sqlite3.Row
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            path TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            mtime REAL NOT NULL,
            size_bytes INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]',
            links TEXT NOT NULL DEFAULT '[]',
            indexed_at TEXT NOT NULL
        )
        """
    )
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(notes)").fetchall()}
    if "tags" not in columns:
        connection.execute("ALTER TABLE notes ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")
    if "links" not in columns:
        connection.execute("ALTER TABLE notes ADD COLUMN links TEXT NOT NULL DEFAULT '[]'")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS entities (
            name TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS entity_observations (
            entity_name TEXT NOT NULL,
            observation TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (entity_name, observation),
            FOREIGN KEY (entity_name) REFERENCES entities(name) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS relations (
            source TEXT NOT NULL,
            relation TEXT NOT NULL,
            target TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (source, relation, target),
            FOREIGN KEY (source) REFERENCES entities(name) ON DELETE CASCADE,
            FOREIGN KEY (target) REFERENCES entities(name) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS note_entities (
            note_path TEXT NOT NULL,
            note_title TEXT NOT NULL,
            entity_name TEXT NOT NULL,
            relation TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (note_path, entity_name, relation),
            FOREIGN KEY (entity_name) REFERENCES entities(name) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
        USING fts5(path UNINDEXED, title, content)
        """
    )


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as note_file:
        for chunk in iter(lambda: note_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def note_index_row(path: Path, vault_path: Path, indexed_at: str) -> dict[str, object]:
    stat = path.stat()
    relative_path = path.relative_to(vault_path).as_posix()
    content = path.read_text(encoding="utf-8")
    return {
        "path": relative_path,
        "title": Path(relative_path).with_suffix("").as_posix(),
        "mtime": stat.st_mtime,
        "size_bytes": stat.st_size,
        "content_hash": hash_file(path),
        "tags": json.dumps(extract_tags(content), ensure_ascii=False),
        "links": json.dumps(extract_links(content), ensure_ascii=False),
        "content": content,
        "indexed_at": indexed_at,
    }


def markdown_note_paths(vault_path: Path, ignored_folders: set[str]) -> list[Path]:
    return sorted(
        path
        for path in vault_path.rglob("*.md")
        if path.is_file() and not any(part in ignored_folders for part in path.relative_to(vault_path).parts)
    )


def replace_index_row(connection: sqlite3.Connection, row: dict[str, object]) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO notes (path, title, mtime, size_bytes, content_hash, tags, links, indexed_at)
        VALUES (:path, :title, :mtime, :size_bytes, :content_hash, :tags, :links, :indexed_at)
        """,
        row,
    )
    connection.execute("DELETE FROM notes_fts WHERE path = ?", (row["path"],))
    connection.execute(
        """
        INSERT INTO notes_fts (path, title, content)
        VALUES (:path, :title, :content)
        """,
        row,
    )
