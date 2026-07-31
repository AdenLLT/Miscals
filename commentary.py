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

# ── Fixed exclamation openers for big moments (guarantees the format/tone) ───
_SIX_OPENERS = [
    "6️⃣ **SIX!**", "6️⃣ **SIX! Maximum!**", "6️⃣ **MASSIVE SIX!**", "6️⃣ **SIX! Into the stands!**",
    "6️⃣ **HUGE SIX!**", "6️⃣ **SIX! Gone all the way!**", "6️⃣ **SIX! That's out of here!**",
]
_FOUR_OPENERS = [
    "4️⃣ **FOUR!**", "4️⃣ **FOUR! Races away!**", "4️⃣ **CRACKING FOUR!**", "4️⃣ **FOUR! Finds the gap!**",
    "4️⃣ **BEAUTIFUL FOUR!**", "4️⃣ **FOUR! Timed to perfection!**", "4️⃣ **FOUR! Superb shot!**",
]
_WICKET_OPENERS = [
    "🚨 **OUT!**", "🎯 **WICKET!**", "❌ **GONE!**", "🔥 **THAT'S OUT!**", "🚨 **WICKET!**", "💥 **GOT HIM!**",
]


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


def _format_player(user_id, discord_username: str, full_name: str, guild, bot) -> str:
    """Return: emoji **FirstName** **__DisplayName__** using the member's live Discord display name."""
    base = full_name or discord_username or "Player"
    first = base.split()[0] if base else "Player"
    emoji = _get_player_emoji(full_name or discord_username, bot)

    display_name = discord_username or first
    if user_id and guild:
        try:
            member = guild.get_member(int(user_id))
            if member:
                display_name = member.display_name
        except Exception:
            pass

    tag = f"**__{display_name}__**"
    return f"{emoji} {tag}" if emoji else tag


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
    """Build a concise, fact-grounded match-situation string for the AI prompt."""
    lines = []

    channel = bot.get_channel(state.get('channel_id'))
    guild = channel.guild if channel else None

    team_a   = state.get('team_a_name', '')
    team_b   = state.get('team_b_name', '')
    batting  = state.get('batting_team', '') or team_a
    score    = state.get('team_a_score', '')
    overs    = state.get('overs', '')
    innings    = state.get('innings', 'ONE')
    target_str = state.get('target', '')

    if score:
        lines.append(f"Score: {batting} {score} ({overs} ov)")
    if team_a and team_b:
        lines.append(f"Match: {team_a} vs {team_b}")

    # Ground the innings/target facts explicitly — this is what stops the AI
    # from hallucinating a run-chase during the 1st innings.
    if innings == "TWO" and target_str:
        tm = re.search(r'(\d+)', str(target_str))
        sm = re.match(r'\s*(\d+)', score)
        lines.append(f"Innings: 2nd innings — {target_str}.")
        if tm and sm:
            runs_needed = int(tm.group(1)) - int(sm.group(1))
            lines.append(
                f"Needs {runs_needed} more runs to win. "
                "(Do NOT state balls remaining or required run rate — not available.)"
            )
    else:
        lines.append(
            "Innings: 1st innings — there is NO target yet. Do NOT mention chasing, "
            "a target, required run rate, or \"runs/balls needed\"."
        )

    on_strike = state.get('on_strike')
    for idx, prefix in enumerate(['batsman1', 'batsman2'], start=1):
        uname = state.get(f'{prefix}_username', '')
        fname = state.get(f'{prefix}_full_name', '') or uname
        uid   = state.get(f'{prefix}_user_id')
        sc    = state.get(f'{prefix}_score', '')
        if uname:
            mark = " [ON STRIKE]" if on_strike == idx else ""
            lines.append(f"Batter: {_format_player(uid, uname, fname, guild, bot)} — {sc}{mark}")

    buname = state.get('bowler_username', '')
    bfname = state.get('bowler_full_name', '') or buname
    buid   = state.get('bowler_user_id')
    bstats = state.get('bowler_stats', '')
    if buname:
        lines.append(f"Bowler: {_format_player(buid, buname, bfname, guild, bot)} — {bstats}")

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

    # Fixed punchy opener for big moments — deterministic, not left to the AI
    opener = None
    if event == 'boundary_6':
        opener = random.choice(_SIX_OPENERS)
    elif event == 'boundary_4':
        opener = random.choice(_FOUR_OPENERS)
    elif event == 'wicket':
        opener = random.choice(_WICKET_OPENERS)

    # 35% chance of replying to the other commentator (skip during big-moment openers)
    is_reply = opener is None and bool(_history) and random.random() < 0.35

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
        channel = bot.get_channel(state.get('channel_id'))
        guild = channel.guild if channel else None
        out_mention = _format_player(
            wd.get('out_user_id'), wd.get('out_username', ''), wd.get('out_full_name', ''), guild, bot
        )
        wicket_detail = (
            f"\nDismissal: {out_mention} out for "
            f"{wd.get('runs', '?')} ({wd.get('balls', '?')} balls) — "
            f"{wd.get('dismissal_text', '')}."
        )

    reply_instr = (
        f"You are REPLYING to {other_c['name']} who just said: \"{_history[-1]['text']}\". "
        "Acknowledge briefly then add your own angle."
        if is_reply
        else "Give your own live commentary for this moment."
    )

    if opener:
        # The exclamation itself is fixed in code — the AI only writes the elaboration after it.
        task_block = (
            f'Your line will be shown to viewers starting with the fixed call "{opener}" — that part is '
            'already handled, do NOT repeat or rephrase SIX / FOUR / OUT / WICKET / GONE yourself. '
            'Write ONLY a short, punchy follow-up (max 140 characters) describing HOW it happened — '
            'shot type, direction, fielding effort, a plausible distance/speed if it fits.'
        )
    else:
        flavour = ""
        if event in ('ball', 'over_end'):
            kmh = random.randint(118, 148)
            flavour = f"You may reference the delivery speed was around {kmh} km/h if it fits."
        task_block = f"{reply_instr}\n{flavour}\nHARD max 200 characters."

    prompt = f"""{this_c['style']}

=== LIVE MATCH SITUATION (ONLY use facts listed here — never invent scores, targets, run rates, or balls remaining) ===
{match_block}

{hist_block}

=== CURRENT EVENT ===
{event_desc}{wicket_detail}

=== YOUR LINE ===
{task_block}

Strict rules:
- When mentioning a player, copy their EXACT mention format from the match situation block above (emoji + bold first name + bold-underlined display name). Do not invent players not listed there.
- Sound like a real broadcast commentator — natural pacing, no hashtags, no excessive emojis.
- Wicket / six = excited energy. Dot ball = analytical. Over end = summary feel.
- Do NOT use filler phrases like "indeed", "certainly", "absolutely", "well there we have it".
- Never mention a target, chase, required run rate, or "X off Y needed" unless the match situation block explicitly states it.

Return ONLY valid JSON, no markdown fences:
{{"text": "your commentary line here"}}"""

    raw = await call_openrouter(prompt, max_tokens=200)
    raw = raw.strip()
    s = raw.find('{'); e = raw.rfind('}')
    if s != -1 and e != -1:
        raw = raw[s:e+1]
    raw = re.sub(r',\s*([}\]])', r'\1', raw)
    data = json.loads(raw)
    ai_text = data.get("text", "").strip()
    final_text = f"{opener} {ai_text}".strip() if opener else ai_text

    return {
        "key":  this_c["key"],
        "name": this_c["name"],
        "text": final_text
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
