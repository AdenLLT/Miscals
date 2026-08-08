---
name: Leaderboard competition scopes
description: Rules for separating tournament, series, international, and career cricket statistics
---

Competition leaderboards must use explicit row metadata rather than inferring membership from timestamps or matching stat values. Tournament rows carry the tournament ID; series rows carry the series ID and an explicit international-inclusion flag. Untagged historical rows remain available to career statistics but are excluded from tournament and international leaderboards.

**Why:** Existing career data predates competition tagging, and timestamp/value inference can accidentally pull historical or duplicate series records into a currently running tournament.

**How to apply:** When adding a new match-stat ingestion path, write the active tournament or series identifier in the same transaction as the player row. Keep `nolbi` as a series-row flag and ensure all leaderboard pagination/graphics reuse the same scope.