#!/bin/bash
# Bash completion for docker-janitor

_docker_janitor() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    
    # Available options
    opts="--help --daemon --dry-run"
    
    case "${prev}" in
        docker-janitor)
            COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
            return 0
            ;;
        *)
            ;;
    esac
    
    COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
    return 0
}

# Register the completion function
complete -F _docker_janitor docker-janitor

# Also enable completion for common typos and shortcuts
complete -F _docker_janitor docker-jan
complete -F _docker_janitor dj