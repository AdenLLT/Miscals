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
FANTASY_SCORING_VERSION = 2

RUN_MILESTONE_BONUSES = (
    (150, 30),
    (100, 20),
    (50, 10),
    (30, 5),
)
WICKET_HAUL_BONUSES = (
    (7, 30),
    (5, 20),
    (3, 10),
)


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
    c.execute('''CREATE TABLE IF NOT EXISTS minigame_fantasy_points (
        user_id      INTEGER,
        player_name  TEXT,
        total_points REAL DEFAULT 0,
        PRIMARY KEY (user_id, player_name)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS minigame_fantasy_points_log (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER,
        player_name   TEXT,
        match_id      INTEGER,
        points_earned REAL,
        timestamp     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS minigame_fantasy_sync (
        tournament_id   INTEGER PRIMARY KEY,
        scoring_version INTEGER NOT NULL,
        synced_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    try:
        c = conn.cursor()
        # Leadership is a one-time election.  Use INSERT OR IGNORE so an
        # already elected pair cannot be replaced by a stale menu interaction.
        c.execute(
            "INSERT OR IGNORE INTO minigame_captains (user_id, captain, vc) VALUES (?,?,?)",
            (user_id, captain, vc)
        )
        conn.commit()
    finally:
        conn.close()


def clear_invalid_captains(user_id: int):
    """Remove captain/vc if those players are no longer in the squad."""
    squad_names = {r[0] for r in get_squad(user_id)}
    cap, vc = get_captains(user_id)
    new_cap = cap if cap in squad_names else None
    new_vc  = vc  if vc  in squad_names else None
    if new_cap != cap or new_vc != vc:
        conn = _db()
        try:
            c = conn.cursor()
            c.execute(
                "UPDATE minigame_captains SET captain=?, vc=? WHERE user_id=?",
                (new_cap or '', new_vc or '', user_id)
            )
            conn.commit()
        finally:
            conn.close()


def _format_points(points) -> str:
    """Format whole fantasy points without an unnecessary decimal."""
    value = float(points or 0)
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


def get_squad_fantasy_breakdown(user_id: int):
    """Return every squad player and their cumulative fantasy contribution."""
    conn = _db()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT s.player_name, s.claimed_uid, s.role, s.team,
                   COALESCE(p.total_points, 0),
                   COALESCE(l.captain, ''), COALESCE(l.vc, '')
            FROM minigame_squads AS s
            LEFT JOIN minigame_fantasy_points AS p
              ON p.user_id = s.user_id AND p.player_name = s.player_name
            LEFT JOIN minigame_captains AS l ON l.user_id = s.user_id
            WHERE s.user_id = ?
            ORDER BY s.role, s.player_name
            """,
            (user_id,),
        )
        return c.fetchall()
    finally:
        conn.close()


def get_squad_fantasy_leaderboard():
    """Return all minigame squads ordered by their cumulative fantasy points."""
    conn = _db()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT s.user_id,
                   COALESCE(SUM(p.total_points), 0) AS total_points,
                   COUNT(*) AS player_count
            FROM minigame_squads AS s
            LEFT JOIN minigame_fantasy_points AS p
              ON p.user_id = s.user_id AND p.player_name = s.player_name
            GROUP BY s.user_id
            ORDER BY total_points DESC, s.user_id ASC
            """
        )
        return c.fetchall()
    finally:
        conn.close()


def reset_squad_fantasy_points():
    """Clear fantasy points while keeping every user's collected squad."""
    conn = _db()
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(DISTINCT user_id) FROM minigame_fantasy_points")
        users_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM minigame_fantasy_points_log")
        logs_count = c.fetchone()[0]
        c.execute("DELETE FROM minigame_fantasy_points")
        c.execute("DELETE FROM minigame_fantasy_points_log")
        conn.commit()
        return users_count, logs_count
    finally:
        conn.close()


def _milestone_bonus(runs: int, wickets: int) -> int:
    """Return the highest run and wicket milestone bonus for one performance."""
    run_bonus = next(
        (bonus for threshold, bonus in RUN_MILESTONE_BONUSES if runs >= threshold),
        0,
    )
    wicket_bonus = next(
        (bonus for threshold, bonus in WICKET_HAUL_BONUSES if wickets >= threshold),
        0,
    )
    return run_bonus + wicket_bonus


def calculate_squad_fantasy_points_for_match(matches, bot=None, stat_ids=None):
    """Award match points to every squad that contains a participating player.

    The base formula remains ``runs + (wickets * 20)``. Milestone bonuses are
    added once for the highest run milestone and highest wicket haul reached.
    Captain/VC multipliers apply only to that player's squad owner.
    """
    conn = _db()
    try:
        c = conn.cursor()
        user_ids = [int(match[0]) for match in matches]
        if user_ids:
            placeholders = ",".join("?" for _ in user_ids)
            c.execute(
                f"SELECT user_id, player_name FROM player_representatives "
                f"WHERE user_id IN ({placeholders})",
                user_ids,
            )
            names_by_user_id = dict(c.fetchall())
        else:
            names_by_user_id = {}

        player_records = []
        for index, match in enumerate(matches):
            values = list(match)
            stat_id = stat_ids[index] if stat_ids and index < len(stat_ids) else None
            user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out = map(
                int, values[:7]
            )
            player_name = names_by_user_id.get(user_id)
            if not player_name:
                continue
            impact = runs + (wickets * 20) + _milestone_bonus(runs, wickets)
            player_records.append((stat_id, player_name, impact))

        if not player_records:
            return {}

        player_names = {record[1] for record in player_records}
        c.execute(
            """
            SELECT s.user_id, s.player_name,
                   COALESCE(l.captain, ''), COALESCE(l.vc, '')
            FROM minigame_squads AS s
            LEFT JOIN minigame_captains AS l ON l.user_id = s.user_id
            WHERE s.player_name IN ({})
            """.format(",".join("?" for _ in player_names)),
            list(player_names),
        )
        squad_players = c.fetchall()

        logged_stat_ids = {
            (row[0], row[1], row[2])
            for row in c.execute(
                """
                SELECT user_id, player_name, match_id
                FROM minigame_fantasy_points_log
                WHERE match_id IS NOT NULL
                """
            )
        }

        points_awarded = {}
        for stat_id, player_name, impact in player_records:
            if impact <= 0:
                continue
            for squad_user_id, squad_player_name, captain, vc in squad_players:
                if squad_player_name != player_name:
                    continue
                if stat_id is not None and (
                    squad_user_id, player_name, stat_id
                ) in logged_stat_ids:
                    continue
                multiplier = (
                    2 if player_name == captain
                    else 1.5 if player_name == vc
                    else 1
                )
                points = impact * multiplier
                c.execute(
                    """
                    INSERT INTO minigame_fantasy_points (user_id, player_name, total_points)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, player_name) DO UPDATE SET
                        total_points = total_points + excluded.total_points
                    """,
                    (squad_user_id, player_name, points),
                )
                c.execute(
                    """
                    INSERT INTO minigame_fantasy_points_log
                        (user_id, player_name, match_id, points_earned)
                    VALUES (?, ?, ?, ?)
                    """,
                    (squad_user_id, player_name, stat_id, points),
                )
                if stat_id is not None:
                    logged_stat_ids.add((squad_user_id, player_name, stat_id))
                points_awarded[squad_user_id] = (
                    points_awarded.get(squad_user_id, 0) + points
                )

        conn.commit()
        return points_awarded
    finally:
        conn.close()


def backfill_squad_fantasy_points(tournament_id=None):
    """Populate squad fantasy totals from current-tournament match statistics."""
    # Keep this helper safe to call during startup migrations or from a
    # one-off maintenance script before the cog constructor has run.
    init_minigame_db()
    conn = _db()
    try:
        c = conn.cursor()
        if tournament_id is None:
            c.execute(
                """
                SELECT id FROM tournaments
                WHERE is_active=1 AND is_archived=0
                ORDER BY id DESC LIMIT 1
                """
            )
            row = c.fetchone()
            if not row:
                return {"status": "no_active_tournament", "awarded": 0}
            tournament_id = row[0]

        c.execute(
            "SELECT scoring_version FROM minigame_fantasy_sync WHERE tournament_id=?",
            (tournament_id,),
        )
        marker = c.fetchone()
        if marker and marker[0] >= FANTASY_SCORING_VERSION:
            return {"status": "already_synced", "awarded": 0}

        c.execute("DELETE FROM minigame_fantasy_points")
        c.execute("DELETE FROM minigame_fantasy_points_log")
        c.execute(
            """
            SELECT id, user_id, runs, balls_faced, runs_conceded,
                   balls_bowled, wickets, not_out
            FROM match_stats
            WHERE tournament_id=?
            ORDER BY id
            """,
            (tournament_id,),
        )
        stat_rows = c.fetchall()
        conn.commit()
    finally:
        conn.close()

    matches = [row[1:] for row in stat_rows]
    stat_ids = [row[0] for row in stat_rows]
    awarded = calculate_squad_fantasy_points_for_match(matches, stat_ids=stat_ids)

    conn = _db()
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO minigame_fantasy_sync (tournament_id, scoring_version)
            VALUES (?, ?)
            ON CONFLICT(tournament_id) DO UPDATE SET
                scoring_version=excluded.scoring_version,
                synced_at=CURRENT_TIMESTAMP
            """,
            (tournament_id, FANTASY_SCORING_VERSION),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "status": "synced",
        "tournament_id": tournament_id,
        "stat_rows": len(stat_rows),
        "owners": len(awarded),
        "awarded": sum(awarded.values()),
    }


class SquadFantasyLeaderboardView(View):
    """Paginated leaderboard for fantasy points earned by squad owners."""
    def __init__(self, ctx, bot, all_entries, items_per_page=10):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.bot = bot
        self.all_entries = all_entries
        self.items_per_page = items_per_page
        self.current_page = 0
        self.max_pages = max(
            1,
            (len(all_entries) + items_per_page - 1) // items_per_page,
        )
        self._refresh_buttons()

    def _refresh_buttons(self):
        self.children[0].disabled = self.current_page == 0
        self.children[1].disabled = self.current_page >= self.max_pages - 1

    def get_page_embed(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_entries = self.all_entries[start:end]

        lines = []
        for rank, (user_id, points, player_count) in enumerate(
            page_entries,
            start=start + 1,
        ):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "")
            member = self.ctx.guild.get_member(user_id)
            label = member.mention if member else f"<@{user_id}>"
            lines.append(
                f"{medal} **{rank}.** {label} — "
                f"**{_format_points(points)} pts** "
                f"({player_count} players)"
            )

        embed = discord.Embed(
            title="🏆 Squad Fantasy Leaderboard",
            description=(
                "Top users by fantasy points earned from players in their "
                "**-mysquad**.\n\n"
                + ("\n".join(lines) if lines else "No squads yet!")
            ),
            color=0xFFD700,
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.max_pages}")
        return embed

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.gray)
    async def previous_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message(
                "❌ Not your leaderboard!", ephemeral=True
            )
        if self.current_page == 0:
            return await interaction.response.send_message(
                "This is the first page.", ephemeral=True
            )
        self.current_page -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(
            embed=self.get_page_embed(),
            view=self,
        )

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.gray)
    async def next_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message(
                "❌ Not your leaderboard!", ephemeral=True
            )
        if self.current_page >= self.max_pages - 1:
            return await interaction.response.send_message(
                "This is the last page.", ephemeral=True
            )
        self.current_page += 1
        self._refresh_buttons()
        await interaction.response.edit_message(
            embed=self.get_page_embed(),
            view=self,
        )


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
        existing_captain, existing_vc = get_captains(self.user_id)
        if existing_captain and existing_vc:
            return await interaction.response.send_message(
                "🔒 Your Captain and Vice-Captain choices are already locked.",
                ephemeral=True,
            )
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
        saved_captain, saved_vc = get_captains(self.user_id)
        cap_emoji  = _get_player_emoji(self.captain_choice, self.bot)
        vc_emoji   = _get_player_emoji(self.vc_choice,      self.bot)
        cap_line   = f"{cap_emoji} **{self.captain_choice}**" if cap_emoji else f"**{self.captain_choice}**"
        vc_line    = f"{vc_emoji} **{self.vc_choice}**"      if vc_emoji  else f"**{self.vc_choice}**"
        embed = discord.Embed(
            title="✅ Leadership Elected!",
            description=(
                f"👑 **Captain (2X):** {cap_line}\n"
                f"🥈 **Vice-Captain (1.5X):** {vc_line}\n\n"
                "🔒 These choices are now locked."
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
        # Prevent concurrent -drop invocations for the same user from
        # passing the squad-size check before either one is persisted.
        self._drop_in_progress = set()

    # ── -drop ────────────────────────────────────────────────
    @commands.command(name="drop", help="Drop a random claimed player card into your squad (max 15).")
    async def drop_command(self, ctx):
        user_id = ctx.author.id

        if user_id in self._drop_in_progress:
            return await ctx.send(
                "⏳ Your previous `-drop` is still being processed. "
                "Please wait until the new player has been added to your squad."
            )

        self._drop_in_progress.add(user_id)
        try:
            # Squad cap check. This happens inside the in-progress guard so
            # concurrent commands cannot all pass before an insert occurs.
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

            # Persist before releasing the in-progress guard.
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
        finally:
            self._drop_in_progress.discard(user_id)

    @commands.command(
        name="removeabove15squadplayers",
        help="[ADMIN] Remove excess players from squads larger than 15"
    )
    @commands.has_permissions(administrator=True)
    async def remove_above_15_squad_players_command(self, ctx):
        """Keep the oldest 15 players in every oversized squad."""
        conn = _db()
        c = conn.cursor()
        c.execute("""
            SELECT user_id, COUNT(*) AS squad_size
            FROM minigame_squads
            GROUP BY user_id
            HAVING COUNT(*) > ?
            ORDER BY squad_size DESC, user_id
        """, (MAX_SQUAD_SIZE,))
        oversized = c.fetchall()

        removed_total = 0
        removed_by_user = []

        for user_id, squad_size in oversized:
            c.execute("""
                SELECT player_name
                FROM minigame_squads
                WHERE user_id=?
                ORDER BY datetime(added_at) ASC, rowid ASC
            """, (user_id,))
            squad_names = [row[0] for row in c.fetchall()]
            excess_names = squad_names[MAX_SQUAD_SIZE:]
            if not excess_names:
                continue

            placeholders = ",".join("?" for _ in excess_names)
            c.execute(
                f"DELETE FROM minigame_squads "
                f"WHERE user_id=? AND player_name IN ({placeholders})",
                (user_id, *excess_names)
            )
            removed_count = c.rowcount
            removed_total += removed_count
            removed_by_user.append((user_id, squad_size, removed_count))

            # Do not leave an elected captain/VC pointing at a removed player.
            c.execute(
                "SELECT captain, vc FROM minigame_captains WHERE user_id=?",
                (user_id,)
            )
            elected = c.fetchone()
            if elected:
                remaining_names = set(squad_names[:MAX_SQUAD_SIZE])
                captain_name = elected[0] if elected[0] in remaining_names else ""
                vc_name = elected[1] if elected[1] in remaining_names else ""
                c.execute(
                    "UPDATE minigame_captains SET captain=?, vc=? WHERE user_id=?",
                    (captain_name, vc_name, user_id)
                )

        conn.commit()
        conn.close()

        if not removed_by_user:
            return await ctx.send(
                f"✅ No squads exceeded **{MAX_SQUAD_SIZE}** players."
            )

        details = []
        for user_id, old_size, removed_count in removed_by_user[:20]:
            member = ctx.guild.get_member(user_id)
            label = member.mention if member else f"`{user_id}`"
            details.append(
                f"• {label}: **{old_size} → {MAX_SQUAD_SIZE}** "
                f"({removed_count} removed)"
            )
        if len(removed_by_user) > 20:
            details.append(f"• …and {len(removed_by_user) - 20} more squads")

        embed = discord.Embed(
            title="🧹 Oversized Squad Cleanup Complete",
            description="\n".join(details),
            color=0x00A86B
        )
        embed.add_field(
            name="Total Removed",
            value=f"**{removed_total}** excess player(s)",
            inline=False
        )
        embed.set_footer(text=f"Cleaned by {ctx.author}")
        await ctx.send(embed=embed)

    def _build_fantasy_embed(self, ctx, squad, fantasy_rows, title):
        captain, vc = get_captains(ctx.author.id)
        total_points = sum(float(row[4] or 0) for row in fantasy_rows)

        embed = discord.Embed(
            title=title,
            description=(
                f"✅ **Total Fantasy Points:** {_format_points(total_points)}\n"
                f"**Squad:** {len(squad)}/{MAX_SQUAD_SIZE} players"
            ),
            color=0xFFD700,
        )

        lines = []
        for pname, claimed_uid, role, team, points, row_captain, row_vc in fantasy_rows:
            emoji = _get_player_emoji(pname, self.bot)
            flag = _flag(team)
            marker = " 👑 **C 2X**" if pname == captain else " 🥈 **VC 1.5X**" if pname == vc else ""
            prefix = f"{emoji} " if emoji else ""
            lines.append(
                f"{prefix}**{pname}** {flag}{marker} — "
                f"**{_format_points(points)} pts**"
            )

        if lines:
            # Discord caps each embed field value at 1024 characters. A full
            # 15-player squad can exceed that once custom emojis and markers
            # are included, so split contributions across safe-sized fields.
            chunks = []
            current = []
            current_length = 0
            for line in lines:
                extra_length = len(line) + (1 if current else 0)
                if current and current_length + extra_length > 1000:
                    chunks.append(current)
                    current = []
                    current_length = 0
                current.append(line)
                current_length += len(line) + (1 if len(current) > 1 else 0)
            if current:
                chunks.append(current)

            for index, chunk in enumerate(chunks, start=1):
                field_name = (
                    "Player Contributions"
                    if len(chunks) == 1
                    else f"Player Contributions ({index}/{len(chunks)})"
                )
                embed.add_field(
                    name=field_name,
                    value="\n".join(chunk),
                    inline=False,
                )
        if captain or vc:
            embed.set_footer(
                text=(
                    f"👑 Captain: {captain or '—'} (2X)  •  "
                    f"🥈 Vice-Captain: {vc or '—'} (1.5X)"
                )
            )
        return embed

    # ── -mysquad ─────────────────────────────────────────────
    @commands.command(name="mysquad", aliases=["squad"], help="View your mini player squad.")
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

        embed = self._build_fantasy_embed(
            ctx,
            squad,
            get_squad_fantasy_breakdown(user_id),
            f"📋 {ctx.author.display_name}'s Squad",
        )
        await ctx.send(embed=embed)

    # ── -fantasy ──────────────────────────────────────────────
    @commands.command(name="fantasy", help="View your squad's fantasy points.")
    async def fantasy_command(self, ctx):
        squad = get_squad(ctx.author.id)
        if not squad:
            return await ctx.send(
                "❌ Your squad is empty! Use **-drop** to get players first."
            )

        fantasy_rows = get_squad_fantasy_breakdown(ctx.author.id)
        embed = self._build_fantasy_embed(
            ctx,
            squad,
            fantasy_rows,
            f"🏆 {ctx.author.display_name}'s Fantasy Points",
        )
        await ctx.send(embed=embed)

    # ── -fantasylb ────────────────────────────────────────────
    @commands.command(name="fantasylb", aliases=["flb"], help="View the squad fantasy leaderboard.")
    async def fantasy_leaderboard_command(self, ctx):
        entries = get_squad_fantasy_leaderboard()
        if not entries:
            return await ctx.send(
                "❌ No squads yet! Use **-drop** to collect players first."
            )

        view = SquadFantasyLeaderboardView(ctx, self.bot, entries)
        await ctx.send(embed=view.get_page_embed(), view=view)

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
        if captain and vc:
            return await ctx.send(
                f"🔒 Your Captain (**{captain}**) and Vice-Captain (**{vc}**) "
                "choices are already locked and cannot be changed."
            )

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
