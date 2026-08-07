---
name: Discord image uploads
description: Reliability and deduplication rules for image messages sent through discord.py
---

When sending generated images to Discord, create a new `discord.File` and fresh byte stream for every retry. Record message, timeline, or event deduplication only after Discord accepts the upload.

**Why:** An interrupted aiohttp upload can consume the file stream and leave the connection unusable; marking the event before sending can then suppress the only later retry.

**How to apply:** Keep image generation separate from delivery, retry only transient transport/rate-limit/server failures, and leave permission or payload errors as immediate failures.