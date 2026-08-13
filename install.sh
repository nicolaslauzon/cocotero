#!/bin/sh
set -eu

repo_url="${COCOTERO_REPO:-https://github.com/nicolaslauzon/cocotero}"
ezproxy=0
for arg in "$@"; do
  case "${arg}" in
    --ezproxy|-e) ezproxy=1 ;;
  esac
done

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if [ "${ezproxy}" -eq 1 ]; then
  uv tool install --from "git+${repo_url}" cocotero --with playwright
  "$(uv tool dir)/cocotero/bin/python" -m playwright install chromium
else
  uv tool install --from "git+${repo_url}" cocotero
fi

repo_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -d "${repo_dir}/completions" ]; then
  sh "${repo_dir}/scripts/install_completions.sh"
fi

echo "cocotero installed. Run: cocotero --help"