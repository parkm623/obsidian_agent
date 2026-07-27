import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    config: dict[str, object]
    vault_path: Path
    index_path: Path
    audit_log_path: Path
    backup_path: Path
    ignored_folders: set[str]


def load_config(default_config_path: Path) -> dict[str, object]:
    config_path = Path(os.getenv("OBSIDIAN_AGENT_CONFIG", default_config_path)).expanduser()
    if not config_path.exists():
        return {}

    try:
        return tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def load_settings(project_root: Path) -> Settings:
    default_vault_path = project_root / "obsidian_vault"
    default_config_path = project_root / "obsidian_agent.toml"
    config = load_config(default_config_path)
    config_vault_path = config.get("vault_path", default_vault_path)
    vault_path = Path(os.getenv("OBSIDIAN_VAULT_PATH", config_vault_path)).expanduser().resolve()
    agent_path = vault_path / ".obsidian_agent"

    ignored_folders = {
        ".obsidian_agent",
        *[str(folder) for folder in config.get("ignored_folders", [])],
    }

    return Settings(
        config=config,
        vault_path=vault_path,
        index_path=agent_path / "index.sqlite3",
        audit_log_path=agent_path / "audit.log",
        backup_path=agent_path / "backups",
        ignored_folders=ignored_folders,
    )
