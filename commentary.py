import discord
import asyncio
import json
import random
import sqlite3
import time as _time
import re
import urllib.request
import urllib.error

# ── Commentator profiles ──────────────────────────────────────────────────────
COMMENTATORS = [
    {
        "key":    "pommie",
        "name":   "Pommie Mbangwa - Commentator",
        "avatar": "https://i.ibb.co/YJd99j4/321487-1.webp",
        "style":  (
            "You are Pommie Mbangwa, the legendary Zimbabwean TV cricket commentator. "
            "You are warm, insightful, and occasionally poetic. You appreciate craft, "
            "build tension naturally, and speak about a player's character and mental "
            "strength. Your observations are measured but hit hard when the moment calls."
        )
    },
    {
        "key":    "doull",
        "name":   "Simon Doull - Commentator",
        "avatar": "https://i.ibb.co/SwBcrxNM/Screenshot-2026-07-28-200911.png",
        "style":  (
            "You are Simon Doull, the blunt and opinionated New Zealand cricket commentator. "
            "You love dissecting technique and quoting stats. You won't hold back criticism "
            "of a poor shot or a loose delivery. On a six or a key wicket you get genuinely "
            "fired up; on a dot ball you get analytical."
        )
    }
]

# ── Webhook cache: channel_id -> {"pommie": Webhook, "doull": Webhook} ───────
_webhooks: dict = {}

# ── Commentary history ────────────────────────────────────────────────────────
_history: list = []  # [{"key": str, "name": str, "text": str}]

# ── Change-detection tracking ─────────────────────────────────────────────────
_last_timeline_key: str = ""
_last_wicket_id:    str = ""
_last_commentator:  str = "doull"  # alternate from this


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _sanitize_emoji_name(name: str) -> str:
    return ''.join(c if c.isalnum() or c == '_' else '_' for c in name)[:32]


def _get_player_emoji(full_name: str, bot) -> str:
    if not full_name:
        return ""
    ename = _sanitize_emoji_name(full_name)
    for guild in bot.guilds:
        em = discord.utils.get(guild.emojis, name=ename)
        if em:
            return str(em)
    return ""


def _format_player(discord_username: str, full_name: str, bot) -> str:
    """Return: emoji **FirstName** (@discord)"""
    first = (full_name or discord_username).split()[0] if (full_name or discord_username) else discord_username
    emoji = _get_player_emoji(full_name or discord_username, bot)
    if emoji:
        return f"{emoji} **{first}** (@{discord_username})"
    return f"**{first}** (@{discord_username})"


async def _get_webhooks(channel, bot) -> dict:
    """Get or create both commentator webhooks for the channel."""
    cid = channel.id
    if cid in _webhooks:
        return _webhooks[cid]
    try:
        existing = await channel.webhooks()
        wh_map = {}
        for c_info in COMMENTATORS:
            found = next((w for w in existing if w.name == c_info["name"]), None)
            if found:
                wh_map[c_info["key"]] = found
            else:
                av_bytes = None
                try:
                    req = urllib.request.Request(
                        c_info["avatar"], headers={"User-Agent": "Mozilla/5.0"}
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        av_bytes = resp.read()
                except Exception:
                    pass
                new_wh = await channel.create_webhook(name=c_info["name"], avatar=av_bytes)
                wh_map[c_info["key"]] = new_wh
        _webhooks[cid] = wh_map
        return wh_map
    except Exception as e:
        print(f"[COMMENTARY] Webhook error for channel {cid}: {e}")
        return {}


def _build_match_block(state: dict, bot) -> str:
    """Build a concise match-situation string for the AI prompt."""
    lines = []

    team_a   = state.get('team_a_name', '')
    team_b   = state.get('team_b_name', '')
    batting  = state.get('batting_team', '') or team_a
    score    = state.get('team_a_score', '')
    overs    = state.get('overs', '')
    target   = state.get('target', '')

    if score:
        lines.append(f"Score: {batting} {score} ({overs} ov)")
    if target:
        lines.append(str(target))
    if team_a and team_b:
        lines.append(f"Match: {team_a} vs {team_b}")

    on_strike = state.get('on_strike')
    for idx, prefix in enumerate(['batsman1', 'batsman2'], start=1):
        uname = state.get(f'{prefix}_username', '')
        fname = state.get(f'{prefix}_full_name', '') or uname
        sc    = state.get(f'{prefix}_score', '')
        if uname:
            mark = " [ON STRIKE]" if on_strike == idx else ""
            lines.append(f"Batter: {_format_player(uname, fname, bot)} — {sc}{mark}")

    buname = state.get('bowler_username', '')
    bfname = state.get('bowler_full_name', '') or buname
    bstats = state.get('bowler_stats', '')
    if buname:
        lines.append(f"Bowler: {_format_player(buname, bfname, bot)} — {bstats}")

    # Current over balls
    timeline = state.get('timeline', [])
    if timeline:
        balls_in_cur = len(timeline) % 6
        cur_over_balls = timeline[-balls_in_cur:] if balls_in_cur else timeline[-6:]
        over_num = len(timeline) // 6
        lines.append(f"Current over {over_num}: {' | '.join(cur_over_balls)}")

    return "\n".join(lines)


async def _generate_commentary(state: dict, event: str, bot) -> dict:
    """Generate one commentary line from one commentator. Returns {"key", "name", "text"}."""
    from playerlife import call_openrouter

    global _last_commentator

    # Alternate commentators
    if _last_commentator == "pommie":
        this_c  = COMMENTATORS[1]  # doull
        other_c = COMMENTATORS[0]
    else:
        this_c  = COMMENTATORS[0]  # pommie
        other_c = COMMENTATORS[1]

    # 35% chance of replying to the other commentator
    is_reply = bool(_history) and random.random() < 0.35

    hist_block = ""
    if _history:
        hist_lines = [f"  {h['name']}: {h['text']}" for h in _history[-6:]]
        hist_block = "Recent commentary exchange:\n" + "\n".join(hist_lines)

    match_block = _build_match_block(state, bot)

    event_desc = {
        'ball':       "A delivery has just been bowled.",
        'boundary_4': "FOUR! A boundary has just been struck.",
        'boundary_6': "SIX! A maximum has just been launched into the stands.",
        'wicket':     "WICKET! A batsman has just been dismissed.",
        'over_end':   "The over has just been completed.",
    }.get(event, "Play is continuing.")

    wicket_detail = ""
    if event == 'wicket' and state.get('pending_wicket'):
        wd = state['pending_wicket']
        wicket_detail = (
            f"\nDismissal: {wd.get('out_player_name', '')} out for "
            f"{wd.get('runs', '?')} ({wd.get('balls', '?')} balls) — "
            f"{wd.get('dismissal_text', '')}."
        )

    reply_instr = (
        f"You are REPLYING to {other_c['name']} who just said: \"{_history[-1]['text']}\". "
        "Acknowledge briefly then add your own angle."
        if is_reply and _history
        else "Give your own live commentary for this moment."
    )

    # Flavour for sixes/fours/deliveries
    flavour = ""
    if event == 'boundary_6':
        metres = random.randint(82, 120)
        flavour = f"Mention the six travelled around {metres} metres."
    elif event == 'boundary_4':
        flavour = "Describe briefly how the ball reached the boundary — placement or timing."
    elif event in ('ball', 'over_end'):
        kmh = random.randint(118, 148)
        flavour = f"You may reference the delivery speed was around {kmh} km/h if it fits."

    prompt = f"""{this_c['style']}

=== LIVE MATCH SITUATION ===
{match_block}

{hist_block}

=== CURRENT EVENT ===
{event_desc}{wicket_detail}

=== YOUR LINE ===
{reply_instr}
{flavour}

Strict rules:
- Write exactly 1–3 sentences of live TV commentary. HARD max 200 characters total.
- When mentioning a player, use ONLY their FIRST NAME with this EXACT format as shown in the match block: emoji **FirstName** (@discordusername). Do not invent players not listed.
- Sound like a real broadcast commentator — natural pacing, no hashtags, no excessive emojis.
- Wicket / six = excited energy. Dot ball = analytical. Over end = summary feel.
- Do NOT use filler phrases like "indeed", "certainly", "absolutely", "well there we have it".

Return ONLY valid JSON, no markdown fences:
{{"text": "your commentary line here"}}"""

    raw = await call_openrouter(prompt, max_tokens=200)
    raw = raw.strip()
    s = raw.find('{'); e = raw.rfind('}')
    if s != -1 and e != -1:
        raw = raw[s:e+1]
    raw = re.sub(r',\s*([}\]])', r'\1', raw)
    data = json.loads(raw)
    return {
        "key":  this_c["key"],
        "name": this_c["name"],
        "text": data.get("text", "").strip()
    }


# ─── Main loop ─────────────────────────────────────────────────────────────────

async def background_commentary(bot):
    global _last_timeline_key, _last_wicket_id, _last_commentator

    await asyncio.sleep(20)
    print("[COMMENTARY] AI commentary system started.")

    while True:
        try:
            import matchupdates
            state = dict(matchupdates._live_match_state)

            if not state or not state.get('channel_id'):
                await asyncio.sleep(12)
                continue

            # Ignore stale state (match ended / no activity > 10 min)
            if _time.time() - state.get('last_updated', 0) > 600:
                await asyncio.sleep(12)
                continue

            channel_id = state['channel_id']
            channel = bot.get_channel(channel_id)
            if not channel:
                await asyncio.sleep(12)
                continue

            tkey      = state.get('timeline_key', '')
            wicket    = state.get('pending_wicket')
            last_ball = state.get('last_ball', '')
            over_done = state.get('over_completed', False)

            is_new_state  = tkey != _last_timeline_key
            wicket_id     = f"{(wicket or {}).get('out_player_name','')}_{(wicket or {}).get('runs','')}"
            is_new_wicket = wicket is not None and wicket_id != _last_wicket_id

            if not is_new_state and not is_new_wicket:
                await asyncio.sleep(10)
                continue

            # Choose event
            if is_new_wicket:
                event = 'wicket'
                _last_wicket_id = wicket_id
            elif over_done:
                event = 'over_end'
            elif last_ball == '6':
                event = 'boundary_6'
            elif last_ball == '4':
                event = 'boundary_4'
            else:
                event = 'ball'

            _last_timeline_key = tkey

            # Get/create webhooks
            wh_map = await _get_webhooks(channel, bot)
            if not wh_map:
                await asyncio.sleep(12)
                continue

            # Generate commentary
            result = await _generate_commentary(state, event, bot)
            if not result or not result.get('text'):
                await asyncio.sleep(10)
                continue

            c_key  = result['key']
            c_text = result['text']
            c_info = next(c for c in COMMENTATORS if c['key'] == c_key)
            webhook = wh_map.get(c_key)
            if not webhook:
                await asyncio.sleep(10)
                continue

            await webhook.send(content=c_text, username=c_info['name'], avatar_url=c_info['avatar'])

            _history.append({"key": c_key, "name": c_info['name'], "text": c_text})
            if len(_history) > 12:
                _history.pop(0)
            _last_commentator = c_key

            # Clear the wicket flag after it's been commented on
            if event == 'wicket':
                matchupdates._live_match_state.pop('pending_wicket', None)

            print(f"[COMMENTARY] [{c_info['name']}] ({event}): {c_text[:80]}")

        except Exception as exc:
            import traceback
            print(f"[COMMENTARY] Error: {exc}")
            traceback.print_exc()

        await asyncio.sleep(random.randint(10, 16))


def start_commentary(bot):
    """Call from on_ready to launch the AI commentary loop."""
    asyncio.get_event_loop().create_task(background_commentary(bot))
