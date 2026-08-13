#!/bin/sh
set -eu

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
zsh_dir="${HOME}/.local/share/zsh/site-functions"
bash_dir="${HOME}/.local/share/bash-completion/completions"
marker="cocotero completions"

mkdir -p "${zsh_dir}" "${bash_dir}"
install -m 644 "${repo_dir}/completions/_cocotero" "${zsh_dir}/_cocotero"
install -m 644 "${repo_dir}/completions/cocotero.bash" "${bash_dir}/cocotero"

zshrc="${ZDOTDIR:-${HOME}}/.zshrc"
if [ -f "${zshrc}" ] && ! grep -q "${marker}" "${zshrc}" 2>/dev/null; then
  {
    printf '\n# %s\n' "${marker}"
    printf 'fpath+=(%s)\n' "${zsh_dir}"
    if ! grep -q "compinit" "${zshrc}" 2>/dev/null; then
      printf 'autoload -Uz compinit && compinit\n'
    fi
  } >> "${zshrc}"
  echo "Enabled zsh completions in ${zshrc}"
fi

echo "Installed cocotero completions."
echo "Restart your shell (or run: source ~/.zshrc) to activate."