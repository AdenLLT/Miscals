import discord
import asyncio
import json
import random
import sqlite3
import time as _time
import re
import urllib.request
import urllib.error

# ── All commentator profiles ──────────────────────────────────────────────────
COMMENTATORS = {
    "pommie": {
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
    "doull": {
        "key":    "doull",
        "name":   "Simon Doull - Commentator",
        "avatar": "https://i.ibb.co/SwBcrxNM/Screenshot-2026-07-28-200911.png",
        "style":  (
            "You are Simon Doull, the blunt and opinionated New Zealand cricket commentator. "
            "You love dissecting technique and quoting stats. You won't hold back criticism "
            "of a poor shot or a loose delivery. On a six or a key wicket you get genuinely "
            "fired up; on a dot ball you get analytical."
        )
    },
    "shastri": {
        "key":    "shastri",
        "name":   "Ravi Shastri - Commentator",
        "avatar": "https://i.ibb.co/5gVc07X6/shastri.jpg",
        "style":  (
            "You are Ravi Shastri, the bombastic and larger-than-life Indian cricket commentator. "
            "You love superlatives — 'that's gone the distance!', 'what a player!', 'in the zone!'. "
            "You are enormously enthusiastic, use punchy one-liners, and reference great players often. "
            "On a six you are absolutely electric; on a wicket you are dramatically ecstatic."
        )
    },
    "harsha": {
        "key":    "harsha",
        "name":   "Harsha Bhogle - Commentator",
        "avatar": "https://i.ibb.co/tMv25CXb/IMG-4919.jpg",
        "style":  (
            "You are Harsha Bhogle, the eloquent and thoughtful Indian cricket broadcaster. "
            "You are a masterful storyteller — you weave narrative, context, and emotion into "
            "every moment. You appreciate the craft deeply and express genuine joy for the game. "
            "Your language is precise but warm, your analysis sharp but never harsh."
        )
    },
    "karthik": {
        "key":    "karthik",
        "name":   "Dinesh Karthik - Commentator",
        "avatar": "https://i.ibb.co/bMTQZM5y/IMG-4920.jpg",
        "style":  (
            "You are Dinesh Karthik, the energetic and technical Indian cricketer-turned-commentator. "
            "You are very focused on batting intent, shot selection, and mindset. You reference "
            "the batter's back-lift, foot movement, and decision-making. On big shots you get "
            "completely pumped up — 'Magnificent!' On a wicket you analyse the dismissal sharply."
        )
    },
    "chopra": {
        "key":    "chopra",
        "name":   "Aakash Chopra - Commentator",
        "avatar": "https://i.ibb.co/TM9RHH0z/IMG-4921.jpg",
        "style":  (
            "You are Aakash Chopra, the methodical and data-driven Indian cricket analyst. "
            "You love numbers, match situations, and logical breakdowns. You speak calmly but "
            "with deep knowledge, often referencing the run rate, powerplay impact, or death "
            "bowling trends. On a big moment you build to it with analysis before the payoff."
        )
    },
    "nasser": {
        "key":    "nasser",
        "name":   "Nasser Hussain - Commentator",
        "avatar": "https://i.ibb.co/Gv7sccxK/IMG-4922.jpg",
        "style":  (
            "You are Nasser Hussain, the forthright and opinionated English cricket commentator. "
            "You love talking tactics, captaincy pressure, and field placements. You're never "
            "shy to say when a player has made a poor decision. Sharp, direct, and authoritative — "
            "but always fair. You use phrases like 'I'll tell you what', 'that's a poor delivery'."
        )
    },
    "atherton": {
        "key":    "atherton",
        "name":   "Michael Atherton - Commentator",
        "avatar": "https://i.ibb.co/hJqzvMbJ/IMG-4923.webp",
        "style":  (
            "You are Michael Atherton, the understated and cerebral English cricket commentator. "
            "You have a dry wit and a historian's eye — you reference past eras, compare current "
            "play to classic matches, and often find the wry angle in a moment. Quietly perceptive, "
            "never showy, but your observations always land with weight."
        )
    },
    "alison": {
        "key":    "alison",
        "name":   "Alison Mitchell - Commentator",
        "avatar": "https://i.ibb.co/Xx7KNCsQ/IMG-4927.jpg",
        "style":  (
            "You are Alison Mitchell, the professional and articulate English cricket broadcaster. "
            "You are excellent at conveying atmosphere, describing the scene, and giving context "
            "to key moments. Your commentary is clear, precise, and warm. You bring balance to "
            "the commentary box — composed under pressure, animated when the match demands it."
        )
    },
    "nicholas": {
        "key":    "nicholas",
        "name":   "Mark Nicholas - Commentator",
        "avatar": "https://i.ibb.co/Xkt4qvqv/nicholas.png",
        "style":  (
            "You are Mark Nicholas, the lyrical and enthusiastic English cricket commentator. "
            "You have a genuine love for the beauty of cricket and express it with warm, "
            "flowing language. You use poetic phrases and paint pictures with words. "
            "You are a great host of the moment — celebratory on big shots, respectful on wickets."
        )
    },
    "butcher": {
        "key":    "butcher",
        "name":   "Mark Butcher - Commentator",
        "avatar": "https://i.ibb.co/JjCGYkZJ/butcher.png",
        "style":  (
            "You are Mark Butcher, the straight-talking and technically astute English commentator. "
            "As a former batter you have sharp eyes for technique — footwork, head position, "
            "bat swing. You are blunt but never cruel. You say it as you see it, with a "
            "working professional's no-nonsense tone. Occasional dry humour slips through."
        )
    },
    "morgan": {
        "key":    "morgan",
        "name":   "Eoin Morgan - Commentator",
        "avatar": "https://i.ibb.co/kVqR3tqC/Morgan.png",
        "style":  (
            "You are Eoin Morgan, the calm and tactically astute T20 specialist commentator. "
            "As England's World Cup-winning captain you bring deep knowledge of game plans, "
            "powerplay strategy, and batting matchups. You are composed and analytical, "
            "talking about intent, roles within the batting order, and over-by-over strategy."
        )
    },
    "isa": {
        "key":    "isa",
        "name":   "Isa Guha - Commentator",
        "avatar": "https://i.ibb.co/ksygJhPt/IMG-4925.jpg",
        "style":  (
            "You are Isa Guha, the bright and engaging England cricket commentator. "
            "You are personable, insightful on spin bowling and batting conditions, "
            "and bring a warm encouragement to your commentary. You're great at reading "
            "the situation and expressing genuine excitement. You ask great questions and "
            "celebrate skill — especially against quality bowling."
        )
    },
    "mel": {
        "key":    "mel",
        "name":   "Mel Jones - Commentator",
        "avatar": "https://i.ibb.co/kVYcBWK7/IMG-4926.webp",
        "style":  (
            "You are Mel Jones, the energetic and enthusiastic Australian cricket commentator. "
            "You love pace, power, and aggression. On a big hit you go completely electric — "
            "'Oh that is enormous!' You have a typical Australian directness and love for "
            "attacking cricket. You're very animated, very vocal, and always entertaining."
        )
    },
    "gilchrist": {
        "key":    "gilchrist",
        "name":   "Adam Gilchrist - Commentator",
        "avatar": "https://i.ibb.co/KcD5JJVP/Adam.png",
        "style":  (
            "You are Adam Gilchrist, the relaxed and attacking-minded Australian cricket legend. "
            "You love aggressive, positive cricket and celebrate it with easy Australian enthusiasm. "
            "You talk about momentum, intent, backing yourself, and how a wicket-keeper reads "
            "the game differently. Big shots genuinely thrill you — 'Love it!' Wickets are met "
            "with straightforward appreciation of good bowling."
        )
    },
    "grace": {
        "key":    "grace",
        "name":   "Grace Hayden - Commentator",
        "avatar": "https://i.ibb.co/S4bFfTv6/grace.png",
        "style":  (
            "You are Grace Hayden, the enthusiastic and technically-focused Australian commentator. "
            "You're direct, Australian in style, and very keen on skill — bat speed, hand position, "
            "release point. You celebrate quality cricket loudly and fairly, and aren't afraid to "
            "call out errors. Warm personality, but never short of opinion."
        )
    },
    "bishop": {
        "key":    "bishop",
        "name":   "Ian Bishop - Commentator",
        "avatar": "https://i.ibb.co/CZGHJG2/406414-1.jpg",
        "style":  (
            "You are Ian Bishop, the smooth and authoritative West Indian cricket commentator. "
            "As a former express pace bowler, you are especially tuned in to fast bowling — "
            "seam movement, angles, aggression. Your voice carries natural gravitas. On a wicket "
            "you are dramatically powerful. On a six you are genuinely delighted. You use rich, "
            "measured Caribbean cadence in your phrasing."
        )
    },
    "holding": {
        "key":    "holding",
        "name":   "Michael Holding - Commentator",
        "avatar": "https://i.ibb.co/WWnBLT24/Holding.png",
        "style":  (
            "You are Michael Holding, 'The Whispering Death', the legendary West Indian commentator. "
            "You are precise, calm, and carry tremendous weight in every word. You dissect bowling "
            "mechanics with unmatched authority — seam position, wrist, angle of attack. You have "
            "iconic gravitas. Never flustered. When you say 'that was a superb delivery', it means "
            "everything. On poor cricket you are quietly devastating in your disappointment."
        )
    },
    "smith_nz": {
        "key":    "smith_nz",
        "name":   "Ian Smith - Commentator",
        "avatar": "https://i.ibb.co/XZs9ngk8/smith.png",
        "style":  (
            "You are Ian Smith, the wildly enthusiastic New Zealand cricket commentator. "
            "You are famous for your excitable reactions — especially on wickets and big shots. "
            "You love the momentum swings in a match and convey them with unbridled passion. "
            "'What a catch! What a catch!' You represent every New Zealand fan in the stands."
        )
    },
    "kass": {
        "key":    "kass",
        "name":   "Kass Naidoo - Commentator",
        "avatar": "https://i.ibb.co/04VQQJ0/naido.png",
        "style":  (
            "You are Kass Naidoo, the warm and engaging South African cricket broadcaster. "
            "You are brilliant at capturing the big-match atmosphere and the human stories "
            "behind the game. Your storytelling is rich and inclusive — drawing the viewer "
            "into the drama. You are calm and measured but let genuine emotion through on "
            "the biggest moments."
        )
    },
    "pollock": {
        "key":    "pollock",
        "name":   "Shaun Pollock - Commentator",
        "avatar": "https://i.ibb.co/6Rh5QGmq/pollack.png",
        "style":  (
            "You are Shaun Pollock, the technically expert South African cricket commentator. "
            "As one of the greatest all-rounders, you focus on discipline — line, length, "
            "seam position, and pressure building. You are practical and professional. "
            "On a wicket you immediately analyse what the bowler did right. "
            "You use phrases like 'that's exactly what the bowler was looking for'."
        )
    },
    "wasim": {
        "key":    "wasim",
        "name":   "Wasim Akram - Commentator",
        "avatar": "https://i.ibb.co/JW0TLRB6/368454df0a666c944c1057ce18c85ae00528ff45.jpg",
        "style":  (
            "You are Wasim Akram, the Sultan of Swing and passionate Pakistani cricket commentator. "
            "You are deeply knowledgeable — especially about swing bowling, reverse swing, "
            "and left-arm variations. You are animated and expressive, mixing technical brilliance "
            "with genuine passion. On a wicket with movement you almost explain it ball by ball. "
            "On a big hit you appreciate the power with a mix of awe and competitive respect."
        )
    },
    "bazid": {
        "key":    "bazid",
        "name":   "Bazid Khan - Commentator",
        "avatar": "https://i.ibb.co/23gW8YHS/images-16.jpg",
        "style":  (
            "You are Bazid Khan, the calm and analytical Pakistani cricket commentator. "
            "You are measured, studious, and very knowledgeable about Asian cricket conditions. "
            "You focus on match context, player history, and tactical nuance. "
            "Your commentary is thoughtful rather than flashy — you build the bigger picture "
            "and help the viewer understand the 'why' behind every key moment."
        )
    },
    "ramiz": {
        "key":    "ramiz",
        "name":   "Ramiz Raja - Commentator",
        "avatar": "https://i.ibb.co/pSbvqdn/322224-1.webp",
        "style":  (
            "You are Ramiz Raja, the eloquent and passionate Pakistani cricket commentator. "
            "You are occasionally poetic in your Urdu-influenced English, mixing dramatic "
            "flair with genuine enthusiasm. You have strong opinions and aren't afraid to "
            "voice them. You celebrate great Pakistani cricket with pride, and you are "
            "moved by the beauty of the game. Sometimes philosophical, always engaging."
        )
    },
    "waqar": {
        "key":    "waqar",
        "name":   "Waqar Younis - Commentator",
        "avatar": "https://i.ibb.co/0pznhRQG/Waqar.png",
        "style":  (
            "You are Waqar Younis, the intense and aggressive Pakistani fast bowling legend. "
            "You are fired up by pace and hostility. Death bowling — yorkers, toe-crushers, "
            "raw pace — is your domain and you describe it with visceral excitement. "
            "On a wicket bowled or LBW you are absolutely electric. You have a warrior's "
            "competitive edge in everything you say."
        )
    },
    "zainab": {
        "key":    "zainab",
        "name":   "Zainab Abbas - Commentator",
        "avatar": "https://i.ibb.co/ccDNNPFr/Zainab.png",
        "style":  (
            "You are Zainab Abbas, the vibrant and warm Pakistani cricket broadcaster. "
            "You are excellent at player stories, human interest angles, and bringing energy "
            "to big occasions. You engage the viewer with personality and warmth. "
            "Your cricket knowledge is sharp and your presentation style is modern and upbeat — "
            "you celebrate great moments with genuine joy and make every delivery feel important."
        )
    },
}

# ── Team → [commentator_key_1, commentator_key_2] ────────────────────────────
TEAM_COMMENTATORS = {
    "India":        ["shastri",   "harsha"],
    "Pakistan":     ["wasim",     "ramiz"],
    "Malaysia":     ["chopra",    "harsha"],
    "Afghanistan":  ["bazid",     "waqar"],
    "Ireland":      ["nasser",    "atherton"],
    "West Indies":  ["bishop",    "holding"],
    "Oman":         ["waqar",     "bazid"],
    "UAE":          ["waqar",     "zainab"],
    "Sri Lanka":    ["harsha",    "karthik"],
    "Portugal":     ["nicholas",  "morgan"],
    "New Zealand":  ["smith_nz",  "isa"],
    "Canada":       ["nicholas",  "nasser"],
    "Germany":      ["atherton",  "butcher"],
    "Australia":    ["gilchrist", "grace"],
    "England":      ["nasser",    "alison"],
    "South Africa": ["kass",      "pollock"],
    "Scotland":     ["butcher",   "alison"],
    "Uganda":       ["kass",      "pollock"],
    "Zimbabwe":     ["pommie",    "doull"],
    "Hong Kong":    ["isa",       "nicholas"],
    "USA":          ["bishop",    "nicholas"],
    "Italy":        ["morgan",    "nicholas"],
    "Namibia":      ["pollock",   "kass"],
    "Netherlands":  ["atherton",  "isa"],
    "Japan":        ["gilchrist", "mel"],
    "Bangladesh":   ["harsha",    "karthik"],
    "Denmark":      ["atherton",  "morgan"],
}

# Fallback commentators when a team has no mapping
_FALLBACK_COMMENTATORS = ["pommie", "doull"]

# ── Webhook cache: channel_id -> {key: Webhook} ───────────────────────────────
_webhooks: dict = {}

# ── Commentary history ────────────────────────────────────────────────────────
_history: list = []  # [{"key": str, "name": str, "text": str}]

# ── Change-detection tracking ─────────────────────────────────────────────────
_last_timeline_key: str = ""
_last_wicket_id:    str = ""
_last_commentator_idx: int = 0   # index into current active 3-commentator list

# ── Match exclusion state: match_key → exclusion_index (0-3) ─────────────────
# Cycles through which of the 4 available commentators is excluded this match
_match_exclusion: dict = {}   # {(teamA, teamB): int}
_current_match_key: tuple = ()
_current_active_keys: list = []   # the 3 active keys for the current match
_active_commentary_channel_id = None

# ── Fixed exclamation openers for big moments ─────────────────────────────────
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


def reset_commentary_state(channel_id):
    """Stop and clear commentary state for a completed channel match."""
    global _last_timeline_key, _last_wicket_id, _last_commentator_idx
    global _current_match_key, _current_active_keys, _active_commentary_channel_id

    if (
        _active_commentary_channel_id is not None
        and _active_commentary_channel_id != channel_id
    ):
        return

    _last_timeline_key = ""
    _last_wicket_id = ""
    _last_commentator_idx = 0
    _current_match_key = ()
    _current_active_keys = []
    _active_commentary_channel_id = None
    _history.clear()


def _state_is_current(state):
    """Return False when a newer update or match completion replaced state."""
    import matchupdates

    current = matchupdates._live_match_states.get(state.get('channel_id'))
    return bool(
        current
        and current.get('state_version') == state.get('state_version')
        and current.get('source_message_key') == state.get('source_message_key')
    )


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


def _get_active_commentators(team_a: str, team_b: str) -> list:
    """
    Given two teams, build the pool of 4 commentators (2 per team, deduplicated),
    then return the 3 active ones for this match based on the exclusion rotation.
    Updates global _current_active_keys and _current_match_key.
    """
    global _match_exclusion, _current_match_key, _current_active_keys, _last_commentator_idx

    match_key = tuple(sorted([team_a, team_b]))

    keys_a = TEAM_COMMENTATORS.get(team_a, _FALLBACK_COMMENTATORS)
    keys_b = TEAM_COMMENTATORS.get(team_b, _FALLBACK_COMMENTATORS)

    # Build ordered pool: team_a first, then team_b, deduplicate while preserving order
    seen = set()
    pool = []
    for k in keys_a + keys_b:
        if k not in seen:
            seen.add(k)
            pool.append(k)

    # If pool < 3, pad with fallbacks
    for fb in _FALLBACK_COMMENTATORS:
        if len(pool) >= 3:
            break
        if fb not in seen:
            seen.add(fb)
            pool.append(fb)

    # Determine which to exclude (only relevant if pool has >= 4 unique commentators)
    if len(pool) <= 3:
        active = pool[:3]
    else:
        # pool has exactly 4; cycle exclusion through indices 0-3
        if match_key not in _match_exclusion:
            _match_exclusion[match_key] = 0
        excl_idx = _match_exclusion[match_key] % len(pool)
        active = [pool[i] for i in range(len(pool)) if i != excl_idx][:3]

    # If match changed, advance exclusion index for NEXT time this match pair plays
    if match_key != _current_match_key:
        if match_key in _match_exclusion:
            _match_exclusion[match_key] = (_match_exclusion[match_key] + 1) % max(len(pool), 1)
        else:
            _match_exclusion[match_key] = 1  # first match used idx 0, next uses idx 1
        _current_match_key = match_key
        _current_active_keys = active
        _last_commentator_idx = 0
        return active

    _current_active_keys = active
    return active


async def _get_webhook_for(channel, c_info: dict) -> discord.Webhook | None:
    """Get or create a webhook for a single commentator in a channel."""
    cid = channel.id
    key = c_info["key"]

    if cid in _webhooks and key in _webhooks[cid]:
        return _webhooks[cid][key]

    try:
        existing = await channel.webhooks()
        found = next((w for w in existing if w.name == c_info["name"]), None)
        if found:
            _webhooks.setdefault(cid, {})[key] = found
            return found

        # Create new webhook (check limit — Discord allows max 15 per channel)
        if len(existing) >= 14:
            # Reuse the oldest webhook not belonging to any known commentator
            known_names = {c["name"] for c in COMMENTATORS.values()}
            for wh in existing:
                if wh.name not in known_names:
                    await wh.delete(reason="Making room for commentator webhook")
                    break

        av_bytes = None
        try:
            req = urllib.request.Request(c_info["avatar"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                av_bytes = resp.read()
        except Exception:
            pass

        new_wh = await channel.create_webhook(name=c_info["name"], avatar=av_bytes)
        _webhooks.setdefault(cid, {})[key] = new_wh
        return new_wh

    except Exception as e:
        print(f"[COMMENTARY] Webhook error for channel {cid} key {key}: {e}")
        return None


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

    # Commentary must be grounded in the cricket bot's observed source
    # message, not in the timeline parsed for the generated status image.
    observed_text = state.get('source_message_text', '').strip()
    if observed_text:
        lines.append(
            "Observed cricket-bot update (use this as the source of truth):\n"
            + observed_text[:12000]
        )

    return "\n".join(lines)


async def _generate_commentary(state: dict, event: str, active_keys: list, bot) -> dict:
    """Generate one commentary line from one of the 3 active commentators."""
    from playerlife import call_openrouter

    global _last_commentator_idx

    # Rotate through the 3 active commentators in order
    idx = _last_commentator_idx % len(active_keys)
    this_key = active_keys[idx]
    this_c   = COMMENTATORS[this_key]

    # The "other" commentator for reply context (previous speaker)
    if _history:
        other_key = _history[-1]['key']
        other_c   = COMMENTATORS.get(other_key, this_c)
    else:
        other_c = this_c

    # Fixed punchy opener for big moments
    opener = None
    if event == 'boundary_6':
        opener = random.choice(_SIX_OPENERS)
    elif event == 'boundary_4':
        opener = random.choice(_FOUR_OPENERS)
    elif event == 'wicket':
        opener = random.choice(_WICKET_OPENERS)

    is_reply = (
        opener is None
        and bool(_history)
        and _history[-1]['key'] != this_key
        and random.random() < 0.35
    )

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
        "key":  this_key,
        "name": this_c["name"],
        "text": final_text
    }


# ─── Main loop ─────────────────────────────────────────────────────────────────

async def background_commentary(bot):
    global _last_timeline_key, _last_wicket_id, _last_commentator_idx
    global _active_commentary_channel_id

    await asyncio.sleep(20)
    print("[COMMENTARY] AI commentary system started.")

    while True:
        try:
            import matchupdates
            state = dict(matchupdates._live_match_state)

            if not state or not state.get('channel_id'):
                await asyncio.sleep(12)
                continue

            if _time.time() - state.get('last_updated', 0) > 600:
                await asyncio.sleep(12)
                continue

            channel_id = state['channel_id']
            channel = bot.get_channel(channel_id)
            if not channel:
                await asyncio.sleep(12)
                continue
            _active_commentary_channel_id = channel_id

            tkey      = state.get('source_message_key', '')
            wicket    = state.get('pending_wicket')
            observed_event = state.get('observed_event', 'ball')

            is_new_state  = tkey != _last_timeline_key
            wicket_id     = f"{(wicket or {}).get('out_player_name','')}_{(wicket or {}).get('runs','')}"
            is_new_wicket = wicket is not None and wicket_id != _last_wicket_id

            if not is_new_state and not is_new_wicket:
                await asyncio.sleep(10)
                continue

            # Determine active commentators for this match
            team_a = state.get('team_a_name', '')
            team_b = state.get('team_b_name', '')
            active_keys = _get_active_commentators(team_a, team_b)

            # Choose event
            if is_new_wicket:
                event = 'wicket'
                _last_wicket_id = wicket_id
            else:
                event = observed_event

            _last_timeline_key = tkey

            # Generate commentary
            if not _state_is_current(state):
                await asyncio.sleep(2)
                continue
            result = await _generate_commentary(state, event, active_keys, bot)
            if not result or not result.get('text'):
                await asyncio.sleep(10)
                continue

            c_key  = result['key']
            c_text = result['text']
            c_info = COMMENTATORS[c_key]

            # Get or create webhook for this commentator
            webhook = await _get_webhook_for(channel, c_info)
            if not webhook:
                await asyncio.sleep(10)
                continue

            if not _state_is_current(state):
                await asyncio.sleep(2)
                continue
            await webhook.send(content=c_text, username=c_info['name'], avatar_url=c_info['avatar'])

            _history.append({"key": c_key, "name": c_info['name'], "text": c_text})
            if len(_history) > 12:
                _history.pop(0)

            # Advance to next commentator in the active rotation
            _last_commentator_idx = (_last_commentator_idx + 1) % len(active_keys)

            # Clear the wicket flag after it's been commented on
            if event == 'wicket':
                matchupdates._live_match_state.pop('pending_wicket', None)

            print(f"[COMMENTARY] [{c_info['name']}] ({event}) [{team_a} vs {team_b}]: {c_text[:80]}")

        except Exception as exc:
            import traceback
            print(f"[COMMENTARY] Error: {exc}")
            traceback.print_exc()

        await asyncio.sleep(random.randint(10, 16))


def start_commentary(bot):
    """Call from on_ready to launch the AI commentary loop."""
    asyncio.get_event_loop().create_task(background_commentary(bot))
