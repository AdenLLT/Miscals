import discord
import sqlite3
import json
import random
from datetime import datetime, timedelta
from discord.ext import commands
from discord.ui import View, Select

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────
EXCLUDED_EMOJI_SERVER = 1451591563078533292
MAX_SQUAD_SIZE        = 15
DROP_COOLDOWN_HOURS   = 0  # No cooldown


# ──────────────────────────────────────────────────────────────
# DATABASE
# ──────────────────────────────────────────────────────────────
def _db():
    return sqlite3.connect('players.db')


def init_minigame_db():
    conn = _db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS minigame_squads (
        user_id      INTEGER,
        player_name  TEXT,
        claimed_uid  INTEGER,
        role         TEXT,
        team         TEXT,
        added_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, player_name)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS minigame_captains (
        user_id  INTEGER PRIMARY KEY,
        captain  TEXT,
        vc       TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS minigame_drops (
        user_id   INTEGER PRIMARY KEY,
        last_drop TIMESTAMP
    )''')
    conn.commit()
    conn.close()


def get_squad(user_id: int):
    """Returns list of (player_name, claimed_uid, role, team)."""
    conn = _db()
    c = conn.cursor()
    c.execute(
        "SELECT player_name, claimed_uid, role, team "
        "FROM minigame_squads WHERE user_id=? ORDER BY role, player_name",
        (user_id,)
    )
    rows = c.fetchall()
    conn.close()
    return rows


def get_squad_size(user_id: int) -> int:
    conn = _db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM minigame_squads WHERE user_id=?", (user_id,))
    n = c.fetchone()[0]
    conn.close()
    return n


def already_in_squad(user_id: int, player_name: str) -> bool:
    conn = _db()
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM minigame_squads WHERE user_id=? AND player_name=?",
        (user_id, player_name)
    )
    row = c.fetchone()
    conn.close()
    return row is not None


def add_to_squad(user_id: int, player_name: str, claimed_uid: int, role: str, team: str):
    conn = _db()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO minigame_squads (user_id, player_name, claimed_uid, role, team) "
        "VALUES (?,?,?,?,?)",
        (user_id, player_name, claimed_uid, role, team)
    )
    conn.commit()
    conn.close()


def get_captains(user_id: int):
    """Returns (captain_name, vc_name) or (None, None)."""
    conn = _db()
    c = conn.cursor()
    c.execute("SELECT captain, vc FROM minigame_captains WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return (row[0], row[1]) if row else (None, None)


def set_captains(user_id: int, captain: str, vc: str):
    conn = _db()
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO minigame_captains (user_id, captain, vc) VALUES (?,?,?)",
        (user_id, captain, vc)
    )
    conn.commit()
    conn.close()


def clear_invalid_captains(user_id: int):
    """Remove captain/vc if those players are no longer in the squad."""
    squad_names = {r[0] for r in get_squad(user_id)}
    cap, vc = get_captains(user_id)
    new_cap = cap if cap in squad_names else None
    new_vc  = vc  if vc  in squad_names else None
    if new_cap != cap or new_vc != vc:
        set_captains(user_id, new_cap or '', new_vc or '')


def get_last_drop(user_id: int):
    conn = _db()
    c = conn.cursor()
    c.execute("SELECT last_drop FROM minigame_drops WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def set_last_drop(user_id: int):
    conn = _db()
    c = conn.cursor()
    ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    c.execute(
        "INSERT OR REPLACE INTO minigame_drops (user_id, last_drop) VALUES (?,?)",
        (user_id, ts)
    )
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────────
# PLAYER / TEAM HELPERS
# ──────────────────────────────────────────────────────────────
_PLAYERS_CACHE: list = []

def _load_players_json() -> list:
    global _PLAYERS_CACHE
    if not _PLAYERS_CACHE:
        with open('players.json', 'r') as f:
            _PLAYERS_CACHE = json.load(f)
    return _PLAYERS_CACHE


def _get_player_info(player_name: str):
    """Returns (role, team) from players.json."""
    try:
        for td in _load_players_json():
            for p in td.get('players', []):
                if p.get('name') == player_name:
                    return p.get('role', 'Batsman'), td.get('team', 'Unknown')
    except Exception:
        pass
    return 'Batsman', 'Unknown'


def _get_all_claimed():
    """Returns list of (player_name, user_id) from player_representatives."""
    conn = _db()
    c = conn.cursor()
    c.execute(
        "SELECT player_name, user_id FROM player_representatives "
        "WHERE player_name IS NOT NULL"
    )
    rows = c.fetchall()
    conn.close()
    return rows


_TEAM_FLAGS = {
    "India": "🇮🇳", "Pakistan": "🇵🇰", "Australia": "🇦🇺", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "New Zealand": "🇳🇿", "South Africa": "🇿🇦", "West Indies": "🏝️", "Sri Lanka": "🇱🇰",
    "Bangladesh": "🇧🇩", "Afghanistan": "🇦🇫", "Netherlands": "🇳🇱", "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "Ireland": "🇮🇪", "Zimbabwe": "🇿🇼", "UAE": "🇦🇪", "Canada": "🇨🇦", "USA": "🇺🇸",
    "Nepal": "🇳🇵", "Namibia": "🇳🇦", "Hong Kong": "🇭🇰", "Italy": "🇮🇹",
}


def _flag(team: str) -> str:
    return _TEAM_FLAGS.get(team, "🏳️")


def _get_player_emoji(player_name: str, bot) -> str:
    """Look up the custom Discord emoji for a player across all non-main guilds."""
    if not bot:
        return ""
    emoji_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in player_name)[:32]
    for guild in bot.guilds:
        if guild.id == EXCLUDED_EMOJI_SERVER:
            continue
        eo = discord.utils.get(guild.emojis, name=emoji_name)
        if eo:
            return str(eo)
    return ""


def _role_category(role: str) -> str:
    if role and "Wicketkeeper" in role:
        return "WK"
    if role and ("All-Rounder" in role or "All-rounder" in role or "Allrounder" in role):
        return "ALR"
    if role and "Bowler" in role:
        return "BOWL"
    return "BAT"


# ──────────────────────────────────────────────────────────────
# ELECT VIEW
# ──────────────────────────────────────────────────────────────
class ElectView(View):
    def __init__(self, user_id: int, squad_names: list, bot):
        super().__init__(timeout=120)
        self.user_id        = user_id
        self.bot            = bot
        self.captain_choice = None
        self.vc_choice      = None

        options = [discord.SelectOption(label=n[:100], value=n) for n in squad_names[:25]]

        cap_sel = Select(
            placeholder="👑 Choose Captain (2X multiplier)",
            options=options,
            custom_id="mpg_captain"
        )
        cap_sel.callback = self._captain_cb
        self.add_item(cap_sel)

        vc_sel = Select(
            placeholder="🥈 Choose Vice-Captain (1.5X multiplier)",
            options=options,
            custom_id="mpg_vc"
        )
        vc_sel.callback = self._vc_cb
        self.add_item(vc_sel)

        btn = discord.ui.Button(
            label="✅ Confirm Selection",
            style=discord.ButtonStyle.green,
            custom_id="mpg_confirm"
        )
        btn.callback = self._confirm_cb
        self.add_item(btn)

    async def _captain_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Not your menu!", ephemeral=True)
        self.captain_choice = interaction.data['values'][0]
        await interaction.response.send_message(
            f"👑 Captain set to **{self.captain_choice}**", ephemeral=True
        )

    async def _vc_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Not your menu!", ephemeral=True)
        self.vc_choice = interaction.data['values'][0]
        await interaction.response.send_message(
            f"🥈 Vice-Captain set to **{self.vc_choice}**", ephemeral=True
        )

    async def _confirm_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Not your menu!", ephemeral=True)
        if not self.captain_choice:
            return await interaction.response.send_message(
                "❌ Please select a **Captain** first!", ephemeral=True
            )
        if not self.vc_choice:
            return await interaction.response.send_message(
                "❌ Please select a **Vice-Captain** first!", ephemeral=True
            )
        if self.captain_choice == self.vc_choice:
            return await interaction.response.send_message(
                "❌ Captain and Vice-Captain can't be the same player!", ephemeral=True
            )
        set_captains(self.user_id, self.captain_choice, self.vc_choice)
        cap_emoji  = _get_player_emoji(self.captain_choice, self.bot)
        vc_emoji   = _get_player_emoji(self.vc_choice,      self.bot)
        cap_line   = f"{cap_emoji} **{self.captain_choice}**" if cap_emoji else f"**{self.captain_choice}**"
        vc_line    = f"{vc_emoji} **{self.vc_choice}**"      if vc_emoji  else f"**{self.vc_choice}**"
        embed = discord.Embed(
            title="✅ Leadership Elected!",
            description=(
                f"👑 **Captain (2X):** {cap_line}\n"
                f"🥈 **Vice-Captain (1.5X):** {vc_line}"
            ),
            color=0xFFD700
        )
        await interaction.response.edit_message(embed=embed, view=None)


# ──────────────────────────────────────────────────────────────
# COG
# ──────────────────────────────────────────────────────────────
class MiniPlayerGame(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        init_minigame_db()

    # ── -drop ────────────────────────────────────────────────
    @commands.command(name="drop", help="Drop a random claimed player card into your squad (max 15).")
    async def drop_command(self, ctx):
        user_id = ctx.author.id

        # Squad cap check
        size = get_squad_size(user_id)
        if size >= MAX_SQUAD_SIZE:
            embed = discord.Embed(
                title="🚫 Squad Full!",
                description=(
                    f"You already have **{MAX_SQUAD_SIZE}/{MAX_SQUAD_SIZE}** players — "
                    f"your squad is at its limit!\nUse **-mysquad** to view your squad."
                ),
                color=0xFF4444
            )
            return await ctx.send(embed=embed)

        # Gather claimed players
        all_claimed = _get_all_claimed()
        if not all_claimed:
            return await ctx.send("❌ No claimed players found in the database.")

        # Exclude players already in this user's squad
        already = {r[0] for r in get_squad(user_id)}
        available = [(pn, uid) for pn, uid in all_claimed if pn not in already]
        if not available:
            return await ctx.send(
                "❌ You already have every claimed player in your squad! "
                "Nothing new to drop."
            )

        loading = await ctx.send("🎴 Dropping a player card...")

        # Scan card cache once and try to find a player that has a card
        try:
            from cricket_stats import scan_card_cache
            card_cache = await scan_card_cache(self.bot)
        except Exception:
            card_cache = {}

        random.shuffle(available)
        picked_name  = None
        picked_uid   = None
        card_url     = None

        # Prefer players that have a cached card
        for pn, uid in available:
            cached = card_cache.get(uid)
            if cached and cached.get('url'):
                picked_name = pn
                picked_uid  = uid
                card_url    = cached['url']
                break

        # Fallback: any available player
        if not picked_name:
            picked_name, picked_uid = available[0]

        # Look up role + team
        role, team = _get_player_info(picked_name)
        flag  = _flag(team)
        emoji = _get_player_emoji(picked_name, self.bot)

        # Discord info of the person who claimed this player
        try:
            claimed_user = self.bot.get_user(picked_uid) or await self.bot.fetch_user(picked_uid)
            discord_handle = claimed_user.name if claimed_user else f"uid:{picked_uid}"
        except Exception:
            discord_handle = f"uid:{picked_uid}"

        # Persist
        add_to_squad(user_id, picked_name, picked_uid, role, team)

        new_size = get_squad_size(user_id)

        # Build embed
        emoji_prefix = f"{emoji} " if emoji else ""
        description  = f"{emoji_prefix}**{picked_name} (__@{discord_handle}__)** {flag}"

        embed = discord.Embed(
            title=f"You got @{discord_handle}",
            description=description,
            color=0xFFD700
        )
        embed.set_footer(text=picked_name)
        if card_url:
            embed.set_image(url=card_url)

        embed.add_field(name="🏏 Role",    value=role,               inline=True)
        embed.add_field(name="🌍 Team",    value=f"{flag} {team}",   inline=True)
        embed.add_field(name="📋 Squad",   value=f"{new_size}/{MAX_SQUAD_SIZE}", inline=True)

        await loading.edit(content=None, embed=embed)

    # ── -mysquad ─────────────────────────────────────────────
    @commands.command(name="mysquad", help="View your mini player squad.")
    async def mysquad_command(self, ctx):
        user_id = ctx.author.id
        squad   = get_squad(user_id)

        if not squad:
            embed = discord.Embed(
                title="📋 Your Squad",
                description="Your squad is empty!\nUse **-drop** to collect players.",
                color=0x2B2D31
            )
            return await ctx.send(embed=embed)

        clear_invalid_captains(user_id)
        captain, vc = get_captains(user_id)

        # Group by category
        cats: dict = {"WK": [], "BAT": [], "BOWL": [], "ALR": []}
        for pname, claimed_uid, role, team in squad:
            cats[_role_category(role)].append((pname, claimed_uid, team))

        cat_labels = {
            "WK":   "🧤 Wicketkeepers",
            "BAT":  "🏏 Batsmen",
            "BOWL": "⚡ Bowlers",
            "ALR":  "⭐ All-Rounders",
        }

        embed = discord.Embed(
            title=f"📋 {ctx.author.display_name}'s Squad",
            description=f"**{len(squad)}/{MAX_SQUAD_SIZE} players**   •   Use **-elect** to set C / VC",
            color=0x1E8449
        )

        for cat, label in cat_labels.items():
            players = cats.get(cat, [])
            if not players:
                continue
            lines = []
            for pname, claimed_uid, team in players:
                flag  = _flag(team)
                emoji = _get_player_emoji(pname, self.bot)

                try:
                    u      = self.bot.get_user(claimed_uid)
                    handle = u.name if u else f"uid:{claimed_uid}"
                except Exception:
                    handle = f"uid:{claimed_uid}"

                e_str = f"{emoji} " if emoji else ""
                line  = f"{e_str}{pname} (@{handle}) {flag}"

                if pname == captain:
                    line = f"**(C) 2X** {e_str}**{pname}** (@{handle}) {flag}"
                elif pname == vc:
                    line = f"**(VC) 1.5X** {e_str}**{pname}** (@{handle}) {flag}"

                lines.append(line)

            embed.add_field(name=label, value="\n".join(lines), inline=False)

        footer_parts = []
        if captain:
            footer_parts.append(f"👑 Captain: {captain} (2X)")
        if vc:
            footer_parts.append(f"🥈 Vice-Captain: {vc} (1.5X)")
        if footer_parts:
            embed.set_footer(text="  |  ".join(footer_parts))

        await ctx.send(embed=embed)

    # ── -elect ───────────────────────────────────────────────
    @commands.command(name="elect", help="Elect Captain and Vice-Captain from your squad.")
    async def elect_command(self, ctx):
        user_id = ctx.author.id
        squad   = get_squad(user_id)

        if not squad:
            return await ctx.send(
                "❌ Your squad is empty! Use **-drop** to get players first."
            )
        if len(squad) < 2:
            return await ctx.send(
                "❌ You need at least **2 players** in your squad to elect a Captain and VC."
            )

        squad_names       = [r[0] for r in squad]
        captain, vc       = get_captains(user_id)

        embed = discord.Embed(
            title="👑 Elect Captain & Vice-Captain",
            description=(
                "Pick your **Captain (2X)** and **Vice-Captain (1.5X)** "
                "from the dropdowns, then hit **Confirm**.\n"
                "They cannot be the same player."
            ),
            color=0xFFD700
        )
        if captain or vc:
            embed.add_field(
                name="Current Leaders",
                value=(
                    f"👑 Captain: **{captain or '—'}**\n"
                    f"🥈 Vice-Captain: **{vc or '—'}**"
                ),
                inline=False
            )

        view = ElectView(user_id, squad_names, self.bot)
        await ctx.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(MiniPlayerGame(bot))
