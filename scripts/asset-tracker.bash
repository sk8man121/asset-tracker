# Bash completion for asset-tracker. Source from your shell:
#   source /path/to/asset-tracker/scripts/asset-tracker.bash

_asset_tracker_completions() {
    local cur prev words cword
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    local cmds="init log recent doctor summary dashboard backup export export-csv seed config project channel tx time metrics integrations import import-mock"

    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "${cmds}" -- "${cur}") )
        return 0
    fi

    case "${COMP_WORDS[1]}" in
        log|recent|summary|dashboard|doctor|backup)
            COMPREPLY=( $(compgen -W "--project --channel --notes --days" -- "${cur}") )
            ;;
        import|import-mock)
            COMPREPLY=( $(compgen -W "stripe gumroad bandcamp github_sponsors etsy --since --until --count" -- "${cur}") )
            ;;
        config)
            COMPREPLY=( $(compgen -W "show set --default-project --default-channel" -- "${cur}") )
            ;;
    esac
}

complete -F _asset_tracker_completions asset-tracker
