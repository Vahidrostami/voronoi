#!/bin/bash
# SessionStart hook: auto-runs bd prime on Claude Code session start
# This hook ensures every agent has full Beads context on boot.
# Registered in .claude/settings.json under hooks.SessionStart

if command -v bd >/dev/null 2>&1; then
    bd prime 2>/dev/null || echo "⚠ bd prime failed — run manually if needed" >&2
fi

exit 0
