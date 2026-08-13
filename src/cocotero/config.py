import os
import tomllib
from pathlib import Path

HOME = Path.home()
CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "cocotero" / "config.toml"

DEFAULTS: dict[str, object] = {
    "library": str(HOME / "cocotero" / "library"),
    "unpaywall_email": "",
    "proxy_prefix": "",
    "downloads_dir": str(HOME / "Downloads"),
    "pdf_priority": ["ieee", "semanticscholar", "unpaywall", "arxiv"],
}


def _defaults_toml() -> str:
    lines = ["# Cocotero configuration", "# Created automatically on first run.\n"]
    for key, value in DEFAULTS.items():
        rendered = str(value) if isinstance(value, list) else f'"{value}"'
        lines.append(f"{key} = {rendered}")
    return "\n".join(lines) + "\n"


def load_config() -> dict[str, object]:
    cfg_path = Path(os.environ.get("COCOTERO_CONFIG", str(CONFIG_PATH)))
    if not cfg_path.exists():
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(_defaults_toml())

    with open(cfg_path, "rb") as fh:
        cfg = {**DEFAULTS, **tomllib.load(fh)}

    library = Path(os.environ.get("COCOTERO_LIB", str(cfg["library"]))).expanduser()
    library.mkdir(parents=True, exist_ok=True)
    cfg["library"] = str(library)
    return cfg