_cocotero() {
  local cur
  cur="${COMP_WORDS[COMP_CWORD]}"
  if (( COMP_CWORD == 1 )); then
    COMPREPLY=($(compgen -W "add list open" -- "$cur"))
    return
  fi
  if [[ "${COMP_WORDS[1]}" == "open" && COMP_CWORD -eq 2 ]]; then
    local lib="${COCOTERO_LIB:-$HOME/cocotero/library}"
    COMPREPLY=($(compgen -W "$(ls "$lib" 2>/dev/null)" -- "$cur"))
  fi
}

complete -F _cocotero cocotero