import difflib
import json
import re
from datetime import datetime
from pathlib import Path

from obsidian_agent.notes import is_safe_path, note_name, safe_backup_name


def audit(audit_log_path: Path, vault_path: Path, action: str, note_path: Path, reason: str = "") -> None:
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "path": note_path.relative_to(vault_path).as_posix(),
        "reason": reason,
    }
    with audit_log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def backup_id_for(note_path: Path, vault_path: Path) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    relative = note_path.relative_to(vault_path).as_posix()
    safe_relative = safe_backup_name(relative)
    return f"{timestamp}__{safe_relative}"


def find_heading_section(content: str, heading: str) -> tuple[int, int, str] | None:
    lines = content.splitlines(keepends=True)
    target = heading.strip().lstrip("#").strip()
    start = None
    level = None

    for index, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line.rstrip("\n"))
        if not match:
            continue
        if match.group(2).strip() == target:
            start = index
            level = len(match.group(1))
            break

    if start is None or level is None:
        return None

    end = len(lines)
    for index in range(start + 1, len(lines)):
        match = re.match(r"^(#{1,6})\s+.+?\s*$", lines[index].rstrip("\n"))
        if match and len(match.group(1)) <= level:
            end = index
            break

    return start, end, "".join(lines[start:end])


def replace_heading_section(content: str, heading: str, new_body: str) -> tuple[str, str] | None:
    section = find_heading_section(content, heading)
    if section is None:
        return None

    start, end, old_section = section
    lines = content.splitlines(keepends=True)
    heading_line = lines[start].rstrip("\n")
    body = new_body.rstrip("\n")
    replacement = f"{heading_line}\n{body}\n"
    if end < len(lines):
        replacement += "\n"

    new_content = "".join(lines[:start]) + replacement + "".join(lines[end:])
    return new_content, old_section


def preview_note_update(note_path: Path, vault_path: Path, new_content: str) -> dict[str, object]:
    old_content = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
    title = note_name(note_path, vault_path)
    diff = "".join(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"{title} (current)",
            tofile=f"{title} (new)",
        )
    )
    return {
        "title": title,
        "path": note_path.relative_to(vault_path).as_posix(),
        "exists": note_path.exists(),
        "diff": diff,
    }


def preview_section_update(note_path: Path, vault_path: Path, heading: str, new_body: str) -> dict[str, object]:
    if not note_path.exists():
        return {"title": note_path.stem, "path": "", "exists": False, "diff": "", "error": "note not found"}

    old_content = note_path.read_text(encoding="utf-8")
    replaced = replace_heading_section(old_content, heading, new_body)
    title = note_name(note_path, vault_path)
    if replaced is None:
        return {
            "title": title,
            "path": note_path.relative_to(vault_path).as_posix(),
            "exists": True,
            "diff": "",
            "error": f"section '{heading}' was not found",
        }
    new_content, _old_section = replaced
    diff = "".join(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"{title} (current)",
            tofile=f"{title} (new)",
        )
    )
    return {
        "title": title,
        "path": note_path.relative_to(vault_path).as_posix(),
        "exists": True,
        "diff": diff,
    }


def write_note_replacement(
    note_path: Path,
    vault_path: Path,
    audit_log_path: Path,
    new_content: str,
    reason: str = "",
) -> str:
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(new_content, encoding="utf-8")
    audit(audit_log_path, vault_path, "replace_note", note_path, reason)
    return f"OK: replaced '{note_name(note_path, vault_path)}'."


def write_section_replacement(
    note_path: Path,
    vault_path: Path,
    audit_log_path: Path,
    heading: str,
    new_body: str,
    reason: str = "",
) -> str:
    if not note_path.exists():
        return "ERROR: note was not found."

    old_content = note_path.read_text(encoding="utf-8")
    replaced = replace_heading_section(old_content, heading, new_body)
    if replaced is None:
        return f"ERROR: section '{heading}' was not found."

    new_content, _old_section = replaced
    note_path.write_text(new_content, encoding="utf-8")
    audit(audit_log_path, vault_path, "replace_section", note_path, reason)
    return f"OK: replaced section '{heading}' in '{note_name(note_path, vault_path)}'."


def create_backup(
    note_path: Path,
    vault_path: Path,
    backup_path: Path,
    audit_log_path: Path,
    reason: str = "",
) -> dict[str, object]:
    if not note_path.exists():
        return {"error": "note was not found"}

    backup_path.mkdir(parents=True, exist_ok=True)
    backup_id = backup_id_for(note_path, vault_path)
    backup_file = backup_path / backup_id
    metadata_file = backup_path / f"{backup_id}.json"
    content = note_path.read_text(encoding="utf-8")
    backup_file.write_text(content, encoding="utf-8")

    metadata = {
        "backup_id": backup_id,
        "title": note_name(note_path, vault_path),
        "path": note_path.relative_to(vault_path).as_posix(),
        "reason": reason,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    audit(audit_log_path, vault_path, "backup_note", note_path, reason)
    return metadata


def restore_backup(
    backup_path: Path,
    vault_path: Path,
    audit_log_path: Path,
    backup_id: str,
    reason: str = "",
) -> str:
    clean_backup_id = Path(backup_id).name
    backup_file = backup_path / clean_backup_id
    metadata_file = backup_path / f"{clean_backup_id}.json"
    if not backup_file.exists() or not metadata_file.exists():
        return f"ERROR: backup '{backup_id}' was not found."

    try:
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        target_path = vault_path / metadata["path"]
        if not is_safe_path(target_path, vault_path):
            return "ERROR: backup target is outside the configured vault."

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(backup_file.read_text(encoding="utf-8"), encoding="utf-8")
        audit(audit_log_path, vault_path, "restore_note_version", target_path, reason)
        return f"OK: restored '{metadata['title']}' from backup."
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        return f"ERROR: failed to restore backup: {exc}"


def list_audit_entries(audit_log_path: Path, limit: int = 50) -> list[dict[str, object]]:
    if not audit_log_path.exists():
        return []

    safe_limit = max(1, min(int(limit), 500))
    try:
        entries = []
        for line in audit_log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entries.append(json.loads(line))
        return list(reversed(entries))[:safe_limit]
    except (OSError, ValueError, json.JSONDecodeError):
        return []


def get_backup_metadata(backup_path: Path, backup_id: str) -> dict[str, object]:
    clean_backup_id = Path(backup_id).name
    metadata_file = backup_path / f"{clean_backup_id}.json"
    if not metadata_file.exists():
        return {}

    try:
        return json.loads(metadata_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def list_backups(backup_path: Path, title: str | None = None) -> list[dict[str, object]]:
    if not backup_path.exists():
        return []

    target_title = title.strip() if isinstance(title, str) and title.strip() else None
    backups = []
    for metadata_file in sorted(backup_path.glob("*.json")):
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if target_title is None or metadata.get("title") == target_title:
            backups.append(metadata)

    return sorted(backups, key=lambda backup: backup.get("created_at", ""), reverse=True)
