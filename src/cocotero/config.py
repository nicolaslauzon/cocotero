import os
import tomllib
from pathlib import Path
from typing import TypedDict

HOME = Path.home()
CONFIG_PATH = (
    Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
    / "cocotero"
    / "config.toml"
)


class Config(TypedDict):
    library: str
    unpaywall_email: str
    proxy_prefix: str
    downloads_dir: str
    pdf_priority: list[str]
    handoff_mode: str
    libkey_library_id: str
    drive_remote: str
    auto_sync: bool


DEFAULTS: Config = {
    "library": str(HOME / "cocotero" / "library"),
    "unpaywall_email": "",
    "proxy_prefix": "",
    "downloads_dir": str(HOME / "Downloads"),
    "pdf_priority": ["ieee", "semanticscholar", "unpaywall", "crossref", "arxiv"],
    "handoff_mode": "assisted",
    "libkey_library_id": "",
    "drive_remote": "",
    "auto_sync": True,
}


def config_dir() -> Path:
    return Path(os.environ.get("COCOTERO_CONFIG", str(CONFIG_PATH))).parent


def _render(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return str(value)
    return f'"{value}"'


def _defaults_toml() -> str:
    lines = ["# Cocotero configuration", "# Created automatically on first run."]
    for key, value in DEFAULTS.items():
        rendered = _render(value)
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
    from . import __version__

    email = str(load_config()["unpaywall_email"])
    agent = (
        f"Cocotero/{__version__} (mailto:{email})"
        if email
        else f"Cocotero/{__version__}"
    )
    return {"User-Agent": agent}
