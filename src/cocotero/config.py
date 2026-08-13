import os
import tomllib
from pathlib import Path
from typing import TypedDict

HOME = Path.home()
CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "cocotero" / "config.toml"


class Config(TypedDict):
    library: str
    unpaywall_email: str
    proxy_prefix: str
    downloads_dir: str
    pdf_priority: list[str]


DEFAULTS: Config = {
    "library": str(HOME / "cocotero" / "library"),
    "unpaywall_email": "",
    "proxy_prefix": "",
    "downloads_dir": str(HOME / "Downloads"),
    "pdf_priority": ["ieee", "semanticscholar", "unpaywall", "arxiv"],
}


def _defaults_toml() -> str:
    lines = ["# Cocotero configuration", "# Created automatically on first run."]
    for key, value in DEFAULTS.items():
        rendered = str(value) if isinstance(value, list) else f'"{value}"'
        lines.append(f"{key} = {rendered}")
    return "\n".join(lines) + "\n"


def load_config() -> Config:
    cfg_path = Path(os.environ.get("COCOTERO_CONFIG", str(CONFIG_PATH)))
    if not cfg_path.exists():
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(_defaults_toml())

    with open(cfg_path, "rb") as fh:
        cfg: Config = {**DEFAULTS, **tomllib.load(fh)}

    library = Path(os.environ.get("COCOTERO_LIB", str(cfg["library"]))).expanduser()
    library.mkdir(parents=True, exist_ok=True)
    cfg["library"] = str(library)
    return cfg


def user_agent() -> dict[str, str]:
    email = str(load_config()["unpaywall_email"])
    agent = f"Cocotero/0.1 (mailto:{email})" if email else "Cocotero/0.1"
    return {"User-Agent": agent}
