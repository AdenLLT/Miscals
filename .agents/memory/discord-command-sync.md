---
name: Discord command sync
description: Guild slash-command synchronization and CommandTree interaction checks
---

Discord.py's `CommandTree.interaction_check` is an overridable coroutine method, not a decorator. Assign the check function directly. For this single-server bot, keep `/matchtime` guild-scoped and remove it from the global tree before syncing.

**Why:** Using the method as a decorator can create an un-awaited coroutine warning, while leaving a command in both global and guild trees makes Discord show duplicate commands or invoke an older signature.

**How to apply:** Remove the stale global command, clear and rebuild the target guild tree from current commands, then sync global removals and the guild command set after all extensions are loaded.