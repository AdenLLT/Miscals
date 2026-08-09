---
name: Discord SQLite concurrency
description: SQLite contention and event-loop responsiveness rules for the Discord bot
---

Discord callbacks and background tasks must not perform blocking SQLite reads or writes directly on the event loop. Use short-lived connections with a busy timeout, WAL mode for the shared database, and worker threads for synchronous database operations.

**Why:** A feed cache query waiting on another writer can block Discord heartbeats and surface as `database is locked`; copying only the main database file can also omit committed WAL contents.

**How to apply:** Keep feed/cache database helpers thread-backed, use the shared connection safeguards for legacy synchronous paths, and checkpoint WAL state before sending database backups.