"""Weighbridge edge agent — offline SQLite mirror for an unstable link.

Runs on the weighbridge PC alongside the scale agent. Holds a local SQLite
mirror so gate passes, tokens and invoicing keep working while the internet is
down, then replays the captured intents to the cloud when it returns.

The server remains the single source of truth: local records are authoritative
only until synced. See ~/.claude/plans/linear-splashing-map.md for the design.
"""
