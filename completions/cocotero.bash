_cocotero() {
  local cur
  cur="${COMP_WORDS[COMP_CWORD]}"
  if (( COMP_CWORD == 1 )); then
    COMPREPLY=($(compgen -W "add list open cat cats cluster pdf rm" -- "$cur"))
    return
  fi
  case "${COMP_WORDS[1]}" in
    open|cat|pdf|rm)
      if (( COMP_CWORD == 2 )); then
        local lib="${COCOTERO_LIB:-$HOME/cocotero/library}"
        COMPREPLY=($(compgen -W "$(ls "$lib" 2>/dev/null)" -- "$cur"))
      fi
      ;;
  esac
}

complete -F _cocotero cocotero