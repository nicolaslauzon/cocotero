import shutil
import subprocess
import webbrowser


class MissingToolError(RuntimeError):
    pass


def fzf_select(lines: list[str], preview_cmd: str | None = None) -> str | None:
    if shutil.which("fzf") is None:
        raise MissingToolError(
            "fzf is required but not installed (e.g. `apt install fzf`)."
        )
    cmd = ["fzf", "--no-multi"]
    if preview_cmd:
        cmd += ["--preview", preview_cmd, "--preview-window", "right:60%"]
    proc = subprocess.run(
        cmd,
        input="\n".join(lines) + "\n",
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def open_in_browser(url: str) -> None:
    xdg_open = shutil.which("xdg-open")
    if xdg_open:
        subprocess.Popen([xdg_open, url], stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(url)
