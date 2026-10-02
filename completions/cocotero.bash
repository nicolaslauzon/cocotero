_cocotero() {
  local cur
  cur="${COMP_WORDS[COMP_CWORD]}"
  if (( COMP_CWORD == 1 )); then
    COMPREPLY=($(compgen -W "add open browse-cluster cite read cluster pdf rm clean sync reading login" -- "$cur"))
    return
  fi
  case "${COMP_WORDS[1]}" in
    reading)
      if (( COMP_CWORD == 2 )); then
        COMPREPLY=($(compgen -W "list current add progress done drop" -- "$cur"))
      elif (( COMP_CWORD == 3 )); then
        local lib="${COCOTERO_LIB:-$HOME/cocotero/library}"
        COMPREPLY=($(compgen -W "$(for f in "$lib"/bib/*.bib; do [ -e "$f" ] && basename "$f" .bib; done)" -- "$cur"))
      fi
      ;;
    open|pdf|rm|cite|read)
      if (( COMP_CWORD == 2 )); then
        local lib="${COCOTERO_LIB:-$HOME/cocotero/library}"
        COMPREPLY=($(compgen -W "$(for f in "$lib"/bib/*.bib; do [ -e "$f" ] && basename "$f" .bib; done)" -- "$cur"))
      fi
      ;;
    browse-cluster|cluster)
      if (( COMP_CWORD == 2 )); then
        local lib="${COCOTERO_LIB:-$HOME/cocotero/library}"
        COMPREPLY=($(compgen -W "$(grep -h '^category' "$lib"/bib/*.bib 2>/dev/null | sed 's/.*= {//; s/}.*//' | tr ',' ' ')" -- "$cur"))
      fi
      ;;
  esac
}

complete -F _cocotero cocotero