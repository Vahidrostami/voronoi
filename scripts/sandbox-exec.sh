#!/bin/bash
# sandbox-exec.sh — Execute a command in the investigation's Docker sandbox.
# Falls back to host execution if no sandbox is running.
#
# Usage: ./scripts/sandbox-exec.sh <command> [args...]
#
# Reads .sandbox-id from the current directory to find the container.

set -euo pipefail

SANDBOX_FILE=".sandbox-id"

if [[ -f "$SANDBOX_FILE" ]]; then
    CONTAINER_ID=$(cat "$SANDBOX_FILE" | tr -d '[:space:]')
    if [[ -n "$CONTAINER_ID" ]] && docker inspect "$CONTAINER_ID" &>/dev/null; then
        exec docker exec -w /workspace "$CONTAINER_ID" "$@"
    fi
fi

# Fallback: run on host
exec "$@"
