#!/bin/bash
# Auto-runs bd prime on Claude Code session start
# This hook ensures every agent has full Beads context on boot.

if command -v bd >/dev/null 2>&1; then
    bd prime 2>/dev/null || echo "⚠ bd prime failed — run manually if needed"
fi
