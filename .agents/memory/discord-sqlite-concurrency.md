---
name: Discord SQLite concurrency
description: SQLite contention and event-loop responsiveness rules for the Discord bot
---

Discord callbacks and background tasks must not perform blocking SQLite reads or writes directly on the event loop. Use short-lived connections with a busy timeout, WAL mode for the shared database, worker threads for synchronous database operations, and bounded retries for transient lock errors.

**Why:** A feed cache query waiting on another writer can block Discord heartbeats and surface as `database is locked`; copying only the main database file can omit committed WAL contents, while forcing a WAL truncate checkpoint can create extra writer contention.

**How to apply:** Keep feed/cache database helpers thread-backed, use shared connection safeguards for legacy synchronous paths, retry only lock errors with a short bounded backoff, and use SQLite's online backup API before sending database backups.