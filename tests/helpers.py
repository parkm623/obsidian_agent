import importlib
import os
import sys
from pathlib import Path


def load_server(vault_path: Path | None, config_path: Path | None = None):
    if vault_path is not None:
        os.environ["OBSIDIAN_VAULT_PATH"] = str(vault_path)
    if config_path is not None:
        os.environ["OBSIDIAN_AGENT_CONFIG"] = str(config_path)
    sys.modules.pop("server", None)
    return importlib.import_module("server")
