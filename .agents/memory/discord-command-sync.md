---
name: Discord command sync
description: Guild slash-command synchronization and CommandTree interaction checks
---

Discord.py's `CommandTree.interaction_check` is an overridable coroutine method, not a decorator. Assign the check function directly, and copy the current global command tree into the target guild before guild-syncing when command signatures change.

**Why:** Using the method as a decorator can create an un-awaited coroutine warning, while syncing a stale guild tree leaves Discord invoking an older slash-command signature.

**How to apply:** Keep guild sync explicit for this single-guild bot and run it after all extensions and commands are loaded.