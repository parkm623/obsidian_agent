from datetime import date, datetime
from pathlib import Path
import re

from obsidian_agent.notes import frontmatter, note_name, note_path


REVIEW_ITEM = re.compile(r"^- \[ \] (?P<content>.*?)(?: \(source: (?P<source>.*?)\))?$")


def daily_note_title(day: str | None = None) -> str:
    if day is None or not day.strip():
        resolved = date.today().isoformat()
    else:
        resolved = date.fromisoformat(day.strip()).isoformat()
    return f"Daily/{resolved}"


def daily_note_body(day: str) -> str:
    return (
        f"# {day}\n\n"
        "## Inbox\n\n"
        "## Focus\n\n"
        "## Notes\n\n"
        "## Review\n"
    )


def create_daily_note(vault_path: Path, day: str | None = None) -> str:
    title = daily_note_title(day)
    resolved_day = title.split("/", 1)[1]
    file_path = note_path(title, vault_path)
    if file_path.exists():
        return f"OK: daily note '{title}' already exists."

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(frontmatter(["daily"]) + daily_note_body(resolved_day), encoding="utf-8")
    return f"OK: created daily note '{title}'."


def capture_inbox(vault_path: Path, content: str, source: str = "") -> str:
    clean_content = content.strip()
    if not clean_content:
        return "ERROR: inbox content is required."

    file_path = note_path("Inbox", vault_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if not file_path.exists():
        file_path.write_text(frontmatter(["inbox"]) + "# Inbox\n\n", encoding="utf-8")

    timestamp = datetime.now().isoformat(timespec="minutes")
    clean_source = source.strip()
    source_text = f" (source: {clean_source})" if clean_source else ""
    needs_newline = file_path.stat().st_size > 0
    with file_path.open("a", encoding="utf-8") as inbox_file:
        if needs_newline:
            inbox_file.write("\n")
        inbox_file.write(f"- [{timestamp}] {clean_content}{source_text}\n")

    return "OK: captured inbox item."


def _ensure_review_queue(review_path: Path) -> None:
    if review_path.exists():
        return
    review_path.write_text(
        frontmatter(["review"]) + "# Review Queue\n\n## Pending\n\n",
        encoding="utf-8",
    )


def add_review_item(vault_path: Path, content: str, source: str = "") -> str:
    clean_content = content.strip()
    if not clean_content:
        return "ERROR: review content is required."

    review_path = note_path("Review Queue", vault_path)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_review_queue(review_path)

    clean_source = source.strip()
    source_text = f" (source: {clean_source})" if clean_source else ""
    with review_path.open("a", encoding="utf-8") as review_file:
        review_file.write(f"- [ ] {clean_content}{source_text}\n")

    return "OK: added review item."


def list_review_queue(vault_path: Path) -> list[dict[str, object]]:
    review_path = note_path("Review Queue", vault_path)
    if not review_path.exists():
        return []

    items = []
    for line_number, line in enumerate(review_path.read_text(encoding="utf-8").splitlines(), start=1):
        match = REVIEW_ITEM.match(line.strip())
        if not match:
            continue
        items.append(
            {
                "content": match.group("content"),
                "source": match.group("source") or "",
                "line": line_number,
            }
        )

    return items


def complete_review_item(vault_path: Path, line: int) -> str:
    review_path = note_path("Review Queue", vault_path)
    if not review_path.exists():
        return "ERROR: review item line was not found."

    try:
        target_line = int(line)
    except (TypeError, ValueError):
        return "ERROR: review item line must be a number."

    lines = review_path.read_text(encoding="utf-8").splitlines()
    if target_line < 1 or target_line > len(lines):
        return "ERROR: review item line was not found."

    index = target_line - 1
    if not REVIEW_ITEM.match(lines[index].strip()):
        return "ERROR: review item line was not found."

    lines[index] = lines[index].replace("- [ ]", "- [x]", 1)
    review_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"OK: completed review item on line {target_line}."


def project_base_title(project_name: str) -> str:
    clean_name = project_name.strip()
    if not clean_name:
        raise ValueError("project name is required")
    return f"Projects/{clean_name}"


def _write_if_missing(path: Path, content: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_project_workspace(vault_path: Path, project_name: str) -> str:
    base_title = project_base_title(project_name)
    project_label = base_title.split("/", 1)[1]
    files = {
        "Overview": (
            frontmatter(["project"]) +
            f"# {project_label}\n\n"
            "## Goal\n\n"
            "## Current Status\n\n"
            "## Links\n"
        ),
        "Dev Log": frontmatter(["project", "devlog"]) + "# Dev Log\n\n",
        "Decisions": frontmatter(["project", "decision"]) + "# Decisions\n\n",
        "Ideas": frontmatter(["project", "idea"]) + "# Ideas\n\n",
        "Changes": frontmatter(["project", "change"]) + "# Changes\n\n",
    }

    for name, content in files.items():
        _write_if_missing(note_path(f"{base_title}/{name}", vault_path), content)

    return f"OK: project workspace '{base_title}' is ready."


def _append_project_entry(vault_path: Path, project_name: str, note_name_suffix: str, content: str, prefix: str = "") -> str:
    clean_content = content.strip()
    if not clean_content:
        return "ERROR: project entry content is required."

    base_title = project_base_title(project_name)
    target_path = note_path(f"{base_title}/{note_name_suffix}", vault_path)
    if not target_path.exists():
        create_project_workspace(vault_path, project_name)

    timestamp = datetime.now().isoformat(timespec="minutes")
    label = f"{prefix} " if prefix else ""
    with target_path.open("a", encoding="utf-8") as project_file:
        project_file.write(f"- [{timestamp}] {label}{clean_content}\n")

    return "OK"


def log_project_update(vault_path: Path, project_name: str, content: str) -> str:
    result = _append_project_entry(vault_path, project_name, "Dev Log", content)
    if result.startswith("ERROR:"):
        return result
    return "OK: logged project update."


def capture_project_idea(vault_path: Path, project_name: str, idea: str) -> str:
    result = _append_project_entry(vault_path, project_name, "Ideas", idea)
    if result.startswith("ERROR:"):
        return result
    return "OK: captured project idea."


def record_project_decision(
    vault_path: Path,
    project_name: str,
    decision: str,
    rationale: str = "",
) -> str:
    clean_decision = decision.strip()
    if not clean_decision:
        return "ERROR: project decision is required."

    content = clean_decision
    clean_rationale = rationale.strip()
    if clean_rationale:
        content = f"{content} | rationale: {clean_rationale}"

    result = _append_project_entry(vault_path, project_name, "Decisions", content)
    if result.startswith("ERROR:"):
        return result
    return "OK: recorded project decision."
