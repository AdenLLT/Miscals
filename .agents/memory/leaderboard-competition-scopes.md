---
name: Leaderboard competition scopes
description: Rules for separating tournament, series, international, and career cricket statistics
---

Competition leaderboards must use explicit row metadata rather than inferring membership from timestamps or matching stat values. Tournament rows carry the tournament ID; tournament and series rows carry an explicit international-inclusion flag; series rows also carry the series ID. Untagged historical rows remain available to career statistics but are excluded from tournament leaderboards. LBI uses the full non-tournament international history and must never include running-tournament rows.

**Why:** Existing career data predates competition tagging, and timestamp/value inference can accidentally pull historical or duplicate series records into a currently running tournament.

**How to apply:** When adding a new match-stat ingestion path, write the active tournament or series identifier in the same transaction as the player row. Keep `nolbi` or sync-only behavior as an explicit inclusion flag, and ensure personal ongoing stats and all leaderboard pagination/graphics reuse the same scope. For LBI, query non-tournament `match_stats` rows where `include_in_lbi = 1`.