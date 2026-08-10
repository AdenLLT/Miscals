---
name: Unclaimed role eligibility
description: Claim-status rule for bulk unclaimed-role assignment
---

For bulk unclaimed-role assignment, a member is claimed if they have any configured Discord team role; a member without a team role is unclaimed. Do not use the claims database as the eligibility source.

**Why:** Database claims and Discord roles can become out of sync, causing already-claimed members to receive the unclaimed role.

**How to apply:** Check the member's current Discord roles against the central team-role mapping when adding or removing the unclaimed role, and use the same rule for cleanup runs.