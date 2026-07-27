import re
from datetime import datetime
from pathlib import Path
from typing import Iterable


INVALID_FILENAME_CHARS = re.compile(r'[*?:"<>|]')
FRONTMATTER_BLOCK = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
INLINE_TAG = re.compile(r"(?<![\w/])#([A-Za-z0-9][A-Za-z0-9_/-]*)")
WIKI_LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")


def is_safe_path(target_path: Path, vault_path: Path) -> bool:
    """Return True when target_path stays inside the configured vault."""
    try:
        return target_path.resolve().is_relative_to(vault_path)
    except OSError:
        return False


def sanitize_path(title: str) -> str:
    """Allow nested folders while removing Windows-invalid filename characters."""
    normalized = title.replace("\\", "/").strip()
    normalized = INVALID_FILENAME_CHARS.sub("_", normalized)
    parts = []

    for part in normalized.split("/"):
        part = part.strip()
        if not part or part in {".", ".."}:
            continue
        parts.append(part)

    return "/".join(parts)


def note_path(title: str, vault_path: Path) -> Path:
    sanitized_title = sanitize_path(title)
    if not sanitized_title:
        raise ValueError("note title is empty after sanitization")

    file_path = vault_path / f"{sanitized_title}.md"
    if not is_safe_path(file_path, vault_path):
        raise ValueError("note path is outside the configured vault")

    return file_path


def normalize_tags(tags: object) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        return [tag.strip() for tag in tags.split(",") if tag.strip()]
    if isinstance(tags, Iterable):
        return [str(tag).strip() for tag in tags if str(tag).strip()]
    return [str(tags).strip()]


def frontmatter(tags: object) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    final_tags = normalize_tags(tags)

    if final_tags:
        tags_yaml = "".join(f"\n  - {tag}" for tag in final_tags)
        return f"---\ndate: {today}\ntags:{tags_yaml}\n---\n\n"

    return f"---\ndate: {today}\ntags: []\n---\n\n"


def note_name(path: Path, vault_path: Path) -> str:
    return path.relative_to(vault_path).with_suffix("").as_posix()


def unique_path(file_path: Path) -> Path:
    if not file_path.exists():
        return file_path

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return file_path.with_name(f"{file_path.stem}_{timestamp}{file_path.suffix}")


def frontmatter_text(content: str) -> str:
    match = FRONTMATTER_BLOCK.match(content)
    if not match:
        return ""
    return match.group(1)


def body_text(content: str) -> str:
    return FRONTMATTER_BLOCK.sub("", content, count=1)


def frontmatter_tags(content: str) -> list[str]:
    frontmatter = frontmatter_text(content)
    if not frontmatter:
        return []

    tags = []
    lines = frontmatter.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("tags:"):
            value = stripped.removeprefix("tags:").strip()
            if value.startswith("[") and value.endswith("]"):
                tags.extend(tag.strip().strip("'\"") for tag in value[1:-1].split(","))
            elif value:
                tags.extend(tag.strip().strip("'\"") for tag in value.split(","))
            else:
                index += 1
                while index < len(lines) and lines[index].lstrip().startswith("- "):
                    tags.append(lines[index].split("- ", 1)[1].strip().strip("'\""))
                    index += 1
                continue
        index += 1

    return [tag for tag in tags if tag]


def extract_tags(content: str) -> list[str]:
    tags = set(frontmatter_tags(content))
    tags.update(INLINE_TAG.findall(body_text(content)))
    return sorted(tags)


def extract_links(content: str) -> list[str]:
    links = {match.strip() for match in WIKI_LINK.findall(content)}
    return sorted(link for link in links if link)


def safe_backup_name(relative_path: str) -> str:
    return INVALID_FILENAME_CHARS.sub("_", relative_path.replace("/", "__"))
