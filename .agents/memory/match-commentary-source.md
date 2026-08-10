---
name: Match commentary source
description: Source-of-truth and lifecycle rules for cricket match updates and AI commentary
---

Match commentary must use the monitored cricket bot's original message text as its factual source, not the parsed timeline used to render a status image. A final MVP or match-duration announcement ends the channel's match and invalidates pending commentary.

**Why:** A rendered timeline is a presentation artifact and can omit or reinterpret context from the bot's individual update messages. Without an explicit terminal reset, stale commentary can continue after the match has ended or leak into the next match.

**How to apply:** Store the observed source message with accepted per-channel match state, derive event classification from that message, and version state so in-flight commentary checks validity immediately before sending. Reset channel deduplication and commentary history when the final-result pattern arrives.