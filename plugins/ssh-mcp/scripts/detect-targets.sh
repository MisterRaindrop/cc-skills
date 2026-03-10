#!/usr/bin/env bash
# detect-targets.sh - Scan SSH config for available host targets
# Usage: detect-targets.sh
# Exit 0 + prints host list if hosts found, exit 1 if none

set -euo pipefail

SSH_CONFIG="${HOME}/.ssh/config"

if [[ ! -f "$SSH_CONFIG" ]]; then
    echo "No SSH config found at $SSH_CONFIG" >&2
    exit 1
fi

# Parse Host entries from ~/.ssh/config
# Skips wildcard patterns (Host *)
found=0
current_host=""
current_user=""
current_port=""

while IFS= read -r line; do
    # Strip leading/trailing whitespace
    line="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

    # Skip empty lines and comments
    [[ -z "$line" || "$line" == \#* ]] && continue

    # Match Host directive (case-insensitive)
    if echo "$line" | grep -qi '^Host[[:space:]]'; then
        # Print previous host if we had one
        if [[ -n "$current_host" ]]; then
            printf "%s\t%s\t%s\n" "$current_host" "${current_user:--}" "${current_port:-22}"
            found=1
        fi

        # Extract host value, skip wildcards
        current_host="$(echo "$line" | sed 's/^[Hh][Oo][Ss][Tt][[:space:]]*//')"
        if [[ "$current_host" == *"*"* || "$current_host" == *"?"* ]]; then
            current_host=""
        fi
        current_user=""
        current_port=""
        continue
    fi

    # Match User directive
    if echo "$line" | grep -qi '^User[[:space:]]'; then
        current_user="$(echo "$line" | sed 's/^[Uu][Ss][Ee][Rr][[:space:]]*//')"
        continue
    fi

    # Match Port directive
    if echo "$line" | grep -qi '^Port[[:space:]]'; then
        current_port="$(echo "$line" | sed 's/^[Pp][Oo][Rr][Tt][[:space:]]*//')"
        continue
    fi
done < "$SSH_CONFIG"

# Print last host
if [[ -n "$current_host" ]]; then
    printf "%s\t%s\t%s\n" "$current_host" "${current_user:--}" "${current_port:-22}"
    found=1
fi

if [[ "$found" -eq 0 ]]; then
    echo "No SSH hosts found in $SSH_CONFIG" >&2
    exit 1
fi

exit 0
