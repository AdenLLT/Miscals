from keep_alive import keep_alive
from cricket_stats import ensure_card_in_cache, startup_sync_card_cache
import discord
import os
import json
import hashlib
import re
import random
import sqlite3
import pickle
import asyncio
import time
import io
import math
import pytz
from discord import app_commands
from datetime import datetime, timedelta
from typing import Dict, Optional
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import aiohttp
import tempfile
from discord.ui import Select, View
from discord.ext import commands, tasks
from discord.ext.commands.cooldowns import BucketType

# SQLite is shared by the bot's cogs and by background tasks.  Keep the
# existing lightweight connection style, but make every connection wait for
# short-lived writer contention instead of failing immediately.
_sqlite_connect = sqlite3.connect
_SQLITE_RETRY_ATTEMPTS = 5
_SQLITE_RETRY_DELAYS = (0.05, 0.15, 0.35, 0.75, 1.5)


def _is_sqlite_lock_error(error):
    return isinstance(error, sqlite3.OperationalError) and any(
        marker in str(error).lower()
        for marker in ("database is locked", "database table is locked")
    )


def _retry_sqlite_operation(operation, label):
    for attempt in range(_SQLITE_RETRY_ATTEMPTS):
        try:
            return operation()
        except sqlite3.OperationalError as error:
            if not _is_sqlite_lock_error(error) or attempt == _SQLITE_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(_SQLITE_RETRY_DELAYS[attempt])
    raise RuntimeError(f"SQLite retry loop exited unexpectedly: {label}")


class _RetryCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        return _retry_sqlite_operation(
            lambda: super(_RetryCursor, self).execute(sql, parameters),
            "cursor.execute",
        )

    def executemany(self, sql, parameters):
        return _retry_sqlite_operation(
            lambda: super(_RetryCursor, self).executemany(sql, parameters),
            "cursor.executemany",
        )


class _RetryConnection(sqlite3.Connection):
    def cursor(self, factory=None):
        return super().cursor(factory or _RetryCursor)

    def execute(self, sql, parameters=()):
        return _retry_sqlite_operation(
            lambda: super(_RetryConnection, self).execute(sql, parameters),
            "connection.execute",
        )

    def executemany(self, sql, parameters):
        return _retry_sqlite_operation(
            lambda: super(_RetryConnection, self).executemany(sql, parameters),
            "connection.executemany",
        )

    def commit(self):
        return _retry_sqlite_operation(
            lambda: super(_RetryConnection, self).commit(),
            "connection.commit",
        )


def _connect_sqlite(*args, **kwargs):
    kwargs.setdefault("timeout", 30.0)
    kwargs.setdefault("factory", _RetryConnection)
    conn = _sqlite_connect(*args, **kwargs)
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


# All cogs import the same sqlite3 module object, so this also protects their
# existing sqlite3.connect(...) calls without requiring a risky broad rewrite.
sqlite3.connect = _connect_sqlite

intents = discord.Intents.default()
intents.members = True
intents.presences = True 
intents.message_content = True
intents.voice_states = True  # Required for voice
intents.guilds = True  # Required for voice
mydb = sqlite3.connect("players.db")
crsr = mydb.cursor()
mydb.execute("PRAGMA journal_mode = WAL")
mydb.execute("PRAGMA synchronous = NORMAL")
mydb.commit()

DEFAULT_PLAYER_IMAGE_URL = "https://i.ibb.co/GvWNRX0K/Untitled-design-4.png"

DB_BACKUP_CHANNEL_ID = 1511452654906114139
SQUAD_CACHE_CHANNEL_ID = 1480246123598843974
SQUAD_CACHE_OWNER_ID = 765965975761715241

async def restore_db_from_channel():
    """Download the last players.db attachment from the backup channel and use it."""
    channel = bot.get_channel(DB_BACKUP_CHANNEL_ID)
    if not channel:
        print("❌ DB backup channel not found.")
        return
    async for message in channel.history(limit=200):
        for attachment in message.attachments:
            if attachment.filename == 'players.db':
                async with aiohttp.ClientSession() as session:
                    async with session.get(attachment.url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            with open('players.db', 'wb') as f:
                                f.write(data)
                            global mydb, crsr
                            mydb.close()
                            mydb = sqlite3.connect("players.db")
                            crsr = mydb.cursor()
                            print("✅ Restored players.db from backup channel.")
                            return
    print("ℹ️ No players.db backup found in backup channel — using local file.")

async def backup_db_to_channel():
    """Send the current players.db to the backup channel."""
    backup_path = None
    try:
        channel = bot.get_channel(DB_BACKUP_CHANNEL_ID)
        if channel:
            # Use SQLite's online backup API instead of copying the main file
            # or forcing a WAL TRUNCATE checkpoint. Both of those approaches
            # can omit committed WAL data or contend with live writers.
            backup_path = await asyncio.to_thread(_create_consistent_backup)
            await channel.send(file=discord.File(backup_path, filename='players.db'))
    except Exception as e:
        print(f"[backup] DB backup failed (non-critical): {e}")
    finally:
        if backup_path:
            try:
                os.unlink(backup_path)
            except OSError:
                pass


def _create_consistent_backup():
    fd, backup_path = tempfile.mkstemp(prefix="players-backup-", suffix=".db")
    os.close(fd)
    source = sqlite3.connect("players.db", timeout=30.0)
    target = sqlite3.connect(backup_path, timeout=30.0)
    try:
        source.backup(target)
        target.commit()
        return backup_path
    finally:
        target.close()
        source.close()

class MyHelp(commands.MinimalHelpCommand):
    async def send_pages(self):
        destination = self.get_destination()
        for page in self.paginator.pages:
            emby = discord.Embed(description=page, color=discord.Color.blue())
            await destination.send(embed=emby)

bot = commands.Bot(
    command_prefix="-",
    description="**STATS IN DEVELOPMENT**",
    intents=intents,
    case_insensitive=True,
    strip_after_prefix=True,
    help_command=MyHelp()
)

ALLOWED_GUILD_ID = 1451591563078533292
ALLOWED_GUILD_OBJ = discord.Object(id=ALLOWED_GUILD_ID)

STAFF_ROLE_ID = 1452028308735922339

def is_staff_or_admin():
    """Passes if the user has administrator permission OR the staff role."""
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        if any(r.id == STAFF_ROLE_ID for r in ctx.author.roles):
            return True
        raise commands.MissingPermissions(['administrator'])
    return commands.check(predicate)

def is_staff_or_admin_slash():
    """app_commands check: passes if user has administrator permission OR the staff role."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        if any(r.id == STAFF_ROLE_ID for r in interaction.user.roles):
            return True
        raise app_commands.MissingPermissions(['administrator'])
    return app_commands.check(predicate)

@bot.check
async def only_allowed_guild(ctx):
    return ctx.guild is not None and ctx.guild.id == ALLOWED_GUILD_ID

async def only_allowed_guild_slash(interaction: discord.Interaction) -> bool:
    return interaction.guild_id == ALLOWED_GUILD_ID


# CommandTree.interaction_check is an overridable method, not a decorator.
# Assigning the coroutine directly avoids creating an un-awaited coroutine
# during module initialization and ensures every slash command is checked.
bot.tree.interaction_check = only_allowed_guild_slash

@bot.event
async def on_ready():
    global elite_players
    await restore_db_from_channel()
    init_db()
    init_nicknames_db()
    _init_embeds_table()
    elite_players = load_elite_players()
    # Load the stats cog
    await bot.load_extension('cricket_stats')
    await bot.load_extension('matchupdates')
    await bot.load_extension('tournament')
    await bot.load_extension('series')
    await bot.load_extension('playerlife')
    await bot.load_extension('miniplayergame')
    from miniplayergame import backfill_squad_fantasy_points
    try:
        fantasy_sync = await asyncio.to_thread(backfill_squad_fantasy_points)
        print(f"✅ Squad fantasy sync: {fantasy_sync}")
    except Exception as exc:
        print(f"❌ Squad fantasy sync failed: {exc}")
    # Keep this bot's commands guild-scoped. Remove the old global
    # /matchtime registration so Discord cannot show both a global and a
    # guild copy of that command.
    matchtime_command = bot.tree.remove_command("matchtime")
    bot.tree.clear_commands(guild=ALLOWED_GUILD_OBJ)
    bot.tree.copy_global_to(guild=ALLOWED_GUILD_OBJ)
    if matchtime_command:
        bot.tree.add_command(matchtime_command, guild=ALLOWED_GUILD_OBJ)

    # Sync the global tree after removing the stale global command, then sync
    # the complete current command set to the allowed guild.
    await bot.tree.sync()
    synced_commands = await bot.tree.sync(guild=ALLOWED_GUILD_OBJ)
    print(f"✅ Synced {len(synced_commands)} guild slash commands.")
    await bot.change_presence(activity=discord.Game(name="ODI WC26"))
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is ready! Prefix: .')
    await backup_db_to_channel()
    # Ensure every claimed user has a card in the cache channel
    asyncio.get_event_loop().create_task(startup_sync_card_cache(bot))
    # Start background feed pre-generation (100 posts on startup, 30/hr after)
    from playerlife import start_feed_background_gen
    from commentary import start_commentary
    start_feed_background_gen(bot)
    start_commentary(bot)

_last_backup_ts: float = 0.0

@bot.after_invoke
async def after_command_backup(ctx):
    global _last_backup_ts
    import time as _t
    now = _t.time()
    if now - _last_backup_ts < 300:   # at most once every 5 minutes
        return
    _last_backup_ts = now
    await backup_db_to_channel()

class ConfirmationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.confirmed = False

    @discord.ui.button(label="✅ Confirm Team", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        self.stop()
        await interaction.response.defer()


# Add the reset command for admins:

@bot.command(name="resetfantasysquads", aliases=["rfs"], help="[ADMIN] Reset all fantasy teams")
@is_staff_or_admin()
async def resetfantasysquads_command(ctx):
    """Reset squad fantasy points without deleting collected squads."""

    # Confirmation
    confirm_embed = discord.Embed(
        title="⚠️ Confirm Fantasy Reset",
        description=(
            "Are you sure you want to **reset all squad fantasy points**?\n\n"
            "This will:\n"
            "• Keep every player's `-mysquad` intact\n"
            "• Reset all fantasy points to 0\n"
            "• Clear all fantasy points logs\n\n"
            "**This action cannot be undone!**"
        ),
        color=0xFF0000
    )

    confirm_msg = await ctx.send(embed=confirm_embed)
    await confirm_msg.add_reaction("✅")
    await confirm_msg.add_reaction("❌")

    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == confirm_msg.id

    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=30.0, check=check)
    except asyncio.TimeoutError:
        await confirm_msg.edit(embed=discord.Embed(
            title="❌ Reset Cancelled",
            description="Confirmation timed out.",
            color=0x808080
        ))
        await confirm_msg.clear_reactions()
        return

    if str(reaction.emoji) == "❌":
        await confirm_msg.edit(embed=discord.Embed(
            title="❌ Reset Cancelled",
            description="Squad fantasy points were not reset.",
            color=0x808080
        ))
        await confirm_msg.clear_reactions()
        return

    # User confirmed - proceed with reset
    await confirm_msg.clear_reactions()

    from miniplayergame import reset_squad_fantasy_points
    users_count, logs_count = reset_squad_fantasy_points()

    # Create success embed
    success_embed = discord.Embed(
        title="✅ Fantasy Reset Complete",
        description="All squad fantasy points have been reset. Collected squads were kept.",
        color=0x00FF00
    )

    success_embed.add_field(
        name="Deleted",
        value=f"**{users_count}** users with points\n**{logs_count}** points log entries",
        inline=False
    )

    success_embed.set_footer(text=f"Reset by {ctx.author.name}")
    success_embed.timestamp = discord.utils.utcnow()

    await confirm_msg.edit(embed=success_embed)

@app_commands.describe(
    message="The message content to send",
    image="Optional image to attach"
)
@is_staff_or_admin_slash()
async def sendmsg(interaction: discord.Interaction, message: str, image: Optional[discord.Attachment] = None):
    # Hide the slash command response (ephemeral)
    await interaction.response.send_message("✅ Message sent!", ephemeral=True)

    # Send the message separately in the same channel
    if image:
        file = await image.to_file()
        await interaction.channel.send(content=message, file=file)
    else:
        await interaction.channel.send(content=message)

@bot.command(name="dm", help="[OWNER] Send a DM to a user from the bot")
async def dm_user(ctx, member: discord.Member, *, message: str):
    if ctx.author.id != 765965975761715241:
        return
    """Send a direct message to a user as the bot"""
    try:
        await member.send(message)
        await ctx.send(f"✅ Message sent to **{member.display_name}**.", delete_after=5)
    except discord.Forbidden:
        await ctx.send(f"❌ Could not DM **{member.display_name}** — they may have DMs disabled.")
    except Exception as e:
        await ctx.send(f"❌ Failed to send DM: {e}")

TEAM_ROLE_IDS = {
    "india": 1460376137594044567, "pakistan": 1460376138755866644,
    "australia": 1460376139611640025, "england": 1460376141314654424,
    "new zealand": 1460376142342000762, "south africa": 1460376143633846527,
    "west indies": 1460376148751028408, "sri lanka": 1460376147715166282,
    "bangladesh": 1460376144862908523, "afghanistan": 1460376146163273739,
    "netherlands": 1460376154480312370, "scotland": 1460376151795961897,
    "ireland": 1460376149908525191, "zimbabwe": 1460376157668245545,
    "uae": 1460376158985130114, "canada": 1460376154958725152,
    "usa": 1460376156250570824,
    "italy": 1513096652842467328, "nepal": 1513096680835125398,
    "namibia": 1513096608063950878, "hong kong": 1513236745527889951,
    "oman": 1513236895595757768, "papua new guinea": 1513237053935194262,
    "uganda": 1513237221560287312, "malaysia": 1513238128482320454,
    "spain": 1513238260502233198, "germany": 1513238268777595073,
    "japan": 1513238484075282432, "portugal": 1513238487707549958,
    "denmark": 1513238490723385466
}


def member_has_team_role(member):
    """Return whether Discord shows this member as having a claimed team."""
    team_role_ids = set(TEAM_ROLE_IDS.values())
    return any(role.id in team_role_ids for role in member.roles)


def get_leadership_teams(user_id):
    """Return teams for which a Discord user is the current captain or VC."""
    conn = sqlite3.connect('players.db')
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT team_name FROM team_captains WHERE user_id = ?
            UNION
            SELECT team_name FROM team_vice_captains WHERE user_id = ?
            """,
            (user_id, user_id),
        )
        return [row[0] for row in c.fetchall()]
    finally:
        conn.close()


@bot.command(name="call", help="[CAPTAIN/VC] Alert your team about a World Cup match")
@commands.cooldown(1, 30, BucketType.user)
async def call_command(ctx):
    """Ping the team role and DM all non-bot members of the team."""
    author_team_keys = {
        team_key
        for team_key, role_id in TEAM_ROLE_IDS.items()
        if any(role.id == role_id for role in ctx.author.roles)
    }
    leadership_teams = await asyncio.to_thread(
        get_leadership_teams,
        ctx.author.id,
    )
    leadership_team_keys = {team_name.lower() for team_name in leadership_teams}
    team_key = next(
        (team_key for team_key in author_team_keys if team_key in leadership_team_keys),
        None,
    )

    if not team_key:
        await ctx.send("❌ Only a team's captain or vice-captain can use `-call`.")
        return

    team_role = ctx.guild.get_role(TEAM_ROLE_IDS[team_key])
    if not team_role:
        await ctx.send(f"❌ Could not find the Discord role for **{team_key.title()}**.")
        return

    # This channel mention renders as a clickable #channel link in the DM.
    call_embed = discord.Embed(
        title="Captain's Call 🔔 🧢",
        description=f"‼️ Join World Cup Match: {ctx.channel.mention}",
        color=get_team_color(team_key),
    )

    await ctx.send(
        team_role.mention,
        allowed_mentions=discord.AllowedMentions(
            roles=True,
            users=False,
            everyone=False,
        ),
    )

    members = [member for member in team_role.members if not member.bot]
    failed = 0
    for member in members:
        try:
            await member.send(embed=call_embed)
        except (discord.Forbidden, discord.HTTPException):
            failed += 1

    if failed:
        await ctx.send(f"⚠️ I couldn't DM **{failed}** team member(s).")


@bot.command(name="dmteam", help="[OWNER] DM everyone on a team")
async def dmteam(ctx, team_name: str, *, message: str):
    if ctx.author.id != 765965975761715241:
        return
    """Send a DM to every player on the given team"""
    role_id = TEAM_ROLE_IDS.get(team_name.lower())
    if not role_id:
        teams_list = ", ".join(t.title() for t in TEAM_ROLE_IDS)
        await ctx.send(f"❌ Team **{team_name}** not found.\nAvailable teams: {teams_list}")
        return

    role = ctx.guild.get_role(role_id)
    if not role:
        await ctx.send(f"❌ Could not find the role for **{team_name}** in this server.")
        return

    members = [m for m in role.members if not m.bot]
    if not members:
        await ctx.send(f"❌ No members found with the **{role.name}** role.")
        return

    status_msg = await ctx.send(f"📨 Sending DMs to {len(members)} player(s) on **{role.name}**...")

    sent = 0
    failed = 0
    for member in members:
        try:
            await member.send(message)
            sent += 1
        except discord.Forbidden:
            failed += 1
        except Exception:
            failed += 1

    result = f"✅ Sent to **{sent}** player(s)"
    if failed:
        result += f", ❌ **{failed}** had DMs disabled"
    await status_msg.edit(content=result)

@bot.command(name="quarterfinals")
async def quarterfinals(ctx):
    embed = discord.Embed(
        title="Pakistan's CWC26",
        description=(
            "╭─── ⋅ 🏆 ⋅ ───╮\n\n"
            "🇦🇫 **Afghanistan** VS **South Africa** 🇿🇦\n"
            "───────────────\n"
            "🇧🇩 **Bangladesh** VS **India** 🇮🇳\n"
            "───────────────\n"
            "🏴󠁧󠁢󠁳󠁣󠁴󠁿 **Scotland** VS **Netherlands** 🇳🇱\n"
            "───────────────\n"
            "🇱🇰 **Sri Lanka** VS **TBD #8** 🔍\n\n"
            "╰─── ⋅ 🏆 ⋅ ───╯"
        ),
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text="CWC26 Quarter Finals")
    if ctx.guild and ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)
    await ctx.send(embed=embed)

@bot.listen()
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandInvokeError):
        error = error.original
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(
            f"⏳ Please wait **{error.retry_after:.1f}s** before using that command again."
        )
        return
    if _is_sqlite_lock_error(error):
        command_name = getattr(ctx.command, "qualified_name", "unknown")
        print(f"[SQLite] lock persisted after retries in command={command_name}: {error!r}")
        await ctx.send("⏳ The database is busy finishing another update. Please try again in a moment.")
        return
    await ctx.send(f"❌ Error: {error}")

@bot.listen('on_message')
async def log_dm_messages(message):
    if message.author.bot:
        return
    if isinstance(message.channel, discord.DMChannel):
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute(
            "INSERT INTO dm_logs (user_id, username, content) VALUES (?, ?, ?)",
            (message.author.id, str(message.author), message.content or '[no text content]')
        )
        conn.commit()
        conn.close()

@bot.command(name="dmfetch", help="[OWNER] Fetch last 5 DMs a user sent to the bot")
async def dmfetch(ctx, member: discord.Member):
    if ctx.author.id != 765965975761715241:
        return
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(
        "SELECT content, sent_at FROM dm_logs WHERE user_id = ? ORDER BY sent_at DESC LIMIT 5",
        (member.id,)
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        await ctx.send(f"❌ No DM history found for **{member.display_name}**.")
        return

    embed = discord.Embed(
        title=f"📬 Last DMs from {member.display_name}",
        color=0x5865F2
    )
    for i, (content, sent_at) in enumerate(reversed(rows), 1):
        embed.add_field(
            name=f"Message {i} — {sent_at}",
            value=content[:1024],
            inline=False
        )
    await ctx.author.send(embed=embed)


def init_db():
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS player_representatives
                 (player_name TEXT PRIMARY KEY, user_id INTEGER, username TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS match_stats
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  runs INTEGER,
                  balls_faced INTEGER,
                  runs_conceded INTEGER,
                  balls_bowled INTEGER,
                  wickets INTEGER,
                  not_out INTEGER,
                  match_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Keep leaderboard scopes separate without changing the existing career
    # stats table.  Older rows remain unscoped; new rows are tagged by the
    # command that records them.
    c.execute("PRAGMA table_info(match_stats)")
    match_stats_columns = {row[1] for row in c.fetchall()}
    if 'tournament_id' not in match_stats_columns:
        c.execute("ALTER TABLE match_stats ADD COLUMN tournament_id INTEGER")
    if 'series_id' not in match_stats_columns:
        c.execute("ALTER TABLE match_stats ADD COLUMN series_id INTEGER")
    if 'include_in_lbi' not in match_stats_columns:
        c.execute(
            "ALTER TABLE match_stats ADD COLUMN include_in_lbi INTEGER DEFAULT 1"
        )

    # ADD THIS NEW TABLE FOR CAPTAINS
    c.execute('''CREATE TABLE IF NOT EXISTS team_captains
                 (team_name TEXT PRIMARY KEY, player_name TEXT, user_id INTEGER, username TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS team_vice_captains
                 (team_name TEXT PRIMARY KEY, player_name TEXT, user_id INTEGER, username TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS old_representatives
     (id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER,
      player_name TEXT,
      removed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS dm_logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  username TEXT,
                  content TEXT,
                  sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS invite_counts
                 (user_id INTEGER,
                  guild_id INTEGER,
                  invite_uses INTEGER DEFAULT 0,
                  PRIMARY KEY (user_id, guild_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS stat_overrides
                 (user_id INTEGER PRIMARY KEY,
                  total_runs INTEGER,
                  total_balls_faced INTEGER,
                  times_not_out INTEGER,
                  matches_played INTEGER,
                  total_runs_conceded INTEGER,
                  total_balls_bowled INTEGER,
                  total_wickets INTEGER)''')
    conn.commit()
    conn.close()

def init_nicknames_db():
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS user_nicknames
                 (user_id INTEGER PRIMARY KEY, 
                  original_nickname TEXT,
                  custom_nickname TEXT,
                  last_synced TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()


# Load players from JSON
def load_players():
    try:
        with open('players.json', 'r', encoding='utf-8') as f:
            teams_data = json.load(f)

        # Keep every player image consumer consistent. Missing image values
        # may be stored as null, blank text, or NIL in players.json.
        for team_data in teams_data:
            for player in team_data.get('players', []):
                player['image'] = get_player_image_url(player.get('image'))

        return teams_data
    except json.JSONDecodeError as e:
        print(f"❌ Error loading players.json at line {e.lineno}, column {e.colno}")
        print(f"Error message: {e.msg}")
        print(f"Please check your players.json file for invalid characters at position {e.pos}")
        # Try to read and show problematic line
        with open('players.json', 'r', encoding='utf-8') as f:
            lines = f.readlines()
            if e.lineno <= len(lines):
                print(f"Problematic line: {lines[e.lineno-1]}")
        return []
    except FileNotFoundError:
        print("❌ players.json file not found!")
        return []

# Get team color based on team name
def get_team_color(team_name):
    colors = {
        "India": 0x0066CC,  # Blue
        "Pakistan": 0x006400,  # Dark Green
        "Australia": 0xFFD700,  # Gold
        "England": 0x012169,  # Navy Blue
        "New Zealand": 0x000000,  # Black
        "South Africa": 0x006B3F,  # Green
        "West Indies": 0x7B0041,  # Maroon
        "Sri Lanka": 0x003DA5,  # Blue
        "Bangladesh": 0x006A4E,  # Green
        "Afghanistan": 0x5363ED,  # Red
        "Netherlands": 0xFF3600,
        "Scotland": 0xA100F2,
        "Ireland": 0x9DFF2E,
        "Zimbabwe": 0xFF2121,
        "UAE": 0xFC4444,
        "Canada": 0xFF0000,
        "USA": 0x080026,
        "Italy": 0x009246,
        "Nepal": 0xDC143C,
        "Namibia": 0x003580,
        "Hong Kong": 0xDE2910,
        "Oman": 0x009A44,
        "Papua New Guinea": 0xBF0A30,
        "Uganda": 0xFCDC04,
        "Malaysia": 0xCC0001,
        "Spain": 0xAA151B,
        "Germany": 0xDD0000,
        "Japan": 0xBC002D,
        "Portugal": 0x1A7A3C,
        "Denmark": 0xC60C30
    }
    return colors.get(team_name, 0x808080)  # Default gray

# Get team flag emoji URL (for thumbnails)
def get_team_flag_url(team_name):
    # Using Twemoji CDN for flag images
    flag_codes = {
        "India": "1f1ee-1f1f3",  # 🇮🇳
        "Pakistan": "1f1f5-1f1f0",  # 🇵🇰
        "Australia": "1f1e6-1f1fa",  # 🇦🇺
        "England": "1f3f4-e0067-e0062-e0065-e006e-e0067-e007f",  # 🏴󠁧󠁢󠁥󠁮󠁧󠁿
        "New Zealand": "1f1f3-1f1ff",  # 🇳🇿
        "South Africa": "1f1ff-1f1e6",  # 🇿🇦
        "West Indies": "1f3dd",  # 🏝️
        "Sri Lanka": "1f1f1-1f1f0",  # 🇱🇰
        "Bangladesh": "1f1e7-1f1e9",  # 🇧🇩
        "Afghanistan": "1f1e6-1f1eb",  # 🇦🇫
        "Netherlands": "1f1f3-1f1f1",  # 🇳🇱
        "Scotland": "1f3f4-e0067-e0062-e0073-e0063-e0074-e007f",  # 🏴󠁧󠁢󠁳󠁣󠁴󠁿
        "Ireland": "1f1ee-1f1ea",  # 🇮🇪
        "Zimbabwe": "1f1ff-1f1fc",  # 🇿🇼
        "UAE": "1f1e6-1f1ea",  # 🇦🇪
        "Canada": "1f1e8-1f1e6",  # 🇨🇦
        "USA": "1f1fa-1f1f8",  # 🇺🇸
        "Italy": "1f1ee-1f1f9",  # 🇮🇹
        "Nepal": "1f1f3-1f1f5",  # 🇳🇵
        "Namibia": "1f1f3-1f1e6",  # 🇳🇦
        "Hong Kong": "1f1ed-1f1f0",  # 🇭🇰
        "Oman": "1f1f4-1f1f2",  # 🇴🇲
        "Papua New Guinea": "1f1f5-1f1ec",  # 🇵🇬
        "Uganda": "1f1fa-1f1ec",  # 🇺🇬
        "Malaysia": "1f1f2-1f1fe",  # 🇲🇾
        "Spain": "1f1ea-1f1f8",  # 🇪🇸
        "Germany": "1f1e9-1f1ea",  # 🇩🇪
        "Japan": "1f1ef-1f1f5",  # 🇯🇵
        "Portugal": "1f1f5-1f1f9",  # 🇵🇹
        "Denmark": "1f1e9-1f1f0"  # 🇩🇰
    }
    code = flag_codes.get(team_name)
    if code:
        return f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{code}.png"
    return None

# Get team flag emoji
def get_team_flag(team_name):
    flags = {
        "India": "🇮🇳",
        "Pakistan": "🇵🇰",
        "Australia": "🇦🇺",
        "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
        "New Zealand": "🇳🇿",
        "South Africa": "🇿🇦",
        "West Indies": "🏝️",
        "Sri Lanka": "🇱🇰",
        "Bangladesh": "🇧🇩",
        "Afghanistan": "🇦🇫",
        "Netherlands": "🇳🇱",
        "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
        "Ireland": "🇮🇪",
        "Zimbabwe": "🇿🇼",
        "UAE": "🇦🇪",
        "Canada": "🇨🇦",
        "USA": "🇺🇸",
        "Italy": "🇮🇹",
        "Nepal": "🇳🇵",
        "Namibia": "🇳🇦",
        "Hong Kong": "🇭🇰",
        "Oman": "🇴🇲",
        "Papua New Guinea": "🇵🇬",
        "Uganda": "🇺🇬",
        "Malaysia": "🇲🇾",
        "Spain": "🇪🇸",
        "Germany": "🇩🇪",
        "Japan": "🇯🇵",
        "Portugal": "🇵🇹",
        "Denmark": "🇩🇰"
    }
    return flags.get(team_name, "🏳️")

# --------------


# Get role emoji
def get_role_emoji(role):
    if "Wicketkeeper" in role:
        return "<:wicketkeeper:1451994159668920330>"
    elif "Batsman" in role:
        return "<:bat:1451967322146213980>"
    elif "Bowler" in role:
        return "<:ball:1451974295793172547>"
    elif "All-Rounder" in role or "All-rounder" in role:
        return "<:allrounder:1451978476033671279>"
    return ""

# ========== OVR RATING SYSTEM ==========

def calc_batting_ovr(batting_avg):
    thresholds = [
        (70, 99), (62, 98), (55, 97), (50, 96),
        (47, 95), (43, 94), (40, 93), (37, 92),
        (35, 91), (30, 90), (27, 89), (24, 88),
        (21, 87), (18, 85), (16, 83), (14, 81),
        (12, 79), (10, 77), (9, 75),  (8, 73),
        (7, 71),  (6, 69),  (5, 67),  (4, 65),
        (3, 63),
    ]
    for min_avg, ovr in thresholds:
        if batting_avg >= min_avg:
            return ovr
    return 60


def calc_bowling_ovr(bowl_avg):
    if bowl_avg > 0:
        for avg_thresh, score in [
            (10, 99), (12, 97), (14, 95), (16, 93),
            (18, 91), (20, 89), (22, 87), (25, 84),
            (28, 81), (31, 78), (35, 74), (40, 70), (50, 65)
        ]:
            if bowl_avg <= avg_thresh:
                return score
        return 60
    else:
        return 60


def calc_player_ovr(bat_ovr, bowl_ovr, role):
    if "All-Rounder" in role or "All-rounder" in role:
        if bat_ovr is None and bowl_ovr is None:
            return 60
        if bat_ovr is None:
            return bowl_ovr
        if bowl_ovr is None:
            return bat_ovr
        high = max(bat_ovr, bowl_ovr)
        low  = min(bat_ovr, bowl_ovr)
        return round(0.65 * high + 0.35 * low)
    elif "Bowler" in role:
        if bowl_ovr is None and bat_ovr is None:
            return 60
        if bowl_ovr is None:
            return bat_ovr
        if bat_ovr is None:
            return bowl_ovr
        if bat_ovr > bowl_ovr:
            bonus = min(5, round(max(0, (bowl_ovr - 70) * 0.2)))
            return bat_ovr + bonus
        else:
            bonus = min(2, round(max(0, (bat_ovr - 72) * 0.1)))
            return bowl_ovr + bonus
    else:  # Batsman, Wicketkeeper, WK-Batsman
        if bat_ovr is None and bowl_ovr is None:
            return 60
        if bat_ovr is None:
            return bowl_ovr
        if bowl_ovr is None:
            return bat_ovr
        if bowl_ovr > bat_ovr:
            bonus = min(2, round(max(0, (bat_ovr - 72) * 0.1)))
            return bowl_ovr + bonus
        else:
            bonus = min(5, round(max(0, (bowl_ovr - 70) * 0.2)))
            return bat_ovr + bonus


def _get_ghost_ovr(user_id):
    """Return (bat_ovr, bowl_ovr) from the ghost table, or None if not found."""
    try:
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("SELECT bat_ovr, bowl_ovr FROM ovr_ghost_stats WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        conn.close()
        return row
    except Exception:
        return None


def get_player_ovr_for_vt(user_id, role="Batsman"):
    """Return the main OVR for a player (for use in -vt).
    Bat OVR unlocks at 60 balls faced, Bowl OVR unlocks at 60 balls bowled.
    Falls back to ghost OVR when there are no live stats at all."""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("""
        SELECT SUM(runs), SUM(balls_faced), SUM(runs_conceded), SUM(balls_bowled),
               SUM(wickets), SUM(not_out), COUNT(*)
        FROM match_stats WHERE user_id = ?
    """, (user_id,))
    row = c.fetchone()
    conn.close()

    if not row or row[0] is None:
        ghost = _get_ghost_ovr(user_id)
        if ghost:
            bat_ovr = ghost[0]
            bowl_ovr = ghost[1]
            return calc_player_ovr(bat_ovr, bowl_ovr, role)
        return None

    total_runs, total_balls_faced, total_runs_conceded, total_balls_bowled, total_wickets, times_not_out, matches_played = row

    FALLBACK_OVR = 60

    if (total_balls_faced or 0) >= 60:
        dismissals = matches_played - (times_not_out or 0)
        batting_avg = (float(total_runs or 0) / dismissals) if dismissals > 0 else (float(total_runs or 0) / max(matches_played, 1))
        bat_ovr = calc_batting_ovr(batting_avg)
    else:
        bat_ovr = FALLBACK_OVR

    if (total_balls_bowled or 0) >= 60:
        bowl_avg_val = (float(total_runs_conceded or 0) / total_wickets) if (total_wickets or 0) > 0 else 0.0
        bowl_ovr = calc_bowling_ovr(bowl_avg_val)
    else:
        bowl_ovr = FALLBACK_OVR

    # ── <18 matches nerf: reduce bat/bowl by 10%, then derive main OVR ──
    if (matches_played or 0) < 18:
        bat_ovr = round(bat_ovr * 0.90)
        bowl_ovr = round(bowl_ovr * 0.90)
    main_ovr = calc_player_ovr(bat_ovr, bowl_ovr, role)

    return main_ovr

# ========================================

def emoji_for_select(emoji_str):
    """Convert a custom emoji string like <:name:id> to a PartialEmoji for SelectOption use."""
    if not emoji_str:
        return None
    if emoji_str.startswith('<:') and emoji_str.endswith('>'):
        inner = emoji_str[2:-1]
        parts = inner.split(':')
        if len(parts) == 2:
            try:
                return discord.PartialEmoji(name=parts[0], id=int(parts[1]))
            except (ValueError, IndexError):
                pass
    return emoji_str

# Find player by name (flexible matching)
def find_player(player_name):
    teams_data = load_players()
    player_name_lower = player_name.lower()

    # First try exact match
    for team_data in teams_data:
        for player in team_data['players']:
            if player['name'].lower() == player_name_lower:
                return [player], [team_data['team']]

    # If no exact match, try partial match
    matches = []
    match_teams = []
    for team_data in teams_data:
        for player in team_data['players']:
            if player_name_lower in player['name'].lower():
                matches.append(player)
                match_teams.append(team_data['team'])

    if matches:
        return matches, match_teams

    return None, None

#---------------

async def create_squad_image(team_name, team_data, guild):
    """Create a squad visualization image using provided background"""

    # Load the background image
    try:
        img = Image.open("squadbackground.png").convert('RGBA')
        width, height = img.size
    except FileNotFoundError:
        print("❌ squadbackground.png not found!")
        return None

    # Categorize players
    wicketkeepers = []
    batsmen = []
    allrounders = []
    bowlers = []

    captain_name = get_team_captain(team_name)

    for player in team_data['players']:
        player_info = {
            'name': player['name'],
            'role': player['role'],
            'image': player['image'],
            'is_captain': player['name'] == captain_name
        }

        rep_info = get_representative(player['name'])
        if rep_info:
            member = guild.get_member(rep_info[0])
            if member and member.avatar:
                player_info['avatar_url'] = str(member.avatar.url)
            else:
                # Use default Discord picture from local file
                player_info['avatar_url'] = "discord.jpg"
        else:
            player_info['avatar_url'] = "discord.jpg"

        if "Wicketkeeper" in player['role']:
            wicketkeepers.append(player_info)
        elif "Batsman" in player['role']:
            batsmen.append(player_info)
        elif "Bowler" in player['role']:
            bowlers.append(player_info)
        elif "All-Rounder" in player['role'] or "All-rounder" in player['role']:
            allrounders.append(player_info)

    # Layout configuration
    avatar_size = 140
    player_size = 140
    role_icon_width = 120
    role_icon_height = 80
    wk_icon_width = 140  # WIDER WK ICON
    allrounder_icon_width = 140  # WIDER ALLROUNDER ICON
    bowler_icon_width = 140  # WIDER BOWLER ICON
    captain_icon_width = 140  # WAY WIDER CAPTAIN ICON
    captain_icon_height = 90  # CAPTAIN ICON HEIGHT
    horizontal_spacing = 50
    rows = [wicketkeepers, batsmen, allrounders, bowlers]

    # Calculate starting Y position - MOVED FURTHER UP
    start_y = 80  # MOVED FURTHER UP (was 120)
    row_spacing = 240

    # Add title text - REMOVED
    draw = ImageDraw.Draw(img)

    async with aiohttp.ClientSession() as session:
        for row_idx, row in enumerate(rows):
            if not row:
                continue

            # DYNAMIC SIZING: If more than 5 players, squeeze them
            if len(row) > 5:
                avatar_size_row = 110
                player_size_row = 110
                horizontal_spacing_row = 35
                pair_width = 165
                role_icon_width_row = 95
                role_icon_height_row = 65
                wk_icon_width_row = 110  # WIDER WK ICON for squeezed rows
                allrounder_icon_width_row = 110  # WIDER ALLROUNDER ICON for squeezed rows
                bowler_icon_width_row = 110  # WIDER BOWLER ICON for squeezed rows
                captain_icon_width_row = 110  # WIDER CAPTAIN ICON for squeezed rows
                captain_icon_height_row = 70  # CAPTAIN ICON HEIGHT for squeezed rows
                overlap_offset = 50  # LESS OVERLAP for smaller sizes
            else:
                avatar_size_row = avatar_size
                player_size_row = player_size
                horizontal_spacing_row = horizontal_spacing
                pair_width = 210
                role_icon_width_row = role_icon_width
                role_icon_height_row = role_icon_height
                wk_icon_width_row = wk_icon_width  # WIDER WK ICON
                allrounder_icon_width_row = allrounder_icon_width  # WIDER ALLROUNDER ICON
                bowler_icon_width_row = bowler_icon_width  # WIDER BOWLER ICON
                captain_icon_width_row = captain_icon_width  # WIDER CAPTAIN ICON
                captain_icon_height_row = captain_icon_height  # CAPTAIN ICON HEIGHT
                overlap_offset = 50  # REDUCED OVERLAP (was 70)

            # Calculate total width needed for this row
            total_width = len(row) * pair_width + (len(row) - 1) * horizontal_spacing_row
            start_x = (width - total_width) // 2

            current_y = start_y + (row_idx * row_spacing)

            for player_idx, player_info in enumerate(row):
                current_x = start_x + (player_idx * (pair_width + horizontal_spacing_row))

                # FIRST: Paste Discord avatar (left side) WITH RED BORDER
                avatar_x = current_x
                avatar_y = current_y

                if player_info['avatar_url']:
                    try:
                        # Check if it's the default discord.jpg or a URL
                        if player_info['avatar_url'] == "discord.jpg":
                            # Load from local file
                            avatar_img = Image.open("discord.jpg").convert('RGBA')
                        else:
                            # Download from URL
                            async with session.get(player_info['avatar_url']) as resp:
                                if resp.status == 200:
                                    avatar_data = await resp.read()
                                    avatar_img = Image.open(io.BytesIO(avatar_data)).convert('RGBA')
                                else:
                                    # Fallback to discord.jpg if download fails
                                    avatar_img = Image.open("discord.jpg").convert('RGBA')

                        avatar_img = avatar_img.resize((avatar_size_row, avatar_size_row), Image.Resampling.LANCZOS)

                        # Create a temporary image for avatar with border
                        border_thickness = 8
                        bordered_size = avatar_size_row + (border_thickness * 2)
                        bordered_img = Image.new('RGBA', (bordered_size, bordered_size), (0, 0, 0, 0))
                        bordered_draw = ImageDraw.Draw(bordered_img)

                        # Draw red circular border
                        bordered_draw.ellipse(
                            [(0, 0), (bordered_size, bordered_size)],
                            fill=None,
                            outline=(255, 0, 0, 255),
                            width=border_thickness
                        )

                        # Create circular mask for avatar
                        mask = Image.new('L', (avatar_size_row, avatar_size_row), 0)
                        mask_draw = ImageDraw.Draw(mask)
                        mask_draw.ellipse((0, 0, avatar_size_row, avatar_size_row), fill=255)

                        # Paste avatar in center of bordered image
                        bordered_img.paste(avatar_img, (border_thickness, border_thickness), mask)

                        # Paste the bordered avatar
                        img.paste(bordered_img, (avatar_x - border_thickness, avatar_y - border_thickness), bordered_img)
                    except Exception as e:
                        print(f"Error loading avatar: {e}")

                # SECOND: Paste player image (overlapping to the right) - TRANSPARENT WITH WHITE BACKGROUND AND BLACK OUTLINE
                player_image_url = player_info['image']
                if not player_image_url or player_image_url.strip() == "":
                    player_image_url = "fallback.webp"

                player_x = current_x + avatar_size_row - overlap_offset  # LESS OVERLAP
                player_y = current_y

                try:
                    # Check if it's a local file or URL
                    if player_image_url == "fallback.webp":
                        player_img = Image.open("fallback.webp").convert('RGBA')
                    else:
                        async with session.get(player_image_url) as resp:
                            if resp.status == 200:
                                player_img_data = await resp.read()
                                player_img = Image.open(io.BytesIO(player_img_data)).convert('RGBA')
                            else:
                                player_img = Image.open("fallback.webp").convert('RGBA')

                    player_img = player_img.resize((player_size_row, player_size_row), Image.Resampling.LANCZOS)

                    # Create WHITE background circle
                    white_bg = Image.new('RGBA', (player_size_row, player_size_row), (255, 255, 255, 255))

                    # Create circular mask
                    mask = Image.new('L', (player_size_row, player_size_row), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.ellipse((0, 0, player_size_row, player_size_row), fill=255)

                    # Composite player image on white background
                    white_bg.paste(player_img, (0, 0), player_img)

                    # MAKE TRANSPARENT
                    white_bg.putalpha(180)

                    # Create BLACK OUTLINE
                    outline_thickness = 3  # THIN BLACK OUTLINE
                    outlined_img = Image.new('RGBA', (player_size_row, player_size_row), (0, 0, 0, 0))
                    outlined_draw = ImageDraw.Draw(outlined_img)
                    outlined_draw.ellipse(
                        [(0, 0), (player_size_row - 1, player_size_row - 1)],
                        fill=None,
                        outline=(0, 0, 0, 255),
                        width=outline_thickness
                    )

                    # Paste player image with white background
                    img.paste(white_bg, (player_x, player_y), mask)
                    # Paste black outline on top
                    img.paste(outlined_img, (player_x, player_y), outlined_img)

                except Exception as e:
                    print(f"Error loading player image: {e}")
                    try:
                        player_img = Image.open("fallback.webp").convert('RGBA')
                        player_img = player_img.resize((player_size_row, player_size_row), Image.Resampling.LANCZOS)

                        white_bg = Image.new('RGBA', (player_size_row, player_size_row), (255, 255, 255, 255))
                        mask = Image.new('L', (player_size_row, player_size_row), 0)
                        mask_draw = ImageDraw.Draw(mask)
                        mask_draw.ellipse((0, 0, player_size_row, player_size_row), fill=255)
                        white_bg.paste(player_img, (0, 0), player_img)
                        white_bg.putalpha(180)

                        outlined_img = Image.new('RGBA', (player_size_row, player_size_row), (0, 0, 0, 0))
                        outlined_draw = ImageDraw.Draw(outlined_img)
                        outlined_draw.ellipse(
                            [(0, 0), (player_size_row - 1, player_size_row - 1)],
                            fill=None,
                            outline=(0, 0, 0, 255),
                            width=3
                        )

                        img.paste(white_bg, (player_x, player_y), mask)
                        img.paste(outlined_img, (player_x, player_y), outlined_img)
                    except:
                        pass

                # Add role icon - BOTTOM LEFT (under the avatar) - WIDER FOR SPECIFIC ROLES, MOVED LEFT AND DOWN
                role_icon_path = None
                current_role_width = role_icon_width_row

                if "Wicketkeeper" in player_info['role']:
                    role_icon_path = "wk.png"
                    current_role_width = wk_icon_width_row  # USE WIDER WIDTH FOR WK
                elif "Batsman" in player_info['role']:
                    role_icon_path = "bat.png"
                elif "Bowler" in player_info['role']:
                    role_icon_path = "bowler.png"
                    current_role_width = bowler_icon_width_row  # USE WIDER WIDTH FOR BOWLER
                elif "All-Rounder" in player_info['role'] or "All-rounder" in player_info['role']:
                    role_icon_path = "allrounder.png"
                    current_role_width = allrounder_icon_width_row  # USE WIDER WIDTH FOR ALLROUNDER

                if role_icon_path:
                    try:
                        role_icon = Image.open(role_icon_path).convert('RGBA')
                        role_icon = role_icon.resize((current_role_width, role_icon_height_row), Image.Resampling.LANCZOS)
                        icon_x = avatar_x - 35  # MOVED MORE TO LEFT (was -25)
                        icon_y = avatar_y + avatar_size_row - role_icon_height_row + 20  # MOVED MORE DOWN (was +10)
                        img.paste(role_icon, (icon_x, icon_y), role_icon)
                    except Exception as e:
                        print(f"Error loading role icon: {e}")

                # Add captain icon if applicable - TOP RIGHT (over player image)
                if player_info['is_captain']:
                    try:
                        captain_icon = Image.open("captain.png").convert('RGBA')
                        captain_icon = captain_icon.resize((captain_icon_width_row, captain_icon_height_row), Image.Resampling.LANCZOS)
                        cap_x = player_x + player_size_row - 70  # MOVED MORE TO LEFT (was -55)
                        cap_y = player_y - 15
                        img.paste(captain_icon, (cap_x, cap_y), captain_icon)
                    except Exception as e:
                        print(f"Error loading captain icon: {e}")

    # Add team flag in bottom right - CIRCULAR SHAPE, SAME SIZE FOR ALL TEAMS
    if team_name.lower() == "west indies":
        # Special handling for West Indies - use local file
        try:
            flag_img = Image.open("westindies.jpg").convert('RGBA')
            flag_size = 240  # CIRCULAR SIZE
            flag_img = flag_img.resize((flag_size, flag_size), Image.Resampling.LANCZOS)

            # Create circular mask
            mask = Image.new('L', (flag_size, flag_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, flag_size, flag_size), fill=255)

            # Create circular flag
            circular_flag = Image.new('RGBA', (flag_size, flag_size), (0, 0, 0, 0))
            circular_flag.paste(flag_img, (0, 0), mask)

            flag_x = width - 260
            flag_y = height - 260

            # Paste circular flag
            img.paste(circular_flag, (flag_x, flag_y), circular_flag)
        except Exception as e:
            print(f"Error loading West Indies flag: {e}")
    else:
        # Use flag URL for other teams
        flag_url = get_team_flag_url(team_name)
        if flag_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(flag_url) as resp:
                        if resp.status == 200:
                            flag_data = await resp.read()
                            flag_img = Image.open(io.BytesIO(flag_data)).convert('RGBA')
                            flag_size = 240  # CIRCULAR SIZE
                            flag_img = flag_img.resize((flag_size, flag_size), Image.Resampling.LANCZOS)

                            # Create circular mask
                            mask = Image.new('L', (flag_size, flag_size), 0)
                            mask_draw = ImageDraw.Draw(mask)
                            mask_draw.ellipse((0, 0, flag_size, flag_size), fill=255)

                            # Create circular flag
                            circular_flag = Image.new('RGBA', (flag_size, flag_size), (0, 0, 0, 0))
                            circular_flag.paste(flag_img, (0, 0), mask)

                            flag_x = width - 260
                            flag_y = height - 260

                            # Paste circular flag
                            img.paste(circular_flag, (flag_x, flag_y), circular_flag)
            except Exception as e:
                print(f"Error loading flag: {e}")

    # Convert to bytes
    img = img.convert('RGB')
    output = io.BytesIO()
    img.save(output, format='PNG', quality=95)
    output.seek(0)

    return output
#----------------

# Get player representative
def get_representative(player_name):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT user_id, username FROM player_representatives WHERE player_name = ?", 
              (player_name,))
    result = c.fetchone()
    conn.close()
    return result

# Create player embed
async def create_player_embed(player, team_name, guild):
    embed = discord.Embed(
        color=get_team_color(team_name)
    )

    # Get representative info
    rep_info = get_representative(player['name'])

    if rep_info:
        user_id, username = rep_info
        member = guild.get_member(user_id)

        # Author field with representative
        embed.set_author(
            name=f"{player['name']} (@{username})",
            icon_url=player['image']
        )

        # Footer with representative
        embed.set_footer(
            text="Nations Player 2025-2026",
            icon_url=member.avatar.url if member and member.avatar else "attachment://default.jpg"
        )

        # Image (representative's avatar)
        if member and member.avatar:
            embed.set_image(url=member.avatar.url)
        else:
            embed.set_image(url="attachment://default.jpg")
    else:
        # Author field - unclaimed
        embed.set_author(
            name=f"{player['name']} (Unclaimed)",
            icon_url=player['image']
        )

        # Footer - unclaimed
        embed.set_footer(
            text="Unclaimed Player",
            icon_url="attachment://default.jpg"
        )

        # Image - default
        embed.set_image(url="attachment://default.jpg")

    # Title
    flag = get_team_flag(team_name)
    embed.title = f"{flag}  ✦ {player['name']}"

    # Description - Role and primary style
    role_emoji = get_role_emoji(player['role'])
    description = f"─ **{player['role']}** {role_emoji}\n"

    # Primary style based on role
    if "Batsman" in player['role'] or "Wicketkeeper" in player['role']:
        # Batting style first
        description += f"﹒*{player['batting_style']}*\n\n"
        description += "__**Bowling Style:**__\n"
        if player['bowling_style']:
            description += f"﹒*{player['bowling_style']}*"
        else:
            description += "﹒*Not Officially Declared*  ﹒❌﹒"
    elif "Bowler" in player['role']:
        # Bowling style first
        description += f"﹒*{player['bowling_style']}*\n\n"
        description += "__**Batting Style:**__\n"
        description += f"﹒*{player['batting_style']}*"
    else:  # All-Rounder
        # Both styles
        description += f"﹒*{player['batting_style']}* (Bat)\n"
        description += f"﹒*{player['bowling_style']}* (Bowl)"

    embed.description = description

    # Thumbnail
    embed.set_thumbnail(url=player['image'])

    return embed

def get_team_captain(team_name):
    """Get captain of a team"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name FROM team_captains WHERE team_name = ?", (team_name,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def set_team_captain(team_name, player_name, user_id, username):
    """Set a player as team captain"""
    conn = sqlite3.connect('players.db')
    try:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO team_captains VALUES (?, ?, ?, ?)",
                  (team_name, player_name, user_id, username))
        conn.commit()
    finally:
        conn.close()


def get_player_representative_by_username(username):
    """Look up a representative without holding the connection across awaits."""
    conn = sqlite3.connect('players.db')
    try:
        c = conn.cursor()
        c.execute(
            "SELECT player_name, user_id FROM player_representatives WHERE username = ?",
            (username,),
        )
        return c.fetchone()
    finally:
        conn.close()

def remove_team_captain(team_name):
    """Remove captain from a team"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("DELETE FROM team_captains WHERE team_name = ?", (team_name,))
    conn.commit()
    conn.close()

def get_team_vice_captain(team_name):
    """Get the vice-captain player name for a team."""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name FROM team_vice_captains WHERE team_name = ?", (team_name,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def squad_cache_fingerprint(team_data, guild):
    """Fingerprint all data that can change the rendered squad image."""
    players = []
    for player in team_data.get("players", []):
        representative = get_representative(player["name"])
        member = guild.get_member(representative[0]) if representative else None
        avatar_url = str(member.avatar.url) if member and member.avatar else None
        players.append({
            "name": player.get("name"),
            "role": player.get("role"),
            "image": player.get("image"),
            "representative": representative,
            "avatar_url": avatar_url,
        })

    fingerprint_data = {
        "team": team_data.get("team"),
        "flag_url": get_team_flag_url(team_data["team"]),
        "captain": get_team_captain(team_data["team"]),
        "vice_captain": get_team_vice_captain(team_data["team"]),
        "players": players,
    }
    payload = json.dumps(
        fingerprint_data,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


async def scan_squad_image_cache(bot_instance):
    """Find the newest cached image for each team in the squad cache channel."""
    channel = bot_instance.get_channel(SQUAD_CACHE_CHANNEL_ID)
    if not channel:
        return {}

    cache = {}
    pattern = re.compile(
        r"^SQUAD_CACHE team:(?P<team>.+?) hash:(?P<hash>[a-f0-9]+)"
        r"(?: \((?P<version>\d+)\))?$"
    )
    async for message in channel.history(limit=None):
        if not message.attachments:
            continue
        match = pattern.search(message.content.strip())
        if not match:
            continue
        team_name = match.group("team")
        version = int(match.group("version") or 1)
        key = team_name.lower()
        current = cache.get(key)
        if current is None or version > current["version"]:
            cache[key] = {
                "team_name": team_name,
                "hash": match.group("hash"),
                "version": version,
                "message_id": message.id,
                "url": message.attachments[0].url,
            }
    return cache


async def post_squad_image_to_cache(
    bot_instance,
    team_name,
    fingerprint,
    image_bytes,
    version=1,
):
    """Post a versioned squad image to the cache channel."""
    channel = bot_instance.get_channel(SQUAD_CACHE_CHANNEL_ID)
    if not channel:
        return None
    image_bytes.seek(0)
    try:
        return await channel.send(
            content=f"SQUAD_CACHE team:{team_name} hash:{fingerprint} ({version})",
            file=discord.File(
                image_bytes,
                filename=f"{team_name}_squad.png",
            ),
        )
    finally:
        # The same generated stream may be sent to the requesting channel
        # when cache delivery fails, so always leave it reusable.
        image_bytes.seek(0)


async def refresh_squad_image_cache(team_name, guild):
    """Refresh an existing team cache after a squad-affecting update."""
    try:
        teams_data = load_players()
        team_data = next(
            (
                team for team in teams_data
                if team.get("team", "").lower() == team_name.lower()
            ),
            None,
        )
        if not team_data:
            return False

        cache = await scan_squad_image_cache(bot)
        cached = cache.get(team_data["team"].lower())
        if not cached:
            return False

        fingerprint = squad_cache_fingerprint(team_data, guild)
        if cached["hash"] == fingerprint:
            return False

        image_bytes = await create_squad_image(team_data["team"], team_data, guild)
        if not image_bytes:
            return False

        new_message = await post_squad_image_to_cache(
            bot,
            team_data["team"],
            fingerprint,
            image_bytes,
            version=cached["version"] + 1,
        )
        return bool(new_message)
    except Exception as exc:
        print(f"[SquadCache] Refresh failed for {team_name}: {exc}")
        return False


def set_team_vice_captain(team_name, player_name, user_id, username):
    """Set or replace a team's vice-captain."""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO team_vice_captains VALUES (?, ?, ?, ?)",
        (team_name, player_name, user_id, username)
    )
    conn.commit()
    conn.close()

def remove_team_vice_captain(team_name):
    """Remove a team's vice-captain."""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("DELETE FROM team_vice_captains WHERE team_name = ?", (team_name,))
    conn.commit()
    conn.close()

# Pagination View for Player List
class PlayerListView(View):
    def __init__(self, pages, ctx):
        super().__init__(timeout=180)
        self.pages = pages
        self.current_page = 0
        self.ctx = ctx
        self.message = None
        self.update_buttons()

    def update_buttons(self):
        self.children[0].disabled = self.current_page == 0
        self.children[1].disabled = self.current_page == len(self.pages) - 1

    async def update_message(self):
        self.update_buttons()
        await self.message.edit(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.current_page -= 1
        await interaction.response.defer()
        await self.update_message()

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.current_page += 1
        await interaction.response.defer()
        await self.update_message()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            await self.message.edit(view=self)

@bot.command(name="view", aliases=["v"], help="Search and view a cricket player")
async def view_command(ctx, *, name: str):
    players, team_names = find_player(name)

    if not players:
        await ctx.send(
            f"❌ Player '{name}' not found. Please check the spelling and try again."
        )
        return

    # If multiple matches found, ask user to clarify
    if len(players) > 1:
        embed = discord.Embed(
            title="🔍 Multiple Players Found",
            description=f"Multiple players match '{name}'. Please be more specific:\n\n",
            color=0xFFA500
        )

        for i, (player, team) in enumerate(zip(players, team_names), 1):
            flag = get_team_flag(team)
            embed.description += f"**{i}.** {flag} **{player['name']}** - {team}\n"

        embed.set_footer(text="Use the full name with .view command")
        await ctx.send(embed=embed)
        return

    # Single match found
    player = players[0]
    team_name = team_names[0]
    embed = await create_player_embed(player, team_name, ctx.guild)

    # Check if we need to send default.jpg file
    rep_info = get_representative(player['name'])
    if not rep_info:
        try:
            file = discord.File("default.jpg", filename="default.jpg")
            await ctx.send(embed=embed, file=file)
        except FileNotFoundError:
            await ctx.send(embed=embed)
    else:
        member = ctx.guild.get_member(rep_info[0])
        if not member or not member.avatar:
            try:
                file = discord.File("default.jpg", filename="default.jpg")
                await ctx.send(embed=embed, file=file)
            except FileNotFoundError:
                await ctx.send(embed=embed)
        else:
            await ctx.send(embed=embed)

@bot.command(name="claim", aliases=["c"], help="[ADMIN] Add a representative to a player")
@is_staff_or_admin()
async def claim_command(ctx, user: discord.Member, *, player_name: str):
    players, team_names = find_player(player_name)

    if not players:
        await ctx.send(
            f"❌ Player '{player_name}' not found."
        )
        return

    # If multiple matches, ask for clarification
    if len(players) > 1:
        embed = discord.Embed(
            title="🔍 Multiple Players Found",
            description=f"Multiple players match '{player_name}'. Please use the full name:\n\n",
            color=0xFFA500
        )

        for i, (player, team) in enumerate(zip(players, team_names), 1):
            flag = get_team_flag(team)
            embed.description += f"**{i}.** {flag} **{player['name']}** - {team}\n"

        await ctx.send(embed=embed)
        return

    player = players[0]
    team_name = team_names[0]

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Check if player is already claimed
    c.execute("SELECT username FROM player_representatives WHERE player_name = ?", 
              (player['name'],))
    existing = c.fetchone()

    if existing:
        await ctx.send(
            f"⚠️ {player['name']} is already represented by @{existing[0]}. Use `-unclaim` first to remove them."
        )
        conn.close()
        return

    # Add representative
    c.execute("INSERT INTO player_representatives VALUES (?, ?, ?)",
              (player['name'], user.id, user.name))
    conn.commit()
    conn.close()

    asyncio.get_event_loop().create_task(
        refresh_squad_image_cache(team_name, ctx.guild)
    )

    await ctx.send(
        f"✅ {user.mention} is now representing **{player['name']}** from {team_name}!"
    )

    # Upload a card for the new user to the cache channel
    asyncio.get_event_loop().create_task(ensure_card_in_cache(bot, user.id))

    # Send notification to claims channel
    claims_channel = bot.get_channel(1452037538792476682)
    if claims_channel:
        # Create claim announcement embed
        embed = discord.Embed(
            title="🎉 Player Update!",
            description=f"{user.mention} Officially Represents **{player['name']}**",
            color=get_team_color(team_name)
        )

        flag = get_team_flag(team_name)
        role_emoji = get_role_emoji(player['role'])

        embed.add_field(
            name=f"{flag} Player Info",
            value=f"**{player['name']}**\n{role_emoji} {player['role']}",
            inline=True
        )

        embed.add_field(
            name="👤 Representative",
            value=f"{user.mention}",
            inline=True
        )

        # Set player image as thumbnail and user avatar as image
        embed.set_thumbnail(url=user.avatar.url)
        embed.set_image(url=player['image'])

        embed.set_footer(text=f"TFH Nations", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        embed.timestamp = discord.utils.utcnow()

        await claims_channel.send(embed=embed)

class CaptainRequestView(discord.ui.View):
    """Button view sent in the specialclaim DM so the user can request captaincy."""
    def __init__(self, requester: discord.Member, team_name: str):
        super().__init__(timeout=None)
        self.requester = requester
        self.team_name = team_name
        self.clicked = False

    @discord.ui.button(label="Become Captain 🧢", style=discord.ButtonStyle.primary)
    async def captain_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.clicked:
            await interaction.response.send_message("You've already sent this request!", ephemeral=True)
            return
        self.clicked = True
        button.disabled = True
        # Disable the button on the original DM embed
        await interaction.response.edit_message(view=self)
        # Acknowledge with a new message in the DM
        await interaction.followup.send("Request Sent! ✅")
        # DM the owner
        try:
            owner = await interaction.client.fetch_user(765965975761715241)
            await owner.send(
                f"{self.requester.mention} wants to be captain of **{self.team_name}**"
            )
        except Exception as e:
            print(f"[SPECIALCLAIM] Failed to DM owner about captain request: {e}")


@bot.command(name="specialclaim", help="[OWNER] Interactively claim players for a team")
async def specialclaim_command(ctx, team_name: str, *, rest: str = ""):
    if ctx.author.id != 765965975761715241:
        return

    # Parse optional quoted extra message from the argument
    extra_message = None
    _qm = re.search(r'"([^"]+)"', rest)
    if _qm:
        extra_message = _qm.group(1)

    # Validate team
    team_key = team_name.lower()
    if team_key not in TEAM_ROLE_IDS:
        teams_list = ", ".join(t.title() for t in TEAM_ROLE_IDS)
        await ctx.send(f"❌ Team **{team_name}** not found.\nAvailable teams: {teams_list}")
        return

    # Get team data from players list
    teams_data = load_players()
    team_data = None
    actual_team_name = None
    for td in teams_data:
        if td['team'].lower() == team_key:
            team_data = td
            actual_team_name = td['team']
            break

    if not team_data:
        await ctx.send(f"❌ No player data found for **{team_name}**.")
        return

    team_role_id = TEAM_ROLE_IDS[team_key]
    team_role = ctx.guild.get_role(team_role_id)
    flag = get_team_flag(actual_team_name)

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    await ctx.send(
        f"✅ Started special claim session for {flag} **{actual_team_name}**.\n"
        f"Type `END` at any point to stop.\n\n"
        f"**Give a username:**"
    )

    first = True
    while True:
        # ── Step 1: get username ──────────────────────────────────────────
        if not first:
            await ctx.send("**Name another person** (or type `END` to finish):")
        first = False

        try:
            msg = await bot.wait_for('message', check=check, timeout=120)
        except asyncio.TimeoutError:
            await ctx.send("⏰ Session timed out.")
            return

        if msg.content.strip().upper() == "END":
            await ctx.send("✅ Special claim session ended.")
            return

        username_input = msg.content.strip()

        # Resolve member: mention > exact name > partial name
        member = None
        if msg.mentions:
            member = msg.mentions[0]
        else:
            member = ctx.guild.get_member_named(username_input)
            if not member:
                ulow = username_input.lower()
                for m in ctx.guild.members:
                    if m.name.lower() == ulow or m.display_name.lower() == ulow:
                        member = m
                        break
            if not member:
                ulow = username_input.lower()
                for m in ctx.guild.members:
                    if ulow in m.name.lower() or ulow in m.display_name.lower():
                        member = m
                        break

        if not member:
            await ctx.send(
                f"❌ Could not find **{username_input}** in this server. "
                f"Try again or type `END`.\n\n**Give a username:**"
            )
            first = True   # re-show "Give a username" prompt next iteration
            continue

        # ── Step 2: get player name (inner loop until valid) ──────────────
        await ctx.send(
            f"✅ Found {member.mention}. "
            f"**Which player of {actual_team_name} do you want this person to have?**"
        )

        matched_player = None
        while matched_player is None:
            try:
                pmsg = await bot.wait_for('message', check=check, timeout=120)
            except asyncio.TimeoutError:
                await ctx.send("⏰ Session timed out.")
                return

            if pmsg.content.strip().upper() == "END":
                await ctx.send("✅ Special claim session ended.")
                return

            player_input = pmsg.content.strip()
            player_input_lower = player_input.lower()

            # Exact match first, then partial within this team
            for p in team_data['players']:
                if p['name'].lower() == player_input_lower:
                    matched_player = p
                    break

            if not matched_player:
                partial = [p for p in team_data['players'] if player_input_lower in p['name'].lower()]
                if len(partial) == 1:
                    matched_player = partial[0]
                elif len(partial) > 1:
                    names = "\n".join(f"• {p['name']}" for p in partial)
                    await ctx.send(
                        f"🔍 Multiple players match **{player_input}**:\n{names}\n\n"
                        f"**Please be more specific:**"
                    )
                else:
                    await ctx.send(
                        f"❌ No player matching **{player_input}** found in {actual_team_name}. "
                        f"**Try again:**"
                    )

        # ── Step 3: claim the player ──────────────────────────────────────
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        c.execute("SELECT username FROM player_representatives WHERE player_name = ?", (matched_player['name'],))
        existing = c.fetchone()
        if existing:
            await ctx.send(
                f"⚠️ **{matched_player['name']}** is already represented by @{existing[0]}. "
                f"Use `-unclaim` first.\n\n**Give a username:**"
            )
            conn.close()
            first = True
            continue

        c.execute("INSERT INTO player_representatives VALUES (?, ?, ?)",
                  (matched_player['name'], member.id, member.name))
        conn.commit()
        conn.close()

        asyncio.get_event_loop().create_task(
            refresh_squad_image_cache(actual_team_name, ctx.guild)
        )

        await ctx.send(f"✅ {member.mention} is now representing **{matched_player['name']}** from {actual_team_name}!")

        # Assign team role
        if team_role:
            try:
                if team_role not in member.roles:
                    await member.add_roles(team_role, reason=f"specialclaim by {ctx.author}")
            except discord.Forbidden:
                await ctx.send(f"⚠️ Could not assign the **{actual_team_name}** role to {member.mention} — missing permissions.")

        # Card cache
        asyncio.get_event_loop().create_task(ensure_card_in_cache(bot, member.id))

        # Post to claims channel
        claims_channel = bot.get_channel(1452037538792476682)
        if claims_channel:
            ann_embed = discord.Embed(
                title="🎉 Player Update!",
                description=f"{member.mention} Officially Represents **{matched_player['name']}**",
                color=get_team_color(actual_team_name)
            )
            role_emoji = get_role_emoji(matched_player['role'])
            ann_embed.add_field(
                name=f"{flag} Player Info",
                value=f"**{matched_player['name']}**\n{role_emoji} {matched_player['role']}",
                inline=True
            )
            ann_embed.add_field(name="👤 Representative", value=f"{member.mention}", inline=True)
            ann_embed.set_thumbnail(url=member.avatar.url if member.avatar else None)
            ann_embed.set_image(url=matched_player['image'])
            ann_embed.set_footer(text="TFH Nations", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
            ann_embed.timestamp = discord.utils.utcnow()
            await claims_channel.send(embed=ann_embed)

        # DM the member
        dm_embed = discord.Embed(
            description=(
                f"You have been claimed as **{matched_player['name']}** "
                f"and your team is **{actual_team_name}**"
            ),
            color=get_team_color(actual_team_name)
        )
        dm_embed.set_thumbnail(url=matched_player['image'])
        dm_embed.set_footer(
            text="HC ODI WC 2026",
            icon_url="https://i.ibb.co/CsJbz15H/Add-a-heading-2026-07-23-T135208-900.png"
        )

        view = CaptainRequestView(requester=member, team_name=actual_team_name)
        try:
            await member.send(content=extra_message, embed=dm_embed, view=view)
        except discord.Forbidden:
            await ctx.send(f"⚠️ Could not DM {member.mention} — they may have DMs disabled.")


@bot.command(name="unclaim", aliases=["uc"], help="[ADMIN] Remove a player's representative")
@is_staff_or_admin()
async def unclaim_command(ctx, *, player_name: str):
    players, team_names = find_player(player_name)

    if not players:
        await ctx.send(
            f"❌ Player '{player_name}' not found."
        )
        return

    # If multiple matches, ask for clarification
    if len(players) > 1:
        embed = discord.Embed(
            title="🔍 Multiple Players Found",
            description=f"Multiple players match '{player_name}'. Please use the full name:\n\n",
            color=0xFFA500
        )

        for i, (player, team) in enumerate(zip(players, team_names), 1):
            flag = get_team_flag(team)
            embed.description += f"**{i}.** {flag} **{player['name']}** - {team}\n"

        await ctx.send(embed=embed)
        return

    player = players[0]
    team_name = team_names[0]

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Check if player has a representative
    c.execute("SELECT username FROM player_representatives WHERE player_name = ?", 
              (player['name'],))
    existing = c.fetchone()

    if not existing:
        await ctx.send(
            f"⚠️ {player['name']} is not currently claimed by anyone."
        )
        conn.close()
        return

    # Remove representative
    c.execute("DELETE FROM player_representatives WHERE player_name = ?",
              (player['name'],))
    c.execute("DELETE FROM team_vice_captains WHERE player_name = ?",
              (player['name'],))
    conn.commit()
    conn.close()

    asyncio.get_event_loop().create_task(
        refresh_squad_image_cache(team_name, ctx.guild)
    )

    await ctx.send(
        f"✅ Removed @{existing[0]} as the representative of **{player['name']}**."
    )

@bot.command(name="me", aliases=["myrep"], help="View the player you represent")
async def myclaim_command(ctx):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", 
              (ctx.author.id,))
    result = c.fetchone()
    conn.close()

    if not result:
        await ctx.send(
            "❌ You don't represent any player yet."
        )
        return

    player_name = result[0]
    players, team_names = find_player(player_name)

    if players:
        player = players[0]
        team_name = team_names[0]
        embed = await create_player_embed(player, team_name, ctx.guild)
        await ctx.send(embed=embed)
    else:
        await ctx.send(
            f"⚠️ Error: Player data for {player_name} not found."
        )


# Add this to your main.py file

# Team Selection View
class TeamSelectView(View):
    def __init__(self, ctx):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.selected_team = None
        self.add_team_select()

    def add_team_select(self):
        teams_data = load_players()

        chunks = [teams_data[:25], teams_data[25:]]
        placeholders = ["🏏 Select Your Nation", "🏏 More Nations..."]

        for idx, chunk in enumerate(chunks):
            if not chunk:
                continue
            options = []
            for team_data in chunk:
                flag = get_team_flag(team_data['team'])
                total_players = len(team_data['players'])
                claimed_players = sum(1 for player in team_data['players'] if get_representative(player['name']))
                if claimed_players == total_players:
                    description = f"(TEAM FULL) - All {total_players} players claimed"
                else:
                    description = f"View {team_data['team']} players - {total_players - claimed_players} available"
                options.append(discord.SelectOption(
                    label=team_data['team'],
                    description=description,
                    emoji=flag
                ))
            select = Select(
                placeholder=placeholders[idx],
                options=options,
                custom_id=f"team_select_{idx}"
            )
            select.callback = self.team_callback
            self.add_item(select)

    async def team_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.selected_team = interaction.data['values'][0]

        # Show player selection for the chosen team
        view = PlayerSelectView(self.ctx, self.selected_team)

        flag = get_team_flag(self.selected_team)
        embed = discord.Embed(
            title=f"{flag} Select Your Player from {self.selected_team}",
            description="Choose the player you want to represent from the dropdown below.",
            color=get_team_color(self.selected_team)
        )

        flag_url = get_team_flag_url(self.selected_team)
        if flag_url:
            embed.set_thumbnail(url=flag_url)

        embed.set_footer(text="You can only represent one player at a time")

        await interaction.response.edit_message(embed=embed, view=view)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(view=self)
        except:
            pass

# Player Selection View
class PlayerSelectView(View):
    def __init__(self, ctx, team_name):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.team_name = team_name
        self.add_player_select()

    def add_player_select(self):
        teams_data = load_players()
        team_data = None

        for t in teams_data:
            if t['team'] == self.team_name:
                team_data = t
                break

        if not team_data:
            return

        # Create options for player selection (max 25)
        options = []
        for player in team_data['players'][:25]:
            rep_info = get_representative(player['name'])

            if rep_info:
                description = f"Claimed by @{rep_info[1]}"
            else:
                description = "Unclaimed - Available"

            role_emoji = get_role_emoji(player['role'])

            # Check if player is elite and use elite emoji instead
            if player['name'] in elite_players:
                elite_emoji = bot.get_emoji(1452949859412738110)
                if elite_emoji:
                    role_emoji = elite_emoji
                else:
                    role_emoji = emoji_for_select(role_emoji)
            else:
                role_emoji = emoji_for_select(role_emoji)

            options.append(
                discord.SelectOption(
                    label=player['name'],
                    description=description,
                    emoji=role_emoji,
                    value=player['name']
                )
            )

        select = Select(
            placeholder="👤 Select Your Player",
            options=options,
            custom_id="player_select"
        )
        select.callback = self.player_callback
        self.add_item(select)

    async def player_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        selected_player_name = interaction.data['values'][0]

        # Check if user already represents a player
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", 
                  (interaction.user.id,))
        existing = c.fetchone()
        conn.close()

        if existing:
            await interaction.response.send_message(
                f"❌ You already represent **{existing[0]}**!\n"
                f"Use `-unrepresent / -unrep` to remove your current player before claiming another.",
                ephemeral=True
            )
            return

        # Check if player is already claimed
        rep_info = get_representative(selected_player_name)
        if rep_info:
            await interaction.response.send_message(
                f"❌ **{selected_player_name}** is already represented by @{rep_info[1]}!",
                ephemeral=True
            )
            return

        # Find player data
        players, team_names = find_player(selected_player_name)
        if not players:
            await interaction.response.send_message("❌ Player data not found!", ephemeral=True)
            return

        player = players[0]
        team_name = team_names[0]

        # Check if player is elite - block elite players from being claimed
        if selected_player_name in elite_players:
            try:
                elite_emoji = interaction.client.get_emoji(1452949859412738110)
                emoji_str = f"<:elite:{elite_emoji.id}>" if elite_emoji else "<:elite:1452949859412738110>"
                auction_channel = interaction.client.get_channel(1516051222136623104)
                channel_mention = auction_channel.mention if auction_channel else "<#1516051222136623104>"

                dm_embed = discord.Embed(
                    title="⭐ Elite Player Selected",
                    description=f"This is an elite {emoji_str} player, you will have to buy elite players in {channel_mention}",
                    color=0xFFD700
                )
                await interaction.user.send(embed=dm_embed)
            except discord.Forbidden:
                pass

            await interaction.response.send_message(
                f"❌ **{selected_player_name}** is an elite player and can only be purchased at auction!",
                ephemeral=True
            )
            return

        # DIRECTLY CLAIM THE PLAYER (no approval needed)
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Add the claim
        c.execute("INSERT INTO player_representatives VALUES (?, ?, ?)",
                  (player['name'], interaction.user.id, interaction.user.name))
        conn.commit()
        conn.close()

        # Upload a card for the new user to the cache channel
        asyncio.get_event_loop().create_task(ensure_card_in_cache(bot, interaction.user.id))

        # Send success message to user
        await interaction.response.send_message(
            f"✅ You are now representing **{player['name']}**!\n"
            f"Use `-me` to view your player anytime.",
            ephemeral=True
        )

        # Send notification to claims channel
        claims_channel = interaction.client.get_channel(1452037538792476682)
        if claims_channel:
            flag = get_team_flag(team_name)
            role_emoji = get_role_emoji(player['role'])

            claim_embed = discord.Embed(
                title="🎉 Player Update!",
                description=f"{interaction.user.mention} Officially Represents **{player['name']}**",
                color=get_team_color(team_name)
            )

            # Set author with player's image as icon
            claim_embed.set_author(
                name=".",
                icon_url=player['image']
            )

            claim_embed.add_field(
                name=f"{flag} Player Info",
                value=f"**{player['name']}**\n{role_emoji} {player['role']}",
                inline=True
            )
            claim_embed.add_field(
                name="👤 Representative",
                value=f"{interaction.user.mention}",
                inline=True
            )
            claim_embed.set_thumbnail(url=interaction.user.avatar.url if interaction.user.avatar else None)
            claim_embed.set_image(url=player['image'])
            claim_embed.set_footer(text=f"TFH Nations")
            claim_embed.timestamp = discord.utils.utcnow()
            await claims_channel.send(embed=claim_embed)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True

# Main represent command
@bot.command(name="represent", aliases=["rep"], help="[ADMIN] Request to represent a cricket player")
@is_staff_or_admin()
async def represent_command(ctx):
    # Check if user already represents a player
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", 
              (ctx.author.id,))
    existing = c.fetchone()

    conn.close()

    if existing:
        await ctx.send(
            f"❌ You already represent **{existing[0]}**!\n"
            f"Use `-unrepresent` to remove your current player before claiming another."
        )
        return

    # Create team selection embed
    embed = discord.Embed(
        title="🏏 Select Your Nation",
        description="Choose the nation you want to represent from the dropdown menu below.",
        color=0x0066CC
    )

    embed.set_footer(text="Step 1 of 2: Select your nation")

    view = TeamSelectView(ctx)
    view.message = await ctx.send(embed=embed, view=view)

# Unrepresent command
@bot.command(name="unrepresent", aliases=["unrep"], help="[ADMIN] Remove yourself as a player representative")
@is_staff_or_admin()
async def unrepresent_command(ctx):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", 
              (ctx.author.id,))
    result = c.fetchone()

    if not result:
        await ctx.send("❌ You don't represent any player!")
        conn.close()
        return

    player_name = result[0]
    conn.close()

    # Warning embed
    warn_embed = discord.Embed(
        title="⚠️ Warning: Stats Will Be Reset",
        description=(
            f"You are about to stop representing **{player_name}**.\n\n"
            f"**⚠️ Your cricket stats (runs, wickets, matches, etc.) will be wiped** — they'll appear as zero.\n\n"
            f"🔒 **Your OVR rating is secretly preserved.** If you've batted or bowled 60+ balls, your Bat OVR and Bowl OVR are saved in the background and will still show on `-vt` and future `-statsi` lookups.\n\n"
            f"Your old player will be recorded in history via `-oldreps`.\n\n"
            f"Are you sure you want to continue?"
        ),
        color=0xFF0000
    )

    confirm_view = ConfirmationView()
    msg = await ctx.send(embed=warn_embed, view=confirm_view)
    await confirm_view.wait()

    if not confirm_view.confirmed:
        await msg.edit(embed=discord.Embed(
            title="❌ Cancelled",
            description="Your representation was not changed.",
            color=0x808080
        ), view=None)
        return

    # Save to old reps history
    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS old_representatives
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  player_name TEXT,
                  removed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute("INSERT INTO old_representatives (user_id, player_name) VALUES (?, ?)",
              (ctx.author.id, player_name))

    # ── Ghost OVR: snapshot bat/bowl OVR before wiping stats ──
    c.execute('''CREATE TABLE IF NOT EXISTS ovr_ghost_stats
                 (user_id INTEGER PRIMARY KEY,
                  bat_ovr INTEGER,
                  bowl_ovr INTEGER,
                  saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute("""
        SELECT SUM(runs), SUM(runs_conceded), SUM(balls_bowled),
               SUM(wickets), SUM(not_out), COUNT(*)
        FROM match_stats WHERE user_id = ?
    """, (ctx.author.id,))
    ghost_row = c.fetchone()
    if ghost_row and ghost_row[0] is not None and (ghost_row[5] or 0) >= 5:
        g_runs, g_rc, g_bb, g_wk, g_no, g_mp = ghost_row
        g_dis = g_mp - (g_no or 0)
        g_bat_avg = float(g_runs or 0) / g_dis if g_dis > 0 else float(g_runs or 0) / max(g_mp, 1)
        g_bat_ovr = calc_batting_ovr(g_bat_avg)
        if (g_bb or 0) >= 6:
            g_bowl_avg = float(g_rc or 0) / g_wk if (g_wk or 0) > 0 else 0.0
            g_bowl_ovr = calc_bowling_ovr(g_bowl_avg)
        else:
            g_bowl_ovr = None
        c.execute(
            "INSERT OR REPLACE INTO ovr_ghost_stats (user_id, bat_ovr, bowl_ovr) VALUES (?, ?, ?)",
            (ctx.author.id, g_bat_ovr, g_bowl_ovr)
        )

    # Reset displayed stats (OVR is preserved via ghost table above)
    c.execute("DELETE FROM match_stats WHERE user_id = ?", (ctx.author.id,))
    c.execute("DELETE FROM player_trophies WHERE user_id = ?", (ctx.author.id,))

    # Remove representation
    c.execute("DELETE FROM player_representatives WHERE user_id = ?", (ctx.author.id,))

    # Remove from captains if applicable
    c.execute("DELETE FROM team_captains WHERE player_name = ?", (player_name,))

    conn.commit()
    conn.close()

    _, team_names = find_player(player_name)
    if team_names:
        asyncio.get_event_loop().create_task(
            refresh_squad_image_cache(team_names[0], ctx.guild)
        )

    await msg.edit(embed=discord.Embed(
        title="✅ Done",
        description=(
            f"You are no longer representing **{player_name}**.\n"
            f"Your cricket stats and trophies have been reset.\n"
            f"Use `-represent` to claim a new player."
        ),
        color=0x00FF00
    ), view=None)

@bot.command(name="resetmanualstats", help="[ADMIN] Manually reset stats for a user or 'all' who changed players recently")
@is_staff_or_admin()
async def resetmanualstats_command(ctx, target: str):
    """Manually reset stats of a user or all users if they unrepped and switched in the last 5 days"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    five_days_ago = (datetime.utcnow() - timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S')

    if target.lower() == "all":
        # Find all users who unrepped in the last 5 days AND currently represent someone
        c.execute("""
            SELECT DISTINCT user_id 
            FROM old_representatives 
            WHERE removed_at > ? 
            AND user_id IN (SELECT user_id FROM player_representatives)
        """, (five_days_ago,))
        users = c.fetchall()

        if not users:
            await ctx.send("❌ No users found who unrepped in the last 5 days and currently represent a player.")
            conn.close()
            return

        confirm_embed = discord.Embed(
            title="⚠️ Confirm Bulk Manual Stats Reset",
            description=f"This will reset stats and trophies for **{len(users)}** users who switched players in the last 5 days.\n\n**This cannot be undone!**",
            color=0xFF0000
        )

        confirm_view = ConfirmationView()
        conf_msg = await ctx.send(embed=confirm_embed, view=confirm_view)
        await confirm_view.wait()

        if confirm_view.confirmed:
            reset_count = 0
            for (u_id,) in users:
                c.execute("DELETE FROM match_stats WHERE user_id = ?", (u_id,))
                c.execute("DELETE FROM player_trophies WHERE user_id = ?", (u_id,))
                reset_count += 1
            conn.commit()
            await conf_msg.edit(content=f"✅ Stats and trophies reset for {reset_count} users.", embed=None, view=None)
        else:
            await conf_msg.edit(content="❌ Bulk reset cancelled.", embed=None, view=None)

    else:
        # Handle single member
        try:
            member = await commands.MemberConverter().convert(ctx, target)
        except commands.MemberError:
            await ctx.send("❌ Invalid member provided. Use a mention, ID, or 'all'.")
            conn.close()
            return

        # Check if they unrepped in the last 5 days
        c.execute("SELECT player_name, removed_at FROM old_representatives WHERE user_id = ? AND removed_at > ? ORDER BY removed_at DESC LIMIT 1", 
                  (member.id, five_days_ago))
        last_unrep = c.fetchone()

        if not last_unrep:
            await ctx.send(f"❌ {member.display_name} has not unrepped a player in the last 5 days.")
            conn.close()
            return

        old_player, unrep_time = last_unrep

        # Check if they currently represent someone
        c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", (member.id,))
        current_rep = c.fetchone()

        if not current_rep:
            await ctx.send(f"❌ {member.display_name} currently does not represent any player. Use `-unrep` normally.")
            conn.close()
            return

        current_player = current_rep[0]

        # Confirmation
        confirm_embed = discord.Embed(
            title="⚠️ Confirm Manual Stats Reset",
            description=(
                f"User: {member.mention}\n"
                f"Old Player: **{old_player}** (Unrepped at {unrep_time})\n"
                f"Current Player: **{current_player}**\n\n"
                "This will permanently delete all match stats and trophies for this user."
            ),
            color=0xFF0000
        )

        confirm_view = ConfirmationView()
        conf_msg = await ctx.send(embed=confirm_embed, view=confirm_view)
        await confirm_view.wait()

        if confirm_view.confirmed:
            c.execute("DELETE FROM match_stats WHERE user_id = ?", (member.id,))
            c.execute("DELETE FROM player_trophies WHERE user_id = ?", (member.id,))
            conn.commit()
            await conf_msg.edit(content=f"✅ Stats and trophies reset for {member.mention}.", embed=None, view=None)
        else:
            await conf_msg.edit(content="❌ Reset cancelled.", embed=None, view=None)

    conn.close()

# Server IDs to upload emojis to
EMOJI_SERVERS = [
    840094596914741248,
    829450700764217366,
    902537846634733665,
    886642304335609937,
    823884737437368340,
    877275137009917992,
    848977887209979985,
    1159160118018056192
]

EXCLUDED_EMOJI_SERVER = 1451591563078533292

def get_emoji_guilds(bot_instance):
    """Return all guilds available for emoji storage (excludes the main server)."""
    return [g for g in bot_instance.guilds if g.id != EXCLUDED_EMOJI_SERVER]

# Store emoji mappings {player_name: emoji_id}
player_emojis = {}

def get_player_image_url(image_url):
    """Return a usable player image URL, using the default for missing images."""
    if image_url is None:
        return DEFAULT_PLAYER_IMAGE_URL

    if isinstance(image_url, str):
        cleaned_url = image_url.strip()
        if not cleaned_url or cleaned_url.upper() in {
                "NIL", "NONE", "NULL", "N/A", "NA"
        }:
            return DEFAULT_PLAYER_IMAGE_URL
        return cleaned_url

    return DEFAULT_PLAYER_IMAGE_URL

async def download_and_process_image(session, url, player_name):
    """Download player image and convert to emoji format (PNG, max 256KB)"""
    requested_url = get_player_image_url(url)
    urls_to_try = [requested_url]
    if requested_url != DEFAULT_PLAYER_IMAGE_URL:
        urls_to_try.append(DEFAULT_PLAYER_IMAGE_URL)

    for image_url in urls_to_try:
        try:
            async with session.get(image_url) as resp:
                if resp.status != 200:
                    continue

                image_data = await resp.read()
                img = Image.open(BytesIO(image_data))

                # Convert to RGBA if needed
                if img.mode != 'RGBA':
                    img = img.convert('RGBA')

                # Resize to 128x128 (Discord emoji recommended size)
                img = img.resize((128, 128), Image.Resampling.LANCZOS)

                # Save as PNG
                output = BytesIO()
                img.save(output, format='PNG', optimize=True)
                output.seek(0)

                # Check if under 256KB (Discord emoji limit)
                if output.getbuffer().nbytes > 256000:
                    img = img.resize((64, 64), Image.Resampling.LANCZOS)
                    output = BytesIO()
                    img.save(output, format='PNG', optimize=True)
                    output.seek(0)

                if image_url == DEFAULT_PLAYER_IMAGE_URL and requested_url != image_url:
                    print(
                        f"⚠️ Used default image for {player_name}; "
                        "the listed image could not be downloaded."
                    )
                return output
        except Exception as exc:
            print(f"⚠️ Error processing image for {player_name} from {image_url}: {exc}")

    print(f"❌ Could not process any image for {player_name}")
    return None

async def upload_emojis_to_servers(bot):
    """Upload player emojis to all servers the bot is in (except the main server)."""
    teams_data = load_players()

    # Collect all players
    all_players = []
    for team_data in teams_data:
        for player in team_data['players']:
            all_players.append({
                'name': player['name'],
                'image': get_player_image_url(player.get('image')),
                'team': team_data['team']
            })

    print(f"📊 Total players to process: {len(all_players)}")

    # Get all available guilds except the excluded main server
    emoji_guilds = get_emoji_guilds(bot)

    # Distribute players across servers (50 per server)
    emojis_per_server = 50
    server_index = 0

    async with aiohttp.ClientSession() as session:
        for i in range(0, len(all_players), emojis_per_server):
            if server_index >= len(emoji_guilds):
                print("⚠️ Not enough servers to upload all emojis!")
                break

            guild = emoji_guilds[server_index]

            if not guild:
                server_index += 1
                continue

            print(f"📤 Uploading to server: {guild.name} ({guild.id})")

            # Get batch of players for this server
            batch = all_players[i:i + emojis_per_server]

            for player in batch:
                try:
                    # Create emoji name (alphanumeric + underscores only, max 32 chars)
                    emoji_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in player['name'])
                    emoji_name = emoji_name[:32]

                    # Check if emoji already exists
                    existing_emoji = discord.utils.get(
                        guild.emojis, 
                        name=emoji_name
                    )

                    if existing_emoji:
                        player_emojis[player['name']] = existing_emoji.id
                        print(f"✅ Emoji already exists: {player['name']}")
                        continue

                    # Download and process image
                    image_data = await download_and_process_image(
                        session,
                        get_player_image_url(player.get('image')),
                        player['name']
                    )

                    if not image_data:
                        print(f"❌ Failed to process image for {player['name']}")
                        continue

                    # Upload emoji to server
                    emoji = await guild.create_custom_emoji(
                        name=emoji_name,
                        image=image_data.read()
                    )

                    player_emojis[player['name']] = emoji.id
                    print(f"✅ Uploaded emoji: {player['name']} (ID: {emoji.id})")

                    # Rate limit: wait between uploads
                    await asyncio.sleep(2)

                except discord.errors.HTTPException as e:
                    if e.code == 30008:  # Maximum number of emojis reached
                        print(f"⚠️ Server {guild.name} reached emoji limit")
                        break
                    else:
                        print(f"❌ HTTP error uploading {player['name']}: {e}")
                except Exception as e:
                    print(f"❌ Error uploading {player['name']}: {e}")

            server_index += 1
            print(f"✅ Completed server {guild.name}")

    # Save emoji mappings to file
    with open('player_emojis.json', 'w') as f:
        json.dump(player_emojis, f, indent=2)

    print(f"✅ Upload complete! {len(player_emojis)} emojis uploaded")
    return player_emojis

def load_emoji_mappings():
    """Load emoji mappings from file"""
    try:
        with open('player_emojis.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def get_player_emoji(player_name, bot=None):
    """Get emoji format for a player"""
    if not bot:
        return "👤"

    # Create the expected emoji name format
    emoji_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in player_name)[:32]

    # Search for emoji across all available guilds (except excluded main server)
    for guild in get_emoji_guilds(bot):
        if guild:
            # Try to find emoji by name
            emoji_obj = discord.utils.get(guild.emojis, name=emoji_name)
            if emoji_obj:
                return str(emoji_obj)  # Returns <:emoji_name:emoji_id>

    # Fallback if emoji not found
    return "👤"

# Add command to trigger emoji upload
@bot.command(name="uploademojis", aliases=["ue"])
@is_staff_or_admin()
async def upload_emojis_command(ctx):
    """[ADMIN] Upload player emojis to designated servers"""
    await ctx.send("🔄 Starting emoji upload process... This will take several minutes.")

    try:
        emojis = await upload_emojis_to_servers(bot)
        await ctx.send(f"✅ Emoji upload complete! {len(emojis)} players now have emojis.")
    except Exception as e:
        await ctx.send(f"❌ Error during upload: {e}")

@bot.command(
    name="playersemojissync",
    help="[ADMIN] Check every player for a custom emoji and upload missing emojis"
)
@commands.has_permissions(administrator=True)
async def players_emojis_sync_command(ctx):
    """Audit and repair custom player emojis for every player."""
    await ctx.send(
        "🔄 Starting player emoji sync. "
        "I’ll check every player and upload only missing emojis."
    )

    try:
        # Read the raw file so missing image values can be persisted as the
        # requested default URL, not just replaced in memory.
        with open('players.json', 'r', encoding='utf-8') as players_file:
            teams_data = json.load(players_file)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        await ctx.send(f"❌ Could not load players.json: {exc}")
        return

    all_players = []
    default_image_players = []
    for team_data in teams_data:
        for player in team_data.get('players', []):
            original_image = player.get('image')
            usable_image = get_player_image_url(original_image)
            if usable_image != original_image:
                player['image'] = usable_image
                default_image_players.append(player['name'])
            all_players.append({
                'name': player['name'],
                'image': usable_image,
                'team': team_data.get('team', 'Unknown')
            })

    if not all_players:
        await ctx.send("❌ No players found in players.json.")
        return

    # Persist replacements for null/blank/NIL image values so every other
    # feature that reads players.json sees the same usable image URL.
    if default_image_players:
        try:
            with open('players.json', 'w', encoding='utf-8') as players_file:
                json.dump(teams_data, players_file, indent=2, ensure_ascii=False)
        except OSError as exc:
            await ctx.send(f"⚠️ Could not save default player images: {exc}")

    emoji_guilds = get_emoji_guilds(bot)
    if not emoji_guilds:
        await ctx.send("❌ No emoji-storage servers are available.")
        return

    # Build one authoritative view from Discord itself. The JSON file can be
    # stale after an emoji is deleted or moved, so it is never used as the
    # existence check.
    emojis_by_name = {}
    for guild in emoji_guilds:
        for emoji in guild.emojis:
            emojis_by_name.setdefault(emoji.name, (emoji, guild))

    mappings = load_emoji_mappings()
    existing_count = 0
    uploaded_count = 0
    mapping_repaired_count = 0
    default_count = len(default_image_players)
    full_count = 0
    failed = []

    async def find_available_guild():
        for candidate in emoji_guilds:
            if len(candidate.emojis) < candidate.emoji_limit:
                return candidate
        return None

    await ctx.send(
        f"📊 Auditing **{len(all_players)}** players across "
        f"**{len(emoji_guilds)}** emoji server(s)..."
    )

    async with aiohttp.ClientSession() as session:
        for index, player in enumerate(all_players, 1):
            player_name = player['name']
            emoji_name = ''.join(
                c if c.isalnum() or c == '_' else '_'
                for c in player_name
            )[:32]

            # Existing emoji: repair the mapping if needed, but do not upload
            # a duplicate.
            existing = emojis_by_name.get(emoji_name)
            if existing:
                emoji_obj, _guild = existing
                if mappings.get(player_name) != emoji_obj.id:
                    mappings[player_name] = emoji_obj.id
                    mapping_repaired_count += 1
                existing_count += 1
                continue

            target_guild = await find_available_guild()
            if not target_guild:
                full_count += 1
                failed.append(f"{player_name} — all emoji servers are full")
                continue

            image_data = await download_and_process_image(
                session,
                player['image'],
                player_name
            )
            if not image_data:
                failed.append(f"{player_name} — image could not be downloaded")
                continue

            try:
                emoji_obj = await target_guild.create_custom_emoji(
                    name=emoji_name,
                    image=image_data.read(),
                    reason=f"Player emoji sync by {ctx.author}"
                )
                mappings[player_name] = emoji_obj.id
                emojis_by_name[emoji_name] = (emoji_obj, target_guild)
                uploaded_count += 1
                await asyncio.sleep(2)
            except discord.Forbidden:
                failed.append(f"{player_name} — no permission in {target_guild.name}")
            except discord.HTTPException as exc:
                if exc.code == 30008:
                    full_count += 1
                    failed.append(f"{player_name} — {target_guild.name} became full")
                else:
                    failed.append(f"{player_name} — Discord HTTP error {exc}")
            except Exception as exc:
                failed.append(f"{player_name} — {exc}")

            if index % 25 == 0:
                await ctx.send(
                    f"⏳ Progress: **{index}/{len(all_players)}** checked "
                    f"• **{uploaded_count}** uploaded"
                )

    player_emojis.clear()
    player_emojis.update(mappings)
    try:
        with open('player_emojis.json', 'w', encoding='utf-8') as emoji_file:
            json.dump(mappings, emoji_file, indent=2)
    except OSError as exc:
        failed.append(f"Could not save player_emojis.json — {exc}")

    summary = (
        f"✅ Existing emojis: **{existing_count}**\n"
        f"🆕 Uploaded: **{uploaded_count}**\n"
        f"🔧 Mappings repaired: **{mapping_repaired_count}**\n"
        f"🏝️ Default image used: **{default_count}**\n"
        f"🚫 Servers full: **{full_count}**\n"
        f"❌ Failed: **{len(failed)}**"
    )
    embed = discord.Embed(
        title="✅ Player Emoji Sync Complete",
        description=summary,
        color=0x00A86B if not failed else 0xFFA500
    )
    if failed:
        failure_text = "\n".join(f"• {item}" for item in failed[:15])
        if len(failed) > 15:
            failure_text += f"\n…and {len(failed) - 15} more."
        embed.add_field(name="Issues", value=failure_text, inline=False)
    embed.set_footer(text=f"Synced by {ctx.author}")
    await ctx.send(embed=embed)

# Update playerlist command to use emojis
@bot.command(name="playerlist", aliases=["pl"], help="View all players in a paginated list")
async def playerlist_command(ctx):
    teams_data = load_players()

    if not teams_data:
        await ctx.send("❌ No player data available.")
        return

    # Create pages (10 players per page)
    all_players = []
    for team_data in teams_data:
        for player in team_data['players']:
            rep_info = get_representative(player['name'])
            rep_text = f"@{rep_info[1]}" if rep_info else "Unclaimed"
            all_players.append({
                'name': player['name'],
                'team': team_data['team'],
                'role': player['role'],
                'representative': rep_text
            })

    players_per_page = 10
    pages = []

    for i in range(0, len(all_players), players_per_page):
        page_players = all_players[i:i + players_per_page]

        embed = discord.Embed(
            title="All Nation Players",
            color=0x0066CC
        )

        description = ""
        for idx, player in enumerate(page_players, start=i+1):
            flag = get_team_flag(player['team'])
            role_emoji = get_role_emoji(player['role'])
            emoji = get_player_emoji(player['name'], bot)

            # Format: 1. [emoji] · 🇮🇳 · Rohit Sharma · 🏏
            description += f"**{idx}.** {emoji} · {flag} · **{player['name']}** · {role_emoji}\n"
            description += f"    └ *{player['team']}* • {player['representative']}\n\n"

        embed.description = description
        embed.set_footer(
            text=f"Page {len(pages)+1}/{(len(all_players)-1)//players_per_page + 1} • Total Players: {len(all_players)}"
        )
        pages.append(embed)

    if len(pages) == 1:
        await ctx.send(embed=pages[0])
    else:
        view = PlayerListView(pages, ctx)
        view.message = await ctx.send(embed=pages[0], view=view)


@bot.command(
    name="cachesquadimage",
    help="[OWNER] Build/cache all current squad images",
)
async def cachesquadimage_command(ctx):
    """Build every current squad image and upload it to the squad cache."""
    if ctx.author.id != SQUAD_CACHE_OWNER_ID:
        return

    teams_data = load_players()
    if not teams_data:
        await ctx.send("❌ No player data available.")
        return

    cache_channel = bot.get_channel(SQUAD_CACHE_CHANNEL_ID)
    if not cache_channel:
        await ctx.send("❌ Squad cache channel is unavailable.")
        return

    status = await ctx.send(
        f"⏳ Caching **{len(teams_data)}** squad images..."
    )
    cache = await scan_squad_image_cache(bot)
    uploaded = 0
    skipped = 0
    failed = []

    for team_data in teams_data:
        team_name = team_data["team"]
        fingerprint = squad_cache_fingerprint(team_data, ctx.guild)
        cached = cache.get(team_name.lower())
        if cached and cached["hash"] == fingerprint:
            skipped += 1
            continue

        try:
            image_bytes = await create_squad_image(
                team_name,
                team_data,
                ctx.guild,
            )
            if not image_bytes:
                failed.append(f"{team_name}: image generation returned nothing")
                continue

            version = (cached["version"] + 1) if cached else 1
            message = await post_squad_image_to_cache(
                bot,
                team_name,
                fingerprint,
                image_bytes,
                version=version,
            )
            if message:
                uploaded += 1
                cache[team_name.lower()] = {
                    "team_name": team_name,
                    "hash": fingerprint,
                    "version": version,
                    "message_id": message.id,
                    "url": message.attachments[0].url,
                }
            else:
                failed.append(f"{team_name}: cache channel unavailable")
        except Exception as exc:
            failed.append(f"{team_name}: {exc}")

    summary = (
        f"✅ Uploaded/updated: **{uploaded}**\n"
        f"⏭️ Already current: **{skipped}**\n"
        f"❌ Failed: **{len(failed)}**"
    )
    embed = discord.Embed(
        title="🏏 Squad Image Cache Complete",
        description=summary,
        color=0x00A86B if not failed else 0xFFA500,
    )
    if failed:
        embed.add_field(
            name="Issues",
            value="\n".join(f"• {item}" for item in failed[:15]),
            inline=False,
        )
    await status.edit(content=None, embed=embed)


@bot.command(name="viewteam", aliases=["vt"], help="View all players in a specific team")
async def viewteam_command(ctx, *, team_name: str):
    # Send loading message
    loading_msg = await ctx.send("⏳ Loading squad info...")

    teams_data = load_players()
    if not teams_data:
        await loading_msg.delete()
        await ctx.send("❌ No player data available.")
        return

    # Find the team
    team_data = None
    for t in teams_data:
        if t['team'].lower() == team_name.lower():
            team_data = t
            break

    if not team_data:
        await loading_msg.delete()
        available_teams = ", ".join([t['team'] for t in teams_data])
        await ctx.send(f"❌ Team '{team_name}' not found.\n\n**Available teams:** {available_teams}")
        return

    # Use the cached image whenever the current squad fingerprint matches.
    # A changed roster/claim/avatar/captain causes a new version to be built
    # and uploaded before the result is shown.
    squad_fingerprint = squad_cache_fingerprint(team_data, ctx.guild)
    squad_cache = await scan_squad_image_cache(bot)
    cached_squad = squad_cache.get(team_data["team"].lower())
    squad_image = None
    cached_squad_url = None
    if cached_squad and cached_squad["hash"] == squad_fingerprint:
        cached_squad_url = cached_squad["url"]
    else:
        squad_image = await create_squad_image(
            team_data['team'],
            team_data,
            ctx.guild,
        )
        if squad_image:
            version = (cached_squad["version"] + 1) if cached_squad else 1
            try:
                cached_message = await post_squad_image_to_cache(
                    bot,
                    team_data["team"],
                    squad_fingerprint,
                    squad_image,
                    version=version,
                )
                if cached_message:
                    cached_squad_url = cached_message.attachments[0].url
                    squad_image = None
            except (discord.Forbidden, discord.HTTPException) as exc:
                print(f"[SquadCache] Could not cache {team_data['team']}: {exc}")

    flag = get_team_flag(team_data['team'])
    flag_url = get_team_flag_url(team_data['team'])

    # Get team captain
    captain_name = get_team_captain(team_data['team'])

    # Compute OVR for every player in the squad, use top 12 for team OVR
    all_player_ovrs = []

    vice_captain_name = get_team_vice_captain(team_data['team'])

    for player in team_data['players']:
        rep_info = get_representative(player['name'])
        if rep_info:
            p_ovr = get_player_ovr_for_vt(rep_info[0], player['role'])
        else:
            p_ovr = None
        all_player_ovrs.append(p_ovr if p_ovr is not None else 60)

    top12_ovrs = sorted(all_player_ovrs, reverse=True)[:12]
    team_avg_ovr = round(sum(top12_ovrs) / len(top12_ovrs)) if top12_ovrs else 60

    embed = discord.Embed(
        title=f"{flag} Official {team_data['team']} Squad · {team_avg_ovr} OVR",
        color=get_team_color(team_data['team'])
    )

    # Set the cached squad image as the main embed image.
    if cached_squad_url:
        embed.set_image(url=cached_squad_url)
    elif squad_image:
        file = discord.File(squad_image, filename="squad.png")
        embed.set_image(url="attachment://squad.png")

    # Set flag as thumbnail
    if flag_url:
        embed.set_thumbnail(url=flag_url)

    # Categorize players by role
    batsmen = []
    bowlers = []
    allrounders = []
    wicketkeepers = []

    for player in team_data['players']:
        rep_info = get_representative(player['name'])
        rep_text = f"**@{rep_info[1]}**" if rep_info else "*Unclaimed*"
        emoji = get_player_emoji(player['name'], bot)

        # Player OVR
        if rep_info:
            p_ovr = get_player_ovr_for_vt(rep_info[0], player['role'])
        else:
            p_ovr = None
        ovr_display = str(p_ovr) if p_ovr is not None else "NIL"

        # Add (C) if this player is the captain and (VC) if they are vice-captain
        captain_badge = " **(C)**" if player['name'] == captain_name else ""
        vice_captain_badge = " **(VC)**" if player['name'] == vice_captain_name else ""

        # Format: [emoji] · Player Name (C) · @rep · OVR OVR
        player_line = f"{emoji} · {player['name']}{captain_badge}{vice_captain_badge} · {rep_text} · {ovr_display} OVR"

        if "Wicketkeeper" in player['role']:
            wicketkeepers.append(player_line)
        elif "Batsman" in player['role']:
            batsmen.append(player_line)
        elif "Bowler" in player['role']:
            bowlers.append(player_line)
        elif "All-Rounder" in player['role'] or "All-rounder" in player['role']:
            allrounders.append(player_line)

    # Add fields for each category
    if wicketkeepers:
        embed.add_field(
            name=f"<:wicketkeeper:1451994159668920330> Wicketkeepers ({len(wicketkeepers)})",
            value="\n".join(wicketkeepers),
            inline=False
        )

    if batsmen:
        embed.add_field(
            name=f"<:bat:1451967322146213980> Batsmen ({len(batsmen)})",
            value="\n".join(batsmen),
            inline=False
        )

    if allrounders:
        embed.add_field(
            name=f"<:allrounder:1451978476033671279> All-Rounders ({len(allrounders)})",
            value="\n".join(allrounders),
            inline=False
        )

    if bowlers:
        embed.add_field(
            name=f"<:ball:1451974295793172547> Bowlers ({len(bowlers)})",
            value="\n".join(bowlers),
            inline=False
        )

    total_players = len(team_data['players'])
    claimed = sum(1 for p in team_data['players'] if get_representative(p['name']))
    footer_text = f"Total Players: {total_players} • Claimed: {claimed} • Unclaimed: {total_players - claimed}"
    if captain_name:
        footer_text += f" • Captain: {captain_name}"

    embed.set_footer(text=footer_text)

    # Delete loading message and send with the squad image file if available
    await loading_msg.delete()

    if squad_image:
        await ctx.send(embed=embed, file=file)
    else:
        await ctx.send(embed=embed)
#-----------------

@bot.command(name="squadimage", aliases=["is"], help="View all players in a specific team")
async def viewteam_command(ctx, *, team_name: str):
    teams_data = load_players()

    if not teams_data:
        await ctx.send("❌ No player data available.")
        return

    # Remove quotes if present
    team_name = team_name.strip('"')

    # Find the team
    team_data = None
    for t in teams_data:
        if t['team'].lower() == team_name.lower():
            team_data = t
            team_name = t['team']  # Use exact team name
            break

    if not team_data:
        available_teams = ", ".join([t['team'] for t in teams_data])
        await ctx.send(f"❌ Team '{team_name}' not found.\n\n**Available teams:** {available_teams}")
        return

    # Send loading message
    loading_msg = await ctx.send("🏏 Generating squad image...")

    try:
        # Generate squad image
        image_bytes = await create_squad_image(team_name, team_data, ctx.guild)

        # Create embed
        flag = get_team_flag(team_name)
        embed = discord.Embed(
            title=f"{flag} Official {team_name} Squad",
            color=get_team_color(team_name)
        )

        # Attach image
        file = discord.File(fp=image_bytes, filename=f"{team_name}_squad.png")
        embed.set_image(url=f"attachment://{team_name}_squad.png")

        # Add footer
        total_players = len(team_data['players'])
        claimed = sum(1 for p in team_data['players'] if get_representative(p['name']))
        captain_name = get_team_captain(team_name)

        footer_text = f"Total: {total_players} • Claimed: {claimed} • Unclaimed: {total_players - claimed}"
        if captain_name:
            footer_text += f" • Captain: {captain_name}"

        embed.set_footer(text=footer_text)

        # Delete loading message and send result
        await loading_msg.delete()
        await ctx.send(embed=embed, file=file)

    except Exception as e:
        await loading_msg.edit(content=f"❌ Error generating squad image: {e}")
        print(f"Squad image error: {e}")

# Command to check emoji status
@bot.command(name="checkemojis", aliases=["ce"])
@is_staff_or_admin()
async def check_emojis_command(ctx):
    """[ADMIN] Check how many emojis are uploaded"""
    player_emojis = load_emoji_mappings()
    teams_data = load_players()

    total_players = sum(len(team['players']) for team in teams_data)
    uploaded = len(player_emojis)

    embed = discord.Embed(
        title="📊 Emoji Upload Status",
        color=0x0066CC
    )

    embed.add_field(
        name="Progress",
        value=f"**{uploaded}** / **{total_players}** players have emojis\n"
              f"({(uploaded/total_players*100):.1f}% complete)",
        inline=False
    )

    # Check each server's emoji count
    for guild in get_emoji_guilds(bot):
        emoji_count = len(guild.emojis)
        emoji_limit = guild.emoji_limit
        embed.add_field(
            name=f"{guild.name}",
            value=f"{emoji_count}/{emoji_limit} emojis",
            inline=True
        )

    await ctx.send(embed=embed)

# Debug command to test emoji retrieval
@bot.command(name="testemoji", aliases=["te"])
@is_staff_or_admin()
async def test_emoji_command(ctx, *, player_name: str):
    """[ADMIN] Test emoji retrieval for a specific player"""
    emoji = get_player_emoji(player_name, bot)

    # Also check all servers
    found_emojis = []
    emoji_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in player_name)[:32]

    for guild in get_emoji_guilds(bot):
        emoji_obj = discord.utils.get(guild.emojis, name=emoji_name)
        if emoji_obj:
            found_emojis.append(f"{guild.name}: {emoji_obj} (ID: {emoji_obj.id})")

    embed = discord.Embed(
        title=f"Emoji Test: {player_name}",
        color=0x0066CC
    )

    embed.add_field(
        name="Searched Name",
        value=f"`{emoji_name}`",
        inline=False
    )

    embed.add_field(
        name="Result",
        value=f"{emoji} (This is what shows in embeds)",
        inline=False
    )

    if found_emojis:
        embed.add_field(
            name="Found in Servers",
            value="\n".join(found_emojis),
            inline=False
        )
    else:
        embed.add_field(
            name="Found in Servers",
            value="❌ No emoji found with this name",
            inline=False
        )

    await ctx.send(embed=embed)

# Command to list all emojis in emoji servers
@bot.command(name="listemojis", aliases=["le"])
@is_staff_or_admin()
async def list_emojis_command(ctx, server_index: int = 0):
    """[ADMIN] List all emojis in a specific emoji server"""
    emoji_guilds = get_emoji_guilds(bot)
    if server_index >= len(emoji_guilds):
        await ctx.send(f"❌ Server index must be between 0 and {len(emoji_guilds)-1}")
        return

    guild = emoji_guilds[server_index]

    emojis = guild.emojis

    embed = discord.Embed(
        title=f"Emojis in {guild.name}",
        description=f"Total: {len(emojis)}/{guild.emoji_limit}",
        color=0x0066CC
    )

    # Show first 25 emojis as example
    emoji_list = []
    for emoji in emojis[:25]:
        emoji_list.append(f"{emoji} `:{emoji.name}:` (ID: {emoji.id})")

    if emoji_list:
        embed.add_field(
            name="Sample Emojis",
            value="\n".join(emoji_list),
            inline=False
        )

    if len(emojis) > 25:
        embed.set_footer(text=f"Showing first 25 of {len(emojis)} emojis")

    await ctx.send(embed=embed)

# Elite players storage
elite_players = set()

def load_elite_players():
    """Load elite players from file"""
    try:
        with open('elite_players.json', 'r') as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()

def save_elite_players():
    """Save elite players to file"""
    with open('elite_players.json', 'w') as f:
        json.dump(list(elite_players), f, indent=2)

def is_elite_player(player_name):
    """Check if a player is marked as elite"""
    return player_name in elite_players

def get_player_emoji_with_elite(player_name, bot=None):
    """Get emoji for a player, using elite emoji if applicable"""
    if is_elite_player(player_name):
        return "<:elite:1452949859412738110>"
    return get_player_emoji(player_name, bot)

@bot.command(name="elite", aliases=["e"], help="[ADMIN] Mark players as elite and create auction threads")
@is_staff_or_admin()
async def elite_command(ctx, *, players: str):
    """
    Mark players as elite and create auction threads
    Usage: -elite player1, player2, player3
    """
    # Parse player names (split by comma)
    player_names = [name.strip() for name in players.split(',')]

    if not player_names:
        await ctx.send("❌ Please provide at least one player name.\nUsage: `-elite player1, player2, player3`")
        return

    # Get the auction channel
    auction_channel = bot.get_channel(1516051222136623104)
    if not auction_channel:
        await ctx.send("❌ Auction channel not found!")
        return

    success_count = 0
    failed_players = []
    created_threads = []

    for player_name in player_names:
        # Find the player
        found_players, team_names = find_player(player_name)

        if not found_players:
            failed_players.append(f"{player_name} (not found)")
            continue

        if len(found_players) > 1:
            failed_players.append(f"{player_name} (multiple matches - be more specific)")
            continue

        player = found_players[0]
        team_name = team_names[0]

        # Mark as elite
        elite_players.add(player['name'])

        # Create auction thread
        try:
            thread = await auction_channel.create_thread(
                name=f"{player['name']}",
                type=discord.ChannelType.public_thread,
                reason=f"Elite player auction created by {ctx.author}"
            )

            # Send auction rules in the thread
            auction_message = (
                "**RULES\n"
                "> - INCREASE BY 100K EVERYTIME (E.G 100K --> 200K)\n"
                ">                                                            (E.G 1.1M - 1.2M)\n"
                "> \n"
                "> - TROLLING / MESSING AROUND -> INSTANT BAN\n"
                "> \n"
                "> - AUCTION ENDS AT 30TH DECEMBER \n"
                "> - / / HOWEVER IF NO ONE BIDS FOR 3 DAYS -> LAST HIGHER BIDDER GETS THE PLAYER **\n"
                "*SEND YOUR BID AS A MESSAGE AFTER A PERSON E.G 200K, PAYMENT WILL BE COLLECTED IN THE END IF YOU WIN*\n"
                "__**BASE PRICE 100K**__"
            )

            await thread.send(auction_message)

            success_count += 1
            created_threads.append(f"{player['name']} ({team_name})")

        except discord.HTTPException as e:
            failed_players.append(f"{player['name']} (thread creation failed: {e})")

    # Save elite players to file
    save_elite_players()

    # Send confirmation message
    embed = discord.Embed(
        title="<:elite:1452949859412738110> Elite Players Marked",
        color=0xFFD700
    )

    if success_count > 0:
        embed.add_field(
            name=f"✅ Successfully Created ({success_count})",
            value="\n".join([f"• {p}" for p in created_threads]),
            inline=False
        )

    if failed_players:
        embed.add_field(
            name=f"❌ Failed ({len(failed_players)})",
            value="\n".join([f"• {p}" for p in failed_players]),
            inline=False
        )

    embed.set_footer(text="Elite players will now show the elite emoji in dropdowns")

    await ctx.send(embed=embed)

@bot.command(name="unelite", aliases=["une"], help="[ADMIN] Remove elite status from players")
@is_staff_or_admin()
async def unelite_command(ctx, *, players: str):
    """
    Remove elite status from players
    Usage: -unelite player1, player2, player3
           -unelite all
    """
    if players.strip().lower() == "all":
        count = len(elite_players)
        if count == 0:
            await ctx.send("❌ There are no elite players to remove.")
            return
        elite_players.clear()
        save_elite_players()
        embed = discord.Embed(
            title="Elite Status Removed",
            description=f"✅ Removed elite status from all **{count}** player(s).",
            color=0x808080
        )
        embed.set_footer(text=f"Done by {ctx.author}")
        await ctx.send(embed=embed)
        return

    player_names = [name.strip() for name in players.split(',')]

    if not player_names:
        await ctx.send("❌ Please provide at least one player name.")
        return

    removed = []
    not_found = []

    for player_name in player_names:
        found_players, _ = find_player(player_name)

        if not found_players:
            not_found.append(player_name)
            continue

        if len(found_players) > 1:
            not_found.append(f"{player_name} (multiple matches)")
            continue

        player = found_players[0]

        if player['name'] in elite_players:
            elite_players.remove(player['name'])
            removed.append(player['name'])
        else:
            not_found.append(f"{player['name']} (not elite)")

    save_elite_players()

    embed = discord.Embed(
        title="Elite Status Removed",
        color=0x808080
    )

    if removed:
        embed.add_field(
            name="✅ Removed",
            value="\n".join([f"• {p}" for p in removed]),
            inline=False
        )

    if not_found:
        embed.add_field(
            name="❌ Not Removed",
            value="\n".join([f"• {p}" for p in not_found]),
            inline=False
        )

    await ctx.send(embed=embed)

@bot.command(name="listelite", aliases=["lse"], help="List all elite players")
async def listelite_command(ctx):
    """List all players marked as elite"""
    if not elite_players:
        await ctx.send("❌ No elite players have been marked yet.")
        return

    embed = discord.Embed(
        title="<:elite:1452949859412738110> Elite Players",
        description=f"Total: {len(elite_players)} players",
        color=0xFFD700
    )

    # Group by team
    teams_data = load_players()
    elite_by_team = {}

    for player_name in elite_players:
        found_players, team_names = find_player(player_name)
        if found_players:
            team = team_names[0]
            if team not in elite_by_team:
                elite_by_team[team] = []
            elite_by_team[team].append(player_name)

    for team, players_list in sorted(elite_by_team.items()):
        flag = get_team_flag(team)
        embed.add_field(
            name=f"{flag} {team}",
            value="\n".join([f"• {p}" for p in players_list]),
            inline=True
        )

    await ctx.send(embed=embed)

@bot.command(name="removeemojis", aliases=["re"])
@is_staff_or_admin()
async def remove_emojis_command(ctx):
    """[ADMIN] Remove all player emojis from designated servers"""
    await ctx.send("🔄 Starting emoji removal process... This may take a few minutes.")

    removed_count = 0
    failed_count = 0

    try:
        # Load current emoji mappings
        player_emojis = load_emoji_mappings()

        if not player_emojis:
            await ctx.send("❌ No emoji mappings found. Nothing to remove.")
            return

        # Iterate through all available guilds (except excluded main server)
        for guild in get_emoji_guilds(bot):
            print(f"🗑️ Removing emojis from: {guild.name} ({guild.id})")

            # Get all emojis in this server
            for emoji in guild.emojis:
                try:
                    # Check if this emoji name matches any player emoji format
                    # (player emojis are alphanumeric with underscores)
                    if any(emoji.name == ''.join(c if c.isalnum() or c == '_' else '_' for c in player_name)[:32] 
                           for player_name in player_emojis.keys()):
                        await emoji.delete(reason=f"Player emoji removal by {ctx.author}")
                        removed_count += 1
                        print(f"✅ Deleted emoji: {emoji.name}")

                        # Rate limit: wait between deletions
                        await asyncio.sleep(1)

                except discord.errors.HTTPException as e:
                    print(f"❌ HTTP error deleting {emoji.name}: {e}")
                    failed_count += 1
                except Exception as e:
                    print(f"❌ Error deleting {emoji.name}: {e}")
                    failed_count += 1

            print(f"✅ Completed server {guild.name}")

        # Clear the emoji mappings file
        with open('player_emojis.json', 'w') as f:
            json.dump({}, f, indent=2)

        # Clear the in-memory dictionary
        player_emojis.clear()

        # Send completion message
        embed = discord.Embed(
            title="🗑️ Emoji Removal Complete",
            color=0xFF0000
        )

        embed.add_field(
            name="Results",
            value=f"✅ **Removed:** {removed_count} emojis\n"
                  f"❌ **Failed:** {failed_count} emojis",
            inline=False
        )

        embed.set_footer(text="player_emojis.json has been cleared")

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error during removal: {e}")
        print(f"❌ Error during emoji removal: {e}")

@bot.command(name="syncleft", help="[ADMIN] Unclaim players whose representatives have left the server")
@is_staff_or_admin()
async def sync_left_command(ctx):
    await ctx.send("🔄 Checking for representatives who left the server...")

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Fetch all current claims
    c.execute("SELECT player_name, user_id FROM player_representatives")
    all_claims = c.fetchall()

    removed_count = 0
    removed_list = []
    affected_teams = set()

    for player_name, user_id in all_claims:
        # ctx.guild.get_member relies on the member cache (requires intents.members = True)
        member = ctx.guild.get_member(user_id)

        # If member is None, they are likely not in the server anymore
        if member is None:
            _, team_names = find_player(player_name)
            if team_names:
                affected_teams.add(team_names[0])
            # Remove from representatives
            c.execute("DELETE FROM player_representatives WHERE player_name = ?", (player_name,))

            # Remove from captains if they were one
            c.execute("DELETE FROM team_captains WHERE player_name = ?", (player_name,))
            c.execute("DELETE FROM team_vice_captains WHERE player_name = ?", (player_name,))

            removed_list.append(player_name)
            removed_count += 1

    conn.commit()
    conn.close()

    for affected_team in affected_teams:
        asyncio.get_event_loop().create_task(
            refresh_squad_image_cache(affected_team, ctx.guild)
        )

    if removed_count > 0:
        # Create summary embed
        embed = discord.Embed(title="🗑️ Sync Left Complete", color=0xFF0000)

        # Chunk list if too long for description
        description = "\n".join([f"• {p}" for p in removed_list[:50]])
        if len(removed_list) > 50:
            description += f"\n...and {len(removed_list) - 50} more."

        embed.description = f"**{removed_count}** players were unclaimed because their representatives left the server.\n\n{description}"
        await ctx.send(embed=embed)
    else:
        await ctx.send("✅ All current representatives are still in the server.")

@bot.command(name="setcaptain", aliases=["sc"], help="[ADMIN] Set a player as team captain")
@is_staff_or_admin()
async def setcaptain_command(ctx, team_name: str, *, username: str):
    """
    Set a team captain
    Usage: -setcaptain India @username or -setcaptain India username
    """
    # Remove @ if present
    username = username.lstrip('@')

    # Find the team
    teams_data = load_players()
    team_data = None
    for t in teams_data:
        if t['team'].lower() == team_name.lower():
            team_data = t
            break

    if not team_data:
        available_teams = ", ".join([t['team'] for t in teams_data])
        await ctx.send(f"❌ Team '{team_name}' not found.\n\n**Available teams:** {available_teams}")
        return

    # Keep synchronous SQLite work off Discord's event loop. In particular,
    # commit() can wait on SQLite's busy timeout when another command writes.
    result = await asyncio.to_thread(
        get_player_representative_by_username,
        username,
    )

    if not result:
        await ctx.send(f"❌ No player representative found with username `{username}`.\nMake sure they have claimed a player first.")
        return

    player_name, user_id = result

    # Verify the player is from the specified team
    players, team_names = find_player(player_name)
    if not players or team_names[0] != team_data['team']:
        await ctx.send(f"❌ **{player_name}** (represented by @{username}) is not from **{team_data['team']}**!")
        return

    # Set as captain off the event loop; the shared SQLite retry/timeout layer
    # may wait briefly for another writer to finish.
    await asyncio.to_thread(
        set_team_captain,
        team_data['team'],
        player_name,
        user_id,
        username,
    )
    asyncio.get_event_loop().create_task(
        refresh_squad_image_cache(team_data['team'], ctx.guild)
    )

    flag = get_team_flag(team_data['team'])
    embed = discord.Embed(
        title=f"👑 Captain Appointed",
        description=f"{flag} **{player_name}** (@{username}) is now the captain of **{team_data['team']}**!",
        color=get_team_color(team_data['team'])
    )

    # Get player data for image
    player = players[0]
    embed.set_thumbnail(url=player['image'])
    embed.set_footer(text=f"Set by {ctx.author.name}")
    embed.timestamp = discord.utils.utcnow()

    await ctx.send(embed=embed)

@bot.command(name="removecaptain", aliases=["rc"], help="[ADMIN] Remove captain from a team")
@is_staff_or_admin()
async def removecaptain_command(ctx, *, team_name: str):
    """
    Remove a team's captain
    Usage: -removecaptain India
    """
    # Find the team
    teams_data = load_players()
    team_data = None
    for t in teams_data:
        if t['team'].lower() == team_name.lower():
            team_data = t
            break

    if not team_data:
        available_teams = ", ".join([t['team'] for t in teams_data])
        await ctx.send(f"❌ Team '{team_name}' not found.\n\n**Available teams:** {available_teams}")
        return

    # Check if team has a captain
    captain_name = get_team_captain(team_data['team'])

    if not captain_name:
        await ctx.send(f"❌ **{team_data['team']}** doesn't have a captain set.")
        return

    # Remove captain
    remove_team_captain(team_data['team'])
    remove_team_vice_captain(team_data['team'])
    asyncio.get_event_loop().create_task(
        refresh_squad_image_cache(team_data['team'], ctx.guild)
    )

    flag = get_team_flag(team_data['team'])
    embed = discord.Embed(
        title=f"👑 Captain Removed",
        description=f"{flag} **{captain_name}** is no longer the captain of **{team_data['team']}**.",
        color=get_team_color(team_data['team'])
    )

    embed.set_footer(text=f"Removed by {ctx.author.name}")
    embed.timestamp = discord.utils.utcnow()

    await ctx.send(embed=embed)

@bot.command(name="captains", aliases=["caps"], help="View all team captains")
async def captains_command(ctx):
    """List all teams and their captains"""
    teams_data = load_players()

    fields = []
    has_captains = False

    for team_data in teams_data:
        captain_name = get_team_captain(team_data['team'])
        flag = get_team_flag(team_data['team'])

        if captain_name:
            rep_info = get_representative(captain_name)
            username = rep_info[1] if rep_info else "Unknown"
            fields.append((f"{flag} {team_data['team']}", f"**{captain_name}**\n@{username}"))
            has_captains = True
        else:
            fields.append((f"{flag} {team_data['team']}", "*No captain set*"))

    # Discord allows max 25 fields per embed — split into pages if needed
    page_size = 25
    chunks = [fields[i:i + page_size] for i in range(0, len(fields), page_size)]

    for idx, chunk in enumerate(chunks):
        embed = discord.Embed(
            title="👑 Team Captains" if idx == 0 else "👑 Team Captains (cont.)",
            color=0xFFD700
        )
        if not has_captains and idx == 0:
            embed.description = "No captains have been assigned yet."
        for name, value in chunk:
            embed.add_field(name=name, value=value, inline=True)
        await ctx.send(embed=embed)

class ViceCaptainSelectView(View):
    """Dropdown used by a team captain to appoint their team's vice-captain."""
    def __init__(self, ctx, team_data, captain_user_id):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.team_data = team_data
        self.captain_user_id = captain_user_id
        self.message = None

        options = []
        for player in team_data['players']:
            rep_info = get_representative(player['name'])
            if not rep_info:
                continue

            member = ctx.guild.get_member(rep_info[0])
            if not member:
                continue

            if player['name'] == get_team_captain(team_data['team']):
                continue

            options.append(discord.SelectOption(
                label=member.name[:100],
                description=f"Player: {player['name']}"[:100],
                value=player['name']
            ))

        if options:
            select = Select(
                placeholder="👤 Select a team player as VC",
                options=options[:25],
                custom_id=f"setvc_{team_data['team'].lower().replace(' ', '_')}"
            )
            select.callback = self.select_callback
            self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "❌ This is not your menu!", ephemeral=True
            )
            return

        # Re-check captain status when the dropdown is used.
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute(
            "SELECT user_id FROM team_captains WHERE team_name = ?",
            (self.team_data['team'],)
        )
        captain_row = c.fetchone()
        conn.close()

        if not captain_row or captain_row[0] != interaction.user.id:
            await interaction.response.send_message(
                "❌ Only the current captain of this team can appoint the VC.",
                ephemeral=True
            )
            return

        player_name = interaction.data['values'][0]
        players, team_names = find_player(player_name)
        if not players or team_names[0] != self.team_data['team']:
            await interaction.response.send_message(
                "❌ That player is no longer available for this team.",
                ephemeral=True
            )
            return

        rep_info = get_representative(player_name)
        if not rep_info:
            await interaction.response.send_message(
                "❌ That player is no longer claimed by a Discord user.",
                ephemeral=True
            )
            return

        member = interaction.guild.get_member(rep_info[0])
        if not member:
            await interaction.response.send_message(
                "❌ That player is no longer in the server.",
                ephemeral=True
            )
            return

        set_team_vice_captain(
            self.team_data['team'],
            player_name,
            rep_info[0],
            rep_info[1]
        )
        asyncio.get_event_loop().create_task(
            refresh_squad_image_cache(self.team_data['team'], interaction.guild)
        )

        for child in self.children:
            child.disabled = True

        flag = get_team_flag(self.team_data['team'])
        embed = discord.Embed(
            title="✅ Vice-Captain Appointed",
            description=(
                f"{flag} {member.mention} (`{member.name}`) is now the "
                f"vice-captain of **{self.team_data['team']}**.\n\n"
                f"`-vt {self.team_data['team']}` will show **(VC)** beside "
                f"**{player_name}**."
            ),
            color=get_team_color(self.team_data['team'])
        )
        embed.set_footer(text=f"Appointed by {interaction.user.name}")
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

@bot.command(name="setvc", help="[TEAM CAPTAIN] Choose a vice-captain for your team")
async def setvc_command(ctx):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(
        "SELECT team_name FROM team_captains WHERE user_id = ?",
        (ctx.author.id,)
    )
    captain_teams = [row[0] for row in c.fetchall()]
    conn.close()

    if not captain_teams:
        await ctx.send("❌ Only team captains can use `-setvc`.")
        return

    # A captain should normally have one team; use the first if legacy data
    # contains more than one captain record for the same Discord user.
    team_name = captain_teams[0]
    teams_data = load_players()
    team_data = next(
        (team for team in teams_data if team['team'].lower() == team_name.lower()),
        None
    )
    if not team_data:
        await ctx.send(f"❌ Player data for **{team_name}** could not be found.")
        return

    captain_name = get_team_captain(team_data['team'])
    claimed_members = []
    for player in team_data['players']:
        if player['name'] == captain_name:
            continue
        rep_info = get_representative(player['name'])
        if rep_info and ctx.guild.get_member(rep_info[0]):
            claimed_members.append(player)

    if not claimed_members:
        await ctx.send(
            f"❌ No eligible claimed teammates from **{team_data['team']}** "
            "are currently available to choose."
        )
        return

    flag = get_team_flag(team_data['team'])
    view = ViceCaptainSelectView(ctx, team_data, ctx.author.id)
    embed = discord.Embed(
        title=f"{flag} Select Your Vice-Captain",
        description=(
            f"Choose a Discord username from **{team_data['team']}** below. "
            "Selecting another player will replace the current VC."
        ),
        color=get_team_color(team_data['team'])
    )
    current_vc = get_team_vice_captain(team_data['team'])
    if current_vc:
        embed.set_footer(text=f"Current VC: {current_vc}")

    view.message = await ctx.send(embed=embed, view=view)

@bot.command(name="synccap", help="[ADMIN] Synchronize captain roles and VC channel access")
@commands.has_permissions(administrator=True)
async def synccap_command(ctx):
    """Give the captain role to captains and grant VCs access to the VC channel."""
    captain_role_id = 1463220065657688285
    vc_channel_id = 1463604870547509403

    captain_role = ctx.guild.get_role(captain_role_id)
    vc_channel = ctx.guild.get_channel(vc_channel_id)

    if not captain_role:
        await ctx.send(f"❌ Could not find the captain role (`{captain_role_id}`).")
        return
    if not vc_channel:
        await ctx.send(f"❌ Could not find the VC channel (`{vc_channel_id}`).")
        return

    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM team_captains")
    captain_ids = {row[0] for row in c.fetchall()}
    c.execute("SELECT user_id FROM team_vice_captains")
    vice_captain_ids = {row[0] for row in c.fetchall()}
    conn.close()

    added_captains = 0
    removed_non_captains = 0
    missing_captains = 0
    failed_role_updates = 0

    # Add the role to every current captain.
    for user_id in captain_ids:
        member = ctx.guild.get_member(user_id)
        if not member:
            missing_captains += 1
            continue
        if captain_role not in member.roles:
            try:
                await member.add_roles(captain_role, reason=f"Captain role sync by {ctx.author}")
                added_captains += 1
            except (discord.Forbidden, discord.HTTPException):
                failed_role_updates += 1

    # Remove the role from every member who is not a current captain.
    for member in list(captain_role.members):
        if member.id in captain_ids:
            continue
        try:
            await member.remove_roles(captain_role, reason=f"Captain role sync by {ctx.author}")
            removed_non_captains += 1
        except (discord.Forbidden, discord.HTTPException):
            failed_role_updates += 1

    # Grant each current VC a member-specific view permission on the VC channel.
    granted_vc_access = 0
    missing_vcs = 0
    failed_vc_permissions = 0
    for user_id in vice_captain_ids:
        member = ctx.guild.get_member(user_id)
        if not member:
            missing_vcs += 1
            continue
        try:
            await vc_channel.set_permissions(
                member,
                view_channel=True,
                reason=f"Vice-captain channel access sync by {ctx.author}"
            )
            granted_vc_access += 1
        except (discord.Forbidden, discord.HTTPException):
            failed_vc_permissions += 1

    embed = discord.Embed(
        title="✅ Captain Sync Complete",
        color=0x00A86B
    )
    embed.add_field(
        name="Captain Role",
        value=(
            f"Added: **{added_captains}**\n"
            f"Removed from non-captains: **{removed_non_captains}**\n"
            f"Missing captains: **{missing_captains}**"
        ),
        inline=False
    )
    embed.add_field(
        name="Vice-Captain Channel",
        value=(
            f"Access granted: **{granted_vc_access}**\n"
            f"Missing VCs: **{missing_vcs}**"
        ),
        inline=False
    )
    if failed_role_updates or failed_vc_permissions:
        embed.add_field(
            name="Permission Failures",
            value=(
                f"Role updates: **{failed_role_updates}**\n"
                f"Channel updates: **{failed_vc_permissions}**"
            ),
            inline=False
        )
    embed.set_footer(text=f"Synced by {ctx.author}")
    await ctx.send(embed=embed)

@bot.command(name="fixcaptainstable", aliases=["fct"])
@is_staff_or_admin()
async def fix_captains_table(ctx): 
    """[ADMIN] Fix the team_captains table schema"""
    try:
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Drop the old table
        c.execute("DROP TABLE IF EXISTS team_captains")

        # Create the new table with correct schema
        c.execute('''CREATE TABLE team_captains
                     (team_name TEXT PRIMARY KEY, 
                      player_name TEXT, 
                      user_id INTEGER, 
                      username TEXT)''')

        conn.commit()
        conn.close()

        await ctx.send("✅ Successfully fixed the `team_captains` table schema!")
    except Exception as e:
        await ctx.send(f"❌ Error fixing table: {e}")

@bot.command(name="syncplayers", aliases=["sp"], help="[ADMIN] Unclaim players whose representatives have left the server")
@is_staff_or_admin()
async def syncplayers_command(ctx):
    await ctx.send("🔄 Checking for representatives who left the server...")

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Fetch all current claims
    c.execute("SELECT player_name, user_id, username FROM player_representatives")
    all_claims = c.fetchall()

    removed_count = 0
    removed_list = []
    affected_teams = set()

    for player_name, user_id, username in all_claims:
        # Check if member is still in the server
        member = ctx.guild.get_member(user_id)

        # If member is None, they are not in the server anymore
        if member is None:
            _, team_names = find_player(player_name)
            if team_names:
                affected_teams.add(team_names[0])
            # Remove from representatives
            c.execute("DELETE FROM player_representatives WHERE player_name = ?", (player_name,))

            # Remove from captains if they were one
            c.execute("DELETE FROM team_captains WHERE player_name = ?", (player_name,))
            c.execute("DELETE FROM team_vice_captains WHERE player_name = ?", (player_name,))

            removed_list.append(f"{player_name} (@{username})")
            removed_count += 1

    conn.commit()
    conn.close()

    for affected_team in affected_teams:
        asyncio.get_event_loop().create_task(
            refresh_squad_image_cache(affected_team, ctx.guild)
        )

    if removed_count > 0:
        # Create summary embed
        embed = discord.Embed(
            title="🗑️ Sync Complete",
            color=0xFF0000
        )

        # Chunk list if too long for description
        description = "\n".join([f"• {p}" for p in removed_list[:50]])
        if len(removed_list) > 50:
            description += f"\n...and {len(removed_list) - 50} more."

        embed.description = f"**{removed_count}** players were unclaimed because their representatives left the server.\n\n{description}"
        embed.set_footer(text=f"Synced by {ctx.author.name}")
        embed.timestamp = discord.utils.utcnow()

        await ctx.send(embed=embed)
    else:
        await ctx.send("✅ All current representatives are still in the server.")

@bot.command(name="forceupload", aliases=["fu"], help="[ADMIN] Force upload emoji for a specific player")
@is_staff_or_admin()
async def forceupload_command(ctx, *, player_name: str):
    """[ADMIN] Force upload emoji for a specific player"""

    # Find the player
    players, team_names = find_player(player_name)

    if not players:
        await ctx.send(f"❌ Player '{player_name}' not found.")
        return

    if len(players) > 1:
        embed = discord.Embed(
            title="🔍 Multiple Players Found",
            description=f"Multiple players match '{player_name}'. Please use the full name:\n\n",
            color=0xFFA500
        )

        for i, (player, team) in enumerate(zip(players, team_names), 1):
            flag = get_team_flag(team)
            embed.description += f"**{i}.** {flag} **{player['name']}** - {team}\n"

        await ctx.send(embed=embed)
        return

    player = players[0]
    await ctx.send(f"🔄 Uploading emoji for **{player['name']}**...")

    # Create emoji name (alphanumeric + underscores only, max 32 chars)
    emoji_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in player['name'])
    emoji_name = emoji_name[:32]

    # Check if emoji already exists in any server
    for guild in get_emoji_guilds(bot):
        existing_emoji = discord.utils.get(guild.emojis, name=emoji_name)
        if existing_emoji:
            await ctx.send(f"✅ Emoji already exists: {existing_emoji} in {guild.name}")
            return

    # Find a server with available emoji slots
    target_guild = None
    for guild in get_emoji_guilds(bot):
        if len(guild.emojis) < guild.emoji_limit:
            target_guild = guild
            break

    if not target_guild:
        await ctx.send("❌ All emoji servers are full!")
        return

    try:
        async with aiohttp.ClientSession() as session:
            # Download and process image
            image_data = await download_and_process_image(session, player['image'], player['name'])

            if not image_data:
                await ctx.send(f"❌ Failed to process image for {player['name']}")
                return

            # Upload emoji to server
            emoji = await target_guild.create_custom_emoji(
                name=emoji_name,
                image=image_data.read()
            )

            # Save to emoji mappings
            player_emojis[player['name']] = emoji.id
            with open('player_emojis.json', 'w') as f:
                json.dump(player_emojis, f, indent=2)

            await ctx.send(f"✅ Successfully uploaded emoji: {emoji} for **{player['name']}** in {target_guild.name}")

    except discord.errors.HTTPException as e:
        await ctx.send(f"❌ HTTP error uploading emoji: {e}")
    except Exception as e:
        await ctx.send(f"❌ Error uploading emoji: {e}")

@bot.command(name="syncroles", aliases=["sr"], help="[ADMIN] Sync nationality roles for all members")
@is_staff_or_admin()
async def syncroles_command(ctx):
    await ctx.send("🔄 Syncing nationality roles...")

    teams_data = load_players()
    all_team_names = [team['team'] for team in teams_data]

    # Build role_ids map
    role_ids = {
        team_name: discord.utils.find(lambda r: team_name.lower() in r.name.lower(), ctx.guild.roles)
        for team_name in all_team_names
    }
    all_nationality_roles = [r for r in role_ids.values() if r]

    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name, user_id, username FROM player_representatives")
    all_claims = c.fetchall()
    conn.close()

    claimed_user_ids = {user_id: (player_name, username) for player_name, user_id, username in all_claims}

    synced_count = 0
    removed_count = 0
    failed_list = []
    already_had = 0
    roles_fixed = 0

    # --- Process ALL guild members ---
    for member in ctx.guild.members:
        if member.bot:
            continue

        member_nat_roles = [r for r in member.roles if r in all_nationality_roles]

        if member.id in claimed_user_ids:
            # Has a claim - ensure they have the correct role only
            player_name, username = claimed_user_ids[member.id]
            players, team_names = find_player(player_name)

            if not players or not team_names:
                failed_list.append(f"{player_name} (@{username}) - Player data not found")
                continue

            correct_team = team_names[0]
            correct_role = role_ids.get(correct_team)

            if not correct_role:
                failed_list.append(f"{player_name} (@{username}) - Role for {correct_team} not found")
                continue

            has_correct_only = len(member_nat_roles) == 1 and member_nat_roles[0] == correct_role

            if has_correct_only:
                already_had += 1
                continue

            try:
                # Remove wrong nationality roles
                for role in member_nat_roles:
                    if role != correct_role:
                        await member.remove_roles(role, reason="Syncing: removing incorrect nationality role")

                # Add correct role if missing
                if correct_role not in member.roles:
                    await member.add_roles(correct_role, reason=f"Synced nationality role for {player_name}")
                    synced_count += 1
                else:
                    roles_fixed += 1

            except discord.Forbidden:
                failed_list.append(f"{player_name} (@{username}) - No permission")
            except discord.HTTPException as e:
                failed_list.append(f"{player_name} (@{username}) - HTTP error: {e}")

        else:
            # No claim - remove any nationality roles they have
            if not member_nat_roles:
                continue

            try:
                await member.remove_roles(*member_nat_roles, reason="Syncing: member has no claimed player")
                removed_count += len(member_nat_roles)
            except discord.Forbidden:
                failed_list.append(f"{member.name} - No permission to remove roles")
            except discord.HTTPException as e:
                failed_list.append(f"{member.name} - HTTP error: {e}")

    embed = discord.Embed(title="🌍 Role Sync Complete", color=0x00FF00)

    summary = (
        f"✅ **Roles Added:** {synced_count}\n"
        f"🔧 **Roles Fixed:** {roles_fixed}\n"
        f"🗑️ **Roles Removed (unclaimed):** {removed_count}\n"
        f"ℹ️ **Already Correct:** {already_had}\n"
        f"❌ **Failed:** {len(failed_list)}"
    )
    embed.add_field(name="Summary", value=summary, inline=False)

    if failed_list:
        failures = "\n".join([f"• {f}" for f in failed_list[:10]])
        if len(failed_list) > 10:
            failures += f"\n...and {len(failed_list) - 10} more."
        embed.add_field(name="Failed", value=failures, inline=False)

    embed.set_footer(text=f"Synced by {ctx.author.name}")
    embed.timestamp = discord.utils.utcnow()
    await ctx.send(embed=embed)

@bot.command(name="playeremojiremove", aliases=["per"], help="[ADMIN] Remove emoji for a specific player")
@is_staff_or_admin()
async def playeremojiremove_command(ctx, *, player_name: str):
    """[ADMIN] Remove emoji for a specific player"""

    # Find the player
    players, team_names = find_player(player_name)

    if not players:
        await ctx.send(f"❌ Player '{player_name}' not found.")
        return

    if len(players) > 1:
        embed = discord.Embed(
            title="🔍 Multiple Players Found",
            description=f"Multiple players match '{player_name}'. Please use the full name:\n\n",
            color=0xFFA500
        )

        for i, (player, team) in enumerate(zip(players, team_names), 1):
            flag = get_team_flag(team)
            embed.description += f"**{i}.** {flag} **{player['name']}** - {team}\n"

        await ctx.send(embed=embed)
        return

    player = players[0]
    await ctx.send(f"🔄 Removing emoji for **{player['name']}**...")

    # Create emoji name (alphanumeric + underscores only, max 32 chars)
    emoji_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in player['name'])
    emoji_name = emoji_name[:32]

    # Search for emoji across all available guilds
    emoji_found = False

    for guild in get_emoji_guilds(bot):
        emoji_obj = discord.utils.get(guild.emojis, name=emoji_name)
        if emoji_obj:
                try:
                    await emoji_obj.delete(reason=f"Player emoji removal by {ctx.author}")

                    # Remove from emoji mappings
                    if player['name'] in player_emojis:
                        del player_emojis[player['name']]
                        with open('player_emojis.json', 'w') as f:
                            json.dump(player_emojis, f, indent=2)

                    await ctx.send(f"✅ Successfully removed emoji for **{player['name']}** from {guild.name}")
                    emoji_found = True
                    break

                except discord.Forbidden:
                    await ctx.send(f"❌ No permission to delete emoji in {guild.name}")
                    emoji_found = True
                    break
                except discord.HTTPException as e:
                    await ctx.send(f"❌ HTTP error deleting emoji: {e}")
                    emoji_found = True
                    break

    if not emoji_found:
        await ctx.send(f"❌ No emoji found for **{player['name']}** (searched name: `{emoji_name}`)")

@bot.command(name="roleallclaimed", aliases=["rac"], help="[ADMIN] Give all claimed players a specific role")
@is_staff_or_admin()
async def roleallclaimed_command(ctx, role: discord.Role):
    """[ADMIN] Give all claimed players a specific role"""
    await ctx.send(f"🔄 Adding {role.mention} to all claimed players...")

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Fetch all current claims
    c.execute("SELECT user_id, username FROM player_representatives")
    all_claims = c.fetchall()

    conn.close()

    added_count = 0
    already_had = 0
    failed_list = []

    for user_id, username in all_claims:
        member = ctx.guild.get_member(user_id)

        if not member:
            failed_list.append(f"@{username} - Not in server")
            continue

        # Check if member already has the role
        if role in member.roles:
            already_had += 1
            continue

        try:
            await member.add_roles(role, reason=f"Claimed player role by {ctx.author}")
            added_count += 1
        except discord.Forbidden:
            failed_list.append(f"@{username} - No permission")
        except discord.HTTPException as e:
            failed_list.append(f"@{username} - HTTP error")

    # Create summary embed
    embed = discord.Embed(
        title="✅ Role Assignment Complete",
        color=role.color
    )

    summary = f"**Role:** {role.mention}\n\n"
    summary += f"✅ **Added:** {added_count}\n"
    summary += f"ℹ️ **Already Had:** {already_had}\n"
    summary += f"❌ **Failed:** {len(failed_list)}"

    embed.description = summary

    if failed_list:
        failures = "\n".join([f"• {f}" for f in failed_list[:10]])
        if len(failed_list) > 10:
            failures += f"\n...and {len(failed_list) - 10} more."

        embed.add_field(name="Failed", value=failures, inline=False)

    embed.set_footer(text=f"Executed by {ctx.author.name}")
    embed.timestamp = discord.utils.utcnow()

    await ctx.send(embed=embed)


@bot.command(name="roleallunclaimed", aliases=["rau"], help="[ADMIN] Give unclaimed role to members who haven't claimed")
@is_staff_or_admin()
async def roleallunclaimed_command(ctx):
    """[ADMIN] Give unclaimed role (1461764869282857010) to members with player role (1452028351719014400) who haven't claimed"""
    await ctx.send("🔄 Adding unclaimed role to members who haven't claimed a player...")

    player_role = ctx.guild.get_role(1452028351719014400)
    unclaimed_role = ctx.guild.get_role(1461764869282857010)

    if not player_role:
        await ctx.send("❌ Player role (1452028351719014400) not found!")
        return

    if not unclaimed_role:
        await ctx.send("❌ Unclaimed role (1461764869282857010) not found!")
        return

    added_count = 0
    already_had = 0
    removed_count = 0
    failed_list = []

    # Collect all guild members with the unclaimed role for removal check
    all_unclaimed_members = list(unclaimed_role.members)

    # Discord team roles are the source of truth for whether a member has
    # claimed a player. Remove stale unclaimed roles from claimed members.
    for member in all_unclaimed_members:
        if member_has_team_role(member):
            try:
                await member.remove_roles(unclaimed_role, reason=f"Player claimed; unclaimed role removed by {ctx.author}")
                removed_count += 1
            except discord.Forbidden:
                failed_list.append(f"{member.name} - No permission (remove)")
            except discord.HTTPException:
                failed_list.append(f"{member.name} - HTTP error (remove)")

    # Iterate through all members with the player role
    for member in player_role.members:
        # No team role means this member is unclaimed.
        if member_has_team_role(member):
            continue

        # Check if member already has the unclaimed role
        if unclaimed_role in member.roles:
            already_had += 1
            continue

        try:
            await member.add_roles(unclaimed_role, reason=f"Unclaimed player role by {ctx.author}")
            added_count += 1
        except discord.Forbidden:
            failed_list.append(f"{member.name} - No permission (add)")
        except discord.HTTPException:
            failed_list.append(f"{member.name} - HTTP error (add)")

    # Create summary embed
    embed = discord.Embed(
        title="✅ Unclaimed Role Assignment Complete",
        color=unclaimed_role.color
    )

    summary = f"**Player Role:** {player_role.mention}\n"
    summary += f"**Unclaimed Role:** {unclaimed_role.mention}\n\n"
    summary += f"✅ **Added:** {added_count}\n"
    summary += f"🗑️ **Removed (claimed players):** {removed_count}\n"
    summary += f"ℹ️ **Already Had:** {already_had}\n"
    summary += f"❌ **Failed:** {len(failed_list)}"

    embed.description = summary

    if failed_list:
        failures = "\n".join([f"• {f}" for f in failed_list[:10]])
        if len(failed_list) > 10:
            failures += f"\n...and {len(failed_list) - 10} more."

        embed.add_field(name="Failed", value=failures, inline=False)

    embed.set_footer(text=f"Executed by {ctx.author.name}")
    embed.timestamp = discord.utils.utcnow()

    await ctx.send(embed=embed)

@bot.command(name="replyextract")
async def reply_extract(ctx):
    if ctx.message.reference is not None:
        original_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)

        extracted_text = ""

        # 1. Check for regular text content
        if original_msg.content:
            extracted_text += original_msg.content

        # 2. Check for text inside embeds
        if original_msg.embeds:
            for embed in original_msg.embeds:
                # Get description
                if embed.description:
                    extracted_text += f"\n{embed.description}"
                # Get text from fields
                for field in embed.fields:
                    extracted_text += f"\n{field.name}: {field.value}"

        # Send the result if text was found
        if extracted_text.strip():
            # Discord has a 2000 character limit; we trim to keep it safe
            safe_text = extracted_text[:1990] 
            await ctx.send(f"```{safe_text}```")
        else:
            await ctx.send("I couldn't find any text or embed descriptions in that message.")
    else:
        await ctx.send("Please reply to a message to use this command.")

# ----


@bot.command(name='send')
@is_staff_or_admin()
async def send_message(ctx, channel_id: int, *, message: str):
    """
    Send a message to a specific channel (Administrator only)
    Usage: !send <channel_id> <message>
    """
    # Get the channel by ID
    channel = bot.get_channel(channel_id)

    if channel is None:
        await ctx.send("❌ Channel not found. Make sure the bot has access to that channel.")
        return

    # Check if the channel is a text channel
    if not isinstance(channel, discord.TextChannel):
        await ctx.send("❌ That's not a text channel.")
        return

    try:
        # Send the message to the specified channel
        await channel.send(message)
        await ctx.send(f"✅ Message sent to {channel.mention}")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to send messages in that channel.")
    except Exception as e:
        await ctx.send(f"❌ An error occurred: {e}")


#------------

# Team roles used by /matchtime. The autocomplete keeps this list usable
# without exceeding Discord's 25 static-choice limit.
MATCHTIME_TEAM_ROLE_IDS = {
    "India": 1460376137594044567,
    "Pakistan": 1460376138755866644,
    "Australia": 1460376139611640025,
    "England": 1460376141314654424,
    "New Zealand": 1460376142342000762,
    "South Africa": 1460376143633846527,
    "West Indies": 1460376148751028408,
    "Sri Lanka": 1460376147715166282,
    "Bangladesh": 1460376144862908523,
    "Afghanistan": 1460376146163273739,
    "Netherlands": 1460376154480312370,
    "Scotland": 1460376151795961897,
    "Ireland": 1460376149908525191,
    "Zimbabwe": 1460376157668245545,
    "UAE": 1460376158985130114,
    "Canada": 1460376154958725152,
    "USA": 1460376156250570824,
    "Italy": 1513096652842467328,
    "Nepal": 1513096680835125398,
    "Namibia": 1513096608063950878,
    "Hong Kong": 1513236745527889951,
    "Oman": 1513236895595757768,
    "Papua New Guinea": 1513237053935194262,
    "Uganda": 1513237221560287312,
    "Malaysia": 1513238128482320454,
    "Spain": 1513238260502233198,
    "Germany": 1513238268777595073,
    "Japan": 1513238484075282432,
    "Portugal": 1513238487707549958,
    "Denmark": 1513238490723385466,
}

MATCHTIME_PRIMARY_TEAM_COUNT = 24


async def matchtime_opponent_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Show only the primary tournament teams."""
    current = current.lower().strip()
    primary_teams = list(MATCHTIME_TEAM_ROLE_IDS)[:MATCHTIME_PRIMARY_TEAM_COUNT]

    matches = [
        team_name for team_name in primary_teams
        if not current or current in team_name.lower()
    ]
    return [
        app_commands.Choice(name=team_name, value=team_name)
        for team_name in matches[:25]
    ]


async def matchtime_other_team_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Show the optional list of teams outside the primary 24."""
    current = current.lower().strip()
    primary_teams = set(list(MATCHTIME_TEAM_ROLE_IDS)[:MATCHTIME_PRIMARY_TEAM_COUNT])
    other_teams = [
        team_name for team_name in MATCHTIME_TEAM_ROLE_IDS
        if team_name not in primary_teams
    ]
    matches = [
        team_name for team_name in other_teams
        if not current or current in team_name.lower()
    ]
    return [
        app_commands.Choice(name=team_name, value=team_name)
        for team_name in matches[:25]
    ]


class MatchTimeButtons(discord.ui.View):
    def __init__(
        self,
        requester_id,
        target_captain_id,
        requester_team_role_id,
        target_team_role_id,
        requester_team_name,
        target_team_name,
        match_time,
        stadium_channel_id,
        channel,
    ):
        super().__init__(timeout=172800)  # 2 days in seconds
        self.requester_id = requester_id
        self.target_captain_id = target_captain_id
        self.requester_team_role_id = requester_team_role_id
        self.target_team_role_id = target_team_role_id
        self.requester_team_name = requester_team_name
        self.target_team_name = target_team_name
        self.match_time = match_time
        self.stadium_channel_id = stadium_channel_id
        self.channel = channel

    @discord.ui.button(label="Accept Time", style=discord.ButtonStyle.green, custom_id="accept_time")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Only target captain can click
        if interaction.user.id != self.target_captain_id:
            await interaction.response.send_message("❌ Only the team captain can accept this request!", ephemeral=True)
            return

        # Disable all buttons
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(view=self)

        # Build ping text for roles
        ping_text = ""
        if self.requester_team_role_id:
            ping_text += f"<@&{self.requester_team_role_id}> "
        if self.target_team_role_id:
            ping_text += f"<@&{self.target_team_role_id}> "

        stadium_channel = self.channel.guild.get_channel(self.stadium_channel_id)
        stadium_name = (
            stadium_channel.name if stadium_channel else "the selected stadium channel"
        )
        stadium_mention = (
            stadium_channel.mention if stadium_channel else f"<#{self.stadium_channel_id}>"
        )

        # Send ping message first (separate from embed) as regular message
        await self.channel.send(
            content=(
                f"{ping_text}**VS** at **{self.match_time}** in "
                f"{stadium_mention}"
            )
        )

        # Then send the embed as regular message
        announce_embed = discord.Embed(
            title="⚔️ Match Scheduled!",
            color=0x00FF00
        )

        announce_embed.add_field(
            name="🕐 Match Time",
            value=f"**{self.match_time}**",
            inline=False
        )
        announce_embed.add_field(
        name="📍 Match Channel",
            value=f"{stadium_mention} (`{self.stadium_channel_id}`)",
            inline=False
        )

        announce_embed.set_footer(text="Good luck to both teams!")

        await self.channel.send(embed=announce_embed)

        # DM every non-bot member carrying either team's role. De-duplicate
        # members who happen to have both roles.
        team_members = {
            member.id: member
            for member in self.channel.guild.members
            if not member.bot and (
                any(role.id == self.requester_team_role_id for role in member.roles)
                or any(role.id == self.target_team_role_id for role in member.roles)
            )
        }
        dm_message = (
            "🏏 **Match Scheduled!**\n\n"
            f"**{self.requester_team_name}** vs **{self.target_team_name}**\n"
            f"🕐 Time: **{self.match_time}**\n"
            f"🏟️ Channel: **#{stadium_name}**\n"
            f"Channel ID: `{self.stadium_channel_id}`\n"
            f"Open the match channel: {stadium_mention}\n\n"
            "Good luck!"
        )
        for member in team_members.values():
            try:
                await member.send(dm_message)
            except (discord.Forbidden, discord.HTTPException):
                pass
            except Exception:
                pass

    @discord.ui.button(label="Cancel Request", style=discord.ButtonStyle.red, custom_id="cancel_request")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Only requester can click
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("❌ Only the person who created this request can cancel it!", ephemeral=True)
            return

        # Disable all buttons
        for child in self.children:
            child.disabled = True

        cancel_embed = discord.Embed(
            title="❌ Match Request Cancelled",
            description="The match time request has been cancelled.",
            color=0xFF0000
        )

        await interaction.response.edit_message(embed=cancel_embed, view=self)


async def _create_matchtime_request(
    interaction: discord.Interaction,
    requester_team_role_id: int,
    requester_team_name: str,
    opponent_team_name: str,
    match_time: str,
    stadium_channel_id: int,
):
    """Create the captain request in the channel where /matchtime was used."""
    requester_team_role = interaction.guild.get_role(requester_team_role_id)
    opponent_role_id = MATCHTIME_TEAM_ROLE_IDS.get(opponent_team_name)
    opponent_role = (
        interaction.guild.get_role(opponent_role_id)
        if opponent_role_id
        else None
    )
    if not requester_team_role:
        await interaction.response.send_message(
            "❌ Your team role could not be found!",
            ephemeral=True,
        )
        return
    if not opponent_role:
        await interaction.response.send_message(
            "❌ Opponent team role not found!",
            ephemeral=True,
        )
        return

    if requester_team_role.id == opponent_role.id:
        await interaction.response.send_message(
            "❌ You cannot challenge your own team!",
            ephemeral=True,
        )
        return

    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(
        "SELECT user_id, username FROM team_captains WHERE team_name = ?",
        (opponent_team_name,),
    )
    captain_result = c.fetchone()
    conn.close()

    if not captain_result:
        await interaction.response.send_message(
            f"❌ {opponent_team_name} doesn't have a captain set yet!",
            ephemeral=True,
        )
        return

    captain_id, captain_username = captain_result
    captain = interaction.guild.get_member(captain_id)
    if not captain:
        await interaction.response.send_message(
            f"❌ Captain of {opponent_team_name} is not in the server!",
            ephemeral=True,
        )
        return

    stadium_channel = interaction.guild.get_channel(stadium_channel_id)
    if not stadium_channel:
        await interaction.response.send_message(
            "❌ The selected stadium channel was not found in this server!",
            ephemeral=True,
        )
        return

    await interaction.channel.send(
        content=f"<@{captain_id}> - Match Time Request"
    )

    request_embed = discord.Embed(
        title="🏏 Match Time Request",
        description=f"The captain of **{requester_team_name}** wants to schedule a match!",
        color=0xFFA500,
    )
    request_embed.add_field(
        name="Teams",
        value=f"{requester_team_role.mention} **VS** {opponent_role.mention}",
        inline=False,
    )
    request_embed.add_field(
        name="Proposed Time",
        value=f"**{match_time}**",
        inline=False,
    )
    request_embed.add_field(
        name="📍 Match Channel",
        value=f"{stadium_channel.mention} (`{stadium_channel.id}`)",
        inline=False,
    )
    request_embed.set_footer(text=f"Requested by {interaction.user.name}")

    view = MatchTimeButtons(
        requester_id=interaction.user.id,
        target_captain_id=captain_id,
        requester_team_role_id=requester_team_role.id,
        target_team_role_id=opponent_role.id,
        requester_team_name=requester_team_name,
        target_team_name=opponent_team_name,
        match_time=match_time,
        stadium_channel_id=stadium_channel_id,
        channel=interaction.channel,
    )
    await interaction.channel.send(embed=request_embed, view=view)

    confirmation = "✅ Match time request sent!"
    if interaction.response.is_done():
        await interaction.followup.send(confirmation, ephemeral=True)
    else:
        await interaction.response.send_message(confirmation, ephemeral=True)


@bot.tree.command(name="matchtime", description="Schedule a match time with another team")
@app_commands.describe(
    time="Select the match time",
    opponent="Optional: select one of the main tournament teams",
    other_team="Optional: select Malaysia, Spain, Germany, Japan, Portugal, or Denmark",
)
@app_commands.choices(time=[
    app_commands.Choice(name="5:00 PM IST", value="5:00PM IST"),
    app_commands.Choice(name="5:30 PM IST", value="5:30PM IST"),
    app_commands.Choice(name="6:00 PM IST", value="6:00PM IST"),
    app_commands.Choice(name="6:15 PM IST", value="6:15PM IST"),
    app_commands.Choice(name="6:30 PM IST", value="6:30PM IST"),
    app_commands.Choice(name="6:45 PM IST", value="6:45PM IST"),
    app_commands.Choice(name="7:00 PM IST", value="7:00PM IST"),
    app_commands.Choice(name="7:15 PM IST", value="7:15PM IST"),
    app_commands.Choice(name="7:30 PM IST", value="7:30PM IST"),
    app_commands.Choice(name="7:45 PM IST", value="7:45PM IST"),
    app_commands.Choice(name="8:00 PM IST", value="8:00PM IST"),
    app_commands.Choice(name="8:15 PM IST", value="8:15PM IST"),
    app_commands.Choice(name="8:30 PM IST", value="8:30PM IST"),
    app_commands.Choice(name="8:45 PM IST", value="8:45PM IST"),
    app_commands.Choice(name="9:00 PM IST", value="9:00PM IST"),
    app_commands.Choice(name="9:15 PM IST", value="9:15PM IST"),
    app_commands.Choice(name="9:30 PM IST", value="9:30PM IST"),
    app_commands.Choice(name="9:45 PM IST", value="9:45PM IST"),
    app_commands.Choice(name="10:00 PM IST", value="10:00PM IST"),
    app_commands.Choice(name="10:15 PM IST", value="10:15PM IST"),
])
@app_commands.autocomplete(opponent=matchtime_opponent_autocomplete)
@app_commands.autocomplete(other_team=matchtime_other_team_autocomplete)
async def matchtime(
    interaction: discord.Interaction,
    time: app_commands.Choice[str],
    opponent: Optional[str] = None,
    other_team: Optional[str] = None,
):
    # Check if user has the required role
    required_role = interaction.guild.get_role(1463220065657688285)
    if required_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You don't have permission to use this command!", ephemeral=True)
        return

    # Find requester's team
    requester_team_role = None
    requester_team_name = None
    for team_name, role_id in MATCHTIME_TEAM_ROLE_IDS.items():
        role = interaction.guild.get_role(role_id)
        if role in interaction.user.roles:
            requester_team_role = role
            requester_team_name = team_name
            break

    if not requester_team_role:
        await interaction.response.send_message("❌ You don't have a team role!", ephemeral=True)
        return

    if opponent and other_team:
        await interaction.response.send_message(
            "❌ Choose either a main tournament team or an other team, not both.",
            ephemeral=True,
        )
        return

    selected_opponent = other_team or opponent
    if not selected_opponent:
        await interaction.response.send_message(
            "❌ Select an opponent from either **opponent** or **other_team**.",
            ephemeral=True,
        )
        return

    # The match channel is always where the captain used /matchtime.
    stadium_channel_id = interaction.channel.id
    await _create_matchtime_request(
        interaction=interaction,
        requester_team_role_id=requester_team_role.id,
        requester_team_name=requester_team_name,
        opponent_team_name=selected_opponent,
        match_time=time.value,
        stadium_channel_id=stadium_channel_id,
    )

@bot.command(name="order", aliases=["o"], help="View your team's batting order")
async def order_command(ctx):
    """Show the user's team batting order in simplified format"""

    # Get the user's player
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", 
              (ctx.author.id,))
    result = c.fetchone()
    conn.close()

    if not result:
        await ctx.send("❌ You haven't claimed a player yet! Use `-represent` to claim one.")
        return

    player_name = result[0]

    # Find which team the user's player belongs to
    players, team_names = find_player(player_name)

    if not players or not team_names:
        await ctx.send("❌ Could not find your player's team!")
        return

    user_team = team_names[0]

    # Load all teams data
    teams_data = load_players()

    # Find the user's team data
    team_data = None
    for t in teams_data:
        if t['team'] == user_team:
            team_data = t
            break

    if not team_data:
        await ctx.send("❌ Team data not found!")
        return

    # Categorize players by role and get their representatives
    batsmen = []
    wicketkeepers = []
    allrounders = []
    bowlers = []

    for player in team_data['players']:
        rep_info = get_representative(player['name'])

        # Skip unclaimed players
        if not rep_info:
            continue

        username = rep_info[1]

        # Categorize by role
        if "Wicketkeeper" in player['role']:
            wicketkeepers.append(username)
        elif "Batsman" in player['role']:
            batsmen.append(username)
        elif "All-Rounder" in player['role'] or "All-rounder" in player['role']:
            allrounders.append(username)
        elif "Bowler" in player['role']:
            bowlers.append(username)

    # Build the order text
    order_text = f"**`WK / BAT -> ALR -> BOWL`**\n\n"


    if wicketkeepers:
        order_text += "**Wicketkeepers:**\n"
        for username in wicketkeepers:
            order_text += f"- {username}\n"
        order_text += "\n"

    if batsmen:
        order_text += "**Batters:**\n"
        for username in batsmen:
            order_text += f"- {username}\n"
        order_text += "\n"

    if allrounders:
        order_text += "**All-Rounders:**\n"
        for username in allrounders:
            order_text += f"- {username}\n"
        order_text += "\n"

    if bowlers:
        order_text += "**Bowlers:**\n"
        for username in bowlers:
            order_text += f"- {username}\n"

    await ctx.send(order_text)


def format_player_nickname(player_name, custom_nickname):
    """Format nickname as 'FirstInitial. LastWord ○ CustomNickname'"""
    parts = player_name.split()
    if len(parts) == 0:
        return custom_nickname

    first_initial = parts[0][0]
    last_word = parts[-1]

    return f"{first_initial}. {last_word} ○ {custom_nickname}"

def get_user_custom_nickname(user_id):
    """Get user's custom nickname from database"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT custom_nickname FROM user_nicknames WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def save_original_nickname(user_id, nickname):
    """Save original nickname before syncing"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Check if record exists
    c.execute("SELECT 1 FROM user_nicknames WHERE user_id = ?", (user_id,))
    exists = c.fetchone()

    if exists:
        # Update if original_nickname is NULL
        c.execute("""UPDATE user_nicknames 
                     SET original_nickname = COALESCE(original_nickname, ?)
                     WHERE user_id = ?""", (nickname, user_id))
    else:
        # Insert new record
        c.execute("""INSERT INTO user_nicknames (user_id, original_nickname, custom_nickname) 
                     VALUES (?, ?, ?)""", (user_id, nickname, nickname))

    conn.commit()
    conn.close()

def update_custom_nickname(user_id, custom_nickname):
    """Update user's custom nickname"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO user_nicknames (user_id, custom_nickname, last_synced) 
                 VALUES (?, ?, CURRENT_TIMESTAMP)""", (user_id, custom_nickname))
    conn.commit()
    conn.close()

@bot.command(name="syncnicknames", aliases=["sn"], help="[ADMIN] Sync nicknames for all claimed players")
@is_staff_or_admin()
async def syncnicknames_command(ctx):
    """Sync nicknames for all claimed players: Reset first, then re-sync with length limits"""
    loading_msg = await ctx.send("🔄 **Phase 1:** Resetting all nicknames to default...")

    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name, user_id, username FROM player_representatives")
    all_claims = c.fetchall()
    conn.close()

    reset_count = 0
    synced_count = 0
    failed_list = []

    # Phase 1: Reset all claimed users' nicknames
    for _, user_id, username in all_claims:
        try:
            member = await ctx.guild.fetch_member(user_id)
            if member:
                await member.edit(nick=None, reason="Nickname sync reset phase")
                reset_count += 1
        except Exception:
            continue

    await loading_msg.edit(content=f"🔄 **Phase 2:** Applying formatted nicknames for {len(all_claims)} players...")

    # Phase 2: Apply formatted nicknames
    for player_name, user_id, username in all_claims:
        try:
            member = await ctx.guild.fetch_member(user_id)
        except (discord.NotFound, discord.HTTPException):
            member = ctx.guild.get_member(user_id)
            if not member:
                failed_list.append(f"{player_name} (@{username}) - Not in server")
                continue

        # Save original nickname if not already saved
        current_display = member.display_name
        save_original_nickname(user_id, current_display)

        # Get custom nickname or use current
        custom_nickname = get_user_custom_nickname(user_id)
        if not custom_nickname:
            custom_nickname = member.name # Use discord username as base
            update_custom_nickname(user_id, custom_nickname)

        # Format new nickname: "M. Adair ○ customnick"
        # Discord limit is 32 characters
        formatted_name = format_player_nickname(player_name, custom_nickname)

        # Ensure it fits 32 chars
        if len(formatted_name) > 32:
            # Calculate length of "M. Adair ○ " part
            parts = player_name.split()
            if len(parts) > 0:
                prefix = f"{parts[0][0]}. {parts[-1]} ○ "
                max_custom_len = 32 - len(prefix)
                if max_custom_len > 0:
                    trimmed_custom = custom_nickname[:max_custom_len]
                    formatted_name = f"{prefix}{trimmed_custom}"
                else:
                    # If prefix itself is too long (unlikely), just use first 32 chars
                    formatted_name = prefix[:32]
            else:
                formatted_name = custom_nickname[:32]

        try:
            await member.edit(nick=formatted_name, reason=f"Nickname sync by {ctx.author}")
            synced_count += 1
        except discord.Forbidden:
            failed_list.append(f"{player_name} (@{username}) - No permission")
        except discord.HTTPException as e:
            failed_list.append(f"{player_name} (@{username}) - Error: {e}")

    # Create summary embed
    embed = discord.Embed(
        title="✅ Nickname Sync Complete",
        description=f"Successfully reset {reset_count} and re-synced {synced_count} nicknames.",
        color=0x00FF00
    )

    if failed_list:
        failures = "\n".join([f"• {f}" for f in failed_list[:10]])
        if len(failed_list) > 10:
            failures += f"\n...and {len(failed_list) - 10} more."
        embed.add_field(name="Failed/Skipped", value=failures, inline=False)

    embed.set_footer(text=f"Action by {ctx.author.name}")
    embed.timestamp = discord.utils.utcnow()

    await loading_msg.delete()
    await ctx.send(embed=embed)

@bot.tree.command(name="setnickname", description="Set your custom nickname")
@app_commands.describe(nickname="Your desired nickname")
async def setnickname_command(interaction: discord.Interaction, nickname: str):
    """Set custom nickname for claimed player"""

    # Check if user has claimed a player
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", 
              (interaction.user.id,))
    result = c.fetchone()
    conn.close()

    if not result:
        await interaction.response.send_message(
            "❌ You haven't claimed a player yet! Use `-represent` to claim one.",
            ephemeral=True
        )
        return

    player_name = result[0]

    # Check nickname length (Discord limit is 32 characters)
    formatted_nickname = format_player_nickname(player_name, nickname)
    if len(formatted_nickname) > 32:
        await interaction.response.send_message(
            f"❌ Your nickname is too long! The formatted nickname would be:\n`{formatted_nickname}`\n"
            f"This is {len(formatted_nickname)} characters, but Discord's limit is 32.\n"
            f"Please choose a shorter nickname.",
            ephemeral=True
        )
        return

    # Update custom nickname in database
    update_custom_nickname(interaction.user.id, nickname)

    # Update member's nickname
    try:
        await interaction.user.edit(nick=formatted_nickname, reason="Custom nickname set by user")

        await interaction.response.send_message(
            f"✅ Your nickname has been updated to: **{formatted_nickname}**",
            ephemeral=True
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I don't have permission to change your nickname!",
            ephemeral=True
        )
    except discord.HTTPException as e:
        await interaction.response.send_message(
            f"❌ Failed to update nickname: {e}",
            ephemeral=True
        )

@bot.command(name="setbacknicknames", aliases=["sbn"], help="[ADMIN] Restore original nicknames")
@is_staff_or_admin()
async def setbacknicknames_command(ctx):
    """Restore original nicknames for all claimed players"""
    loading_msg = await ctx.send("🔄 Restoring original nicknames...")

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Get all users with saved nicknames
    c.execute("""SELECT user_id, original_nickname 
                 FROM user_nicknames 
                 WHERE original_nickname IS NOT NULL""")
    nickname_data = c.fetchall()
    conn.close()

    restored_count = 0
    failed_list = []
    skipped_count = 0

    for user_id, original_nickname in nickname_data:
        # Try to fetch member
        try:
            member = await ctx.guild.fetch_member(user_id)
        except discord.NotFound:
            continue
        except discord.HTTPException:
            member = ctx.guild.get_member(user_id)
            if not member:
                continue

        # Skip if nickname is already the original
        if member.display_name == original_nickname:
            skipped_count += 1
            continue

        try:
            await member.edit(nick=original_nickname, reason=f"Nickname restore by {ctx.author}")
            restored_count += 1
        except discord.Forbidden:
            failed_list.append(f"<@{user_id}> - No permission")
        except discord.HTTPException as e:
            failed_list.append(f"<@{user_id}> - HTTP error")

    # Create summary embed
    embed = discord.Embed(
        title="✅ Nicknames Restored",
        color=0x00FF00
    )

    summary = f"✅ **Restored:** {restored_count}\n"
    summary += f"ℹ️ **Already Original:** {skipped_count}\n"
    summary += f"❌ **Failed:** {len(failed_list)}"

    embed.add_field(name="Summary", value=summary, inline=False)

    if failed_list:
        failures = "\n".join([f"• {f}" for f in failed_list[:10]])
        if len(failed_list) > 10:
            failures += f"\n...and {len(failed_list) - 10} more."

        embed.add_field(name="Failed", value=failures, inline=False)

    embed.set_footer(text=f"Restored by {ctx.author.name}")
    embed.timestamp = discord.utils.utcnow()

    await loading_msg.delete()
    await ctx.send(embed=embed)

# Optional: Command to check current nickname status
@bot.command(name="mynickname", aliases=["mn"], help="Check your current nickname status")
async def mynickname_command(ctx):
    """Check current nickname information"""

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Get player info
    c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", 
              (ctx.author.id,))
    player_result = c.fetchone()

    if not player_result:
        await ctx.send("❌ You haven't claimed a player yet!")
        conn.close()
        return

    player_name = player_result[0]

    # Get nickname info
    c.execute("""SELECT original_nickname, custom_nickname, last_synced 
                 FROM user_nicknames WHERE user_id = ?""", (ctx.author.id,))
    nickname_result = c.fetchone()
    conn.close()

    embed = discord.Embed(
        title="📝 Your Nickname Status",
        color=0x0066CC
    )

    embed.add_field(name="Player", value=player_name, inline=False)
    embed.add_field(name="Current Display Name", value=ctx.author.display_name, inline=False)

    if nickname_result:
        original, custom, last_synced = nickname_result
        embed.add_field(name="Original Nickname", value=original or "Not saved", inline=True)
        embed.add_field(name="Custom Nickname", value=custom or "Not set", inline=True)

        if last_synced:
            embed.add_field(
                name="Last Synced",
                value=f"<t:{int(datetime.strptime(last_synced, '%Y-%m-%d %H:%M:%S').timestamp())}:R>",
                inline=False
            )
    else:
        embed.add_field(name="Status", value="Not synced yet", inline=False)

    embed.set_footer(text="Use /setnickname to change your custom nickname")

    await ctx.send(embed=embed)

@bot.command(name="playm", help="[ADMIN] Play national anthems in voice channel")
@is_staff_or_admin()
async def playm_command(ctx):
    """Play pak.mp3 and ind.mp3 in voice channel with intervals"""

    # Get the voice channel
    VOICE_CHANNEL_ID = 1464599261336567933
    voice_channel = bot.get_channel(VOICE_CHANNEL_ID)

    if not voice_channel:
        await ctx.send("❌ Voice channel not found!")
        return

    if not isinstance(voice_channel, discord.VoiceChannel):
        await ctx.send("❌ The specified channel is not a voice channel!")
        return

    # Check if already connected and disconnect first
    for vc in bot.voice_clients:
        if vc.guild == ctx.guild:
            await vc.disconnect(force=True)
            await asyncio.sleep(1)

    voice_client = None

    try:
        # Send initial message
        status_msg = await ctx.send("🔄 Connecting to voice channel...")

        # Try to connect with a timeout
        try:
            voice_client = await asyncio.wait_for(
                voice_channel.connect(timeout=60, reconnect=False),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            await status_msg.edit(content="❌ Connection timed out. Voice connections may not be supported on this hosting platform (Replit).")
            return
        except discord.errors.ConnectionClosed as e:
            await status_msg.edit(content=f"❌ Connection failed with error code {e.code}.\n"
                                         f"**Note:** Voice connections often don't work on Replit due to network restrictions.\n"
                                         f"Consider hosting on a VPS or local machine for voice features.")
            return

        await status_msg.edit(content="✅ Connected! Starting playback in 7 seconds...")

        # Wait 7 seconds before starting
        await asyncio.sleep(7)

        # Define a helper function to play audio and wait
        async def play_audio(file_path, name):
            if not voice_client or not voice_client.is_connected():
                raise Exception("Voice client disconnected")

            # Check if file exists
            import os
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"{file_path} not found")

            await status_msg.edit(content=f"🎵 Now playing: {name}")

            # Create audio source
            audio_source = discord.FFmpegPCMAudio(file_path)
            voice_client.play(audio_source)

            # Wait for audio to finish
            while voice_client.is_playing():
                await asyncio.sleep(0.5)

        # Play pak.mp3
        await play_audio("pak.mp3", "pak.mp3")

        # Wait 15 seconds interval
        await status_msg.edit(content="⏸️ 15 second interval...")
        await asyncio.sleep(15)

        # Play ind.mp3
        await play_audio("ind.mp3", "ind.mp3")

        # Disconnect from voice channel
        await status_msg.edit(content="✅ Playback finished! Leaving voice channel...")
        await voice_client.disconnect()

    except FileNotFoundError as e:
        await ctx.send(f"❌ Audio file not found: {e}\nMake sure pak.mp3 and ind.mp3 are in the bot's directory.")
        if voice_client:
            await voice_client.disconnect()
    except discord.ClientException as e:
        await ctx.send(f"❌ Discord client error: {e}")
        if voice_client:
            await voice_client.disconnect()
    except Exception as e:
        await ctx.send(f"❌ An error occurred: {e}")
        if voice_client:
            try:
                await voice_client.disconnect()
            except:
                pass

# Alternative command if voice doesn't work
@bot.command(name="checkvoice", help="[ADMIN] Check if voice is supported")
@is_staff_or_admin()
async def checkvoice_command(ctx):
    """Check if voice features are available"""

    embed = discord.Embed(
        title="🔊 Voice Support Check",
        color=0x0066CC
    )

    # Check intents
    has_voice_intent = bot.intents.voice_states
    has_guilds_intent = bot.intents.guilds

    embed.add_field(
        name="Required Intents",
        value=f"Voice States: {'✅' if has_voice_intent else '❌'}\n"
              f"Guilds: {'✅' if has_guilds_intent else '❌'}",
        inline=False
    )

    # Check PyNaCl
    try:
        import nacl
        pynacl_installed = "✅ Installed"
    except ImportError:
        pynacl_installed = "❌ Not installed (run: pip install PyNaCl)"

    embed.add_field(name="PyNaCl", value=pynacl_installed, inline=False)

    # Check FFmpeg
    import subprocess
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        ffmpeg_installed = "✅ Installed"
    except:
        ffmpeg_installed = "❌ Not installed or not in PATH"

    embed.add_field(name="FFmpeg", value=ffmpeg_installed, inline=False)

    # Platform warning
    import platform
    system_info = f"{platform.system()} {platform.release()}"
    embed.add_field(name="System", value=system_info, inline=False)

    embed.add_field(
        name="⚠️ Important Note",
        value="Voice features often don't work on Replit or similar cloud platforms due to network restrictions. "
              "For reliable voice support, host the bot on a VPS or local machine.",
        inline=False
    )

    await ctx.send(embed=embed)

@bot.command(name="rulesall", help="[ADMIN] DM rules to all claimed bowlers")
@is_staff_or_admin()
async def rulesall_command(ctx):
    """DM rules embed to all claimed bowlers"""

    loading_msg = await ctx.send("🔄 Sending rules to all bowlers...")

    # Load teams data
    teams_data = load_players()

    # Get all bowlers
    bowler_users = []

    for team_data in teams_data:
        for player in team_data['players']:
            # Check if player is a bowler
            if "Bowler" in player['role']:
                # Get representative info
                rep_info = get_representative(player['name'])

                if rep_info:
                    user_id, username = rep_info
                    member = ctx.guild.get_member(user_id)

                    if member:
                        bowler_users.append({
                            'member': member,
                            'player_name': player['name'],
                            'team': team_data['team']
                        })

    if not bowler_users:
        await loading_msg.edit(content="❌ No claimed bowlers found!")
        return

    # Send DMs to all bowlers
    sent_count = 0
    failed_list = []

    for bowler_info in bowler_users:
        member = bowler_info['member']
        player_name = bowler_info['player_name']
        team = bowler_info['team']

        try:
            # Create embed
            embed = discord.Embed(
                title="🏏 CWC26 TFH HC Nations - Bowler Rules",
                description=(
                    f"You are playing as a **Bowler** in the CWC26 TFH HC Nations.\n\n"
                    f"Welcome. You will need to follow THIS ONE SIMPLE RULE **DURING YOUR BATTING**"
                ),
                color=0x0066CC
            )

            # Add player info
            flag = get_team_flag(team)
            embed.add_field(
                name="Your Player",
                value=f"{flag} **{player_name}** ({team})",
                inline=False
            )

            # Set image
            file = discord.File("well.png", filename="well.png")
            embed.set_image(url="attachment://well.png")

            embed.set_footer(text="CWC26 TFH HC Nations")

            # Send DM
            await member.send(embed=embed, file=file)
            sent_count += 1

            # Small delay to avoid rate limits
            await asyncio.sleep(1)

        except discord.Forbidden:
            failed_list.append(f"{player_name} (@{member.name}) - DMs disabled")
        except discord.HTTPException as e:
            failed_list.append(f"{player_name} (@{member.name}) - HTTP error")
        except FileNotFoundError:
            await loading_msg.edit(content="❌ well.png file not found!")
            return
        except Exception as e:
            failed_list.append(f"{player_name} (@{member.name}) - {str(e)}")

    # Create summary embed
    summary_embed = discord.Embed(
        title="✅ Rules DM Complete",
        color=0x00FF00
    )

    summary = f"✅ **Sent:** {sent_count}\n"
    summary += f"❌ **Failed:** {len(failed_list)}\n"
    summary += f"📊 **Total Bowlers:** {len(bowler_users)}"

    summary_embed.add_field(name="Summary", value=summary, inline=False)

    if failed_list:
        failures = "\n".join([f"• {f}" for f in failed_list[:10]])
        if len(failed_list) > 10:
            failures += f"\n...and {len(failed_list) - 10} more."

        summary_embed.add_field(name="Failed", value=failures, inline=False)

    summary_embed.set_footer(text=f"Executed by {ctx.author.name}")
    summary_embed.timestamp = discord.utils.utcnow()

    await loading_msg.delete()
    await ctx.send(embed=summary_embed)

@bot.command(name="deletereal", aliases=["dr"], help="[ADMIN] Permanently delete a player from all databases")
@is_staff_or_admin()
async def deletereal_command(ctx, *, player_name: str):
    """
    Permanently delete a player from all databases
    Usage: -deletereal player name
    """
    # Search for player in database
    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Search in player_representatives table
    c.execute("SELECT player_name, user_id, username FROM player_representatives WHERE player_name LIKE ?", 
              (f"%{player_name}%",))
    results = c.fetchall()

    if not results:
        await ctx.send(f"❌ Player '{player_name}' not found in database.")
        conn.close()
        return

    if len(results) > 1:
        embed = discord.Embed(
            title="🔍 Multiple Players Found",
            description=f"Multiple players match '{player_name}'. Please use the exact name:\n\n",
            color=0xFFA500
        )

        for i, (name, user_id, username) in enumerate(results, 1):
            embed.description += f"**{i}.** **{name}** (@{username})\n"

        await ctx.send(embed=embed)
        conn.close()
        return

    # Single match found
    exact_player_name, user_id, username = results[0]
    conn.close()

    # Confirmation embed
    confirm_embed = discord.Embed(
        title="⚠️ Confirm Permanent Deletion",
        description=f"Are you sure you want to **permanently delete** this player?\n\n"
                    f"**Player:** {exact_player_name}\n"
                    f"**Representative:** @{username}\n"
                    f"**User ID:** {user_id}\n\n"
                    f"This will remove them from:\n"
                    f"• Player representatives\n"
                    f"• Team captains\n"
                    f"• Match stats\n"
                    f"• Elite players\n"
                    f"• Player emojis\n"
                    f"• User nicknames\n\n"
                    f"**This action cannot be undone!**",
        color=0xFF0000
    )

    confirm_msg = await ctx.send(embed=confirm_embed)
    await confirm_msg.add_reaction("✅")
    await confirm_msg.add_reaction("❌")

    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == confirm_msg.id

    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=30.0, check=check)
    except asyncio.TimeoutError:
        await confirm_msg.edit(embed=discord.Embed(
            title="❌ Deletion Cancelled",
            description="Confirmation timed out.",
            color=0x808080
        ))
        await confirm_msg.clear_reactions()
        return

    if str(reaction.emoji) == "❌":
        await confirm_msg.edit(embed=discord.Embed(
            title="❌ Deletion Cancelled",
            description=f"**{exact_player_name}** was not deleted.",
            color=0x808080
        ))
        await confirm_msg.clear_reactions()
        return

    # User confirmed - proceed with deletion
    await confirm_msg.clear_reactions()
    await confirm_msg.edit(embed=discord.Embed(
        title="🔄 Deleting Player...",
        description="Please wait...",
        color=0xFFA500
    ))

    deletion_log = []
    _, deleted_player_teams = find_player(exact_player_name)

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # 1. Remove from player_representatives
    c.execute("DELETE FROM player_representatives WHERE player_name = ?", (exact_player_name,))
    if c.rowcount > 0:
        deletion_log.append(f"✅ Removed from player representatives")
    conn.commit()

    # 2. Remove from team_captains
    c.execute("DELETE FROM team_captains WHERE player_name = ?", (exact_player_name,))
    if c.rowcount > 0:
        deletion_log.append(f"✅ Removed from team captains")
    conn.commit()

    # 3. Remove from team vice-captains
    c.execute("DELETE FROM team_vice_captains WHERE player_name = ?", (exact_player_name,))
    if c.rowcount > 0:
        deletion_log.append(f"✅ Removed from team vice-captains")
    conn.commit()

    # 4. Remove from match_stats (using user_id)
    c.execute("DELETE FROM match_stats WHERE user_id = ?", (user_id,))
    if c.rowcount > 0:
        deletion_log.append(f"✅ Removed {c.rowcount} match stat entries")
    conn.commit()

    # 4. Remove from user_nicknames
    c.execute("DELETE FROM user_nicknames WHERE user_id = ?", (user_id,))
    if c.rowcount > 0:
        deletion_log.append(f"✅ Removed from user nicknames")
    conn.commit()

    conn.close()

    for affected_team in deleted_player_teams or []:
        asyncio.get_event_loop().create_task(
            refresh_squad_image_cache(affected_team, ctx.guild)
        )

    # 5. Remove from elite players
    if exact_player_name in elite_players:
        elite_players.remove(exact_player_name)
        save_elite_players()
        deletion_log.append(f"✅ Removed from elite players")

    # 6. Remove player emoji
    emoji_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in exact_player_name)[:32]
    emoji_removed = False

    for guild in get_emoji_guilds(bot):
        emoji_obj = discord.utils.get(guild.emojis, name=emoji_name)
        if emoji_obj:
            try:
                await emoji_obj.delete(reason=f"Player deletion by {ctx.author}")
                deletion_log.append(f"✅ Removed emoji from {guild.name}")
                emoji_removed = True
            except:
                deletion_log.append(f"⚠️ Failed to remove emoji from {guild.name}")

    # Remove from emoji mappings
    if exact_player_name in player_emojis:
        del player_emojis[exact_player_name]
        with open('player_emojis.json', 'w') as f:
            json.dump(player_emojis, f, indent=2)
        if not emoji_removed:
            deletion_log.append(f"✅ Removed from emoji mappings")

    # Create final embed
    final_embed = discord.Embed(
        title="✅ Player Permanently Deleted",
        description=f"**{exact_player_name}** (@{username}) has been permanently deleted from all databases.",
        color=0xFF0000
    )

    if deletion_log:
        final_embed.add_field(
            name="Deletion Log",
            value="\n".join(deletion_log),
            inline=False
        )

    final_embed.set_footer(text=f"Deleted by {ctx.author.name}")
    final_embed.timestamp = discord.utils.utcnow()

    await confirm_msg.edit(embed=final_embed)

def get_team_color_rgb(team_name):
    """Get team color as RGB tuple for image generation"""
    colors = {
        "India": (0, 102, 204),
        "Pakistan": (0, 100, 0),
        "Australia": (255, 215, 0),
        "England": (1, 33, 105),
        "New Zealand": (0, 0, 0),
        "South Africa": (0, 107, 63),
        "West Indies": (123, 0, 65),
        "Sri Lanka": (0, 61, 165),
        "Bangladesh": (0, 106, 78),
        "Afghanistan": (83, 99, 237),
        "Netherlands": (255, 54, 0),
        "Scotland": (161, 0, 242),
        "Ireland": (157, 255, 46),
        "Zimbabwe": (255, 33, 33),
        "UAE": (252, 68, 68),
        "Canada": (255, 0, 0),
        "USA": (8, 0, 38)
    }
    return colors.get(team_name, (128, 128, 128))


@bot.tree.command(name="dom", description="[ADMIN] Create Player of the Match graphic")
@app_commands.describe(
    text="Achievement text to display",
    user="Discord user to feature"
)
@is_staff_or_admin_slash()
async def dom_command(interaction: discord.Interaction, text: str, user: discord.Member):
    """Generate a Player of the Match graphic"""

    # ========================================
    # 🎯 EASY COORDINATE CONFIGURATION
    # ========================================
    # Just edit these coordinates to move elements around!

    LAYOUT = {
        # Flag position (top left)
        'flag_x': 5,
        'flag_y': 0,
        'flag_size': 140,

        # User avatar position (top right area)
        'avatar_x': 220,
        'avatar_y': 100,
        'avatar_size': 100,

        # Player image position (right side)
        'player_x': -25,
        'player_y': 24,
        'player_size': 350,

        # Text positions - each with independent X coordinate
        'player_name_x': 190,
        'player_name_y': 20,
        'player_name_size': 50,
        'player_name_max_width': 300,  # Max width before scaling down

        'username_x': 330,
        'username_y': 130,
        'username_size': 20,
        'username_max_width': 300,  # Max width before scaling down

        'achievement_x': 230,
        'achievement_y': 270,
        'achievement_size': 20,
        'achievement_max_width': 300,  # Max width for achievement text

        'team_name_x': 1000,
        'team_name_y': None,  # Will auto-calculate below achievement text
        'team_name_size': 40,
        'team_name_spacing': 60,

        # Text styling
        'text_outline_width': 3,
        'text_color': (255, 255, 255),      # White
        'text_outline_color': (0, 0, 0),    # Black
    }

    # ========================================
    # END OF EASY CONFIGURATION
    # ========================================

    await interaction.response.defer(ephemeral=True)

    # Get player info from database
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", (user.id,))
    result = c.fetchone()
    conn.close()

    if not result:
        await interaction.followup.send("❌ This user hasn't claimed a player yet!", ephemeral=True)
        return

    player_name = result[0]

    # Get player data
    players, team_names = find_player(player_name)

    if not players:
        await interaction.followup.send("❌ Player data not found!", ephemeral=True)
        return

    player_data = players[0]
    team_name = team_names[0]

    try:
        # Load background
        bg = Image.open("starbackground.png").convert('RGBA')
        width, height = bg.size

        print(f"Image size: {width}x{height}")

        # ========================================
        # CREATE GRADIENT OVERLAY
        # ========================================
        # Get team color
        team_color = get_team_color_rgb(team_name)

        # Create overlay for gradient
        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay, 'RGBA')

        # Create smooth fading gradient from left side with team color
        for x in range(width // 2):
            progress = x / (width // 2)
            alpha = int(150 * (1 - progress))  # Fade from left to transparent

            for y in range(height):
                draw_overlay.point((x, y), fill=team_color + (alpha,))

        # Composite overlay onto background
        img = Image.alpha_composite(bg, overlay)

        # Load fonts
        try:
            player_name_font = ImageFont.truetype("nor.otf", LAYOUT['player_name_size'])
            username_font = ImageFont.truetype("nor.otf", LAYOUT['username_size'])
            text_font = ImageFont.truetype("nor.otf", LAYOUT['achievement_size'])
            team_font = ImageFont.truetype("nor.otf", LAYOUT['team_name_size'])
            print("✅ Loaded fonts")
        except Exception as e:
            print(f"❌ Failed to load fonts: {e}")
            try:
                player_name_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", LAYOUT['player_name_size'])
                username_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", LAYOUT['username_size'])
                text_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", LAYOUT['achievement_size'])
                team_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", LAYOUT['team_name_size'])
                print("✅ Loaded DejaVu fonts")
            except Exception as e2:
                print(f"❌ Failed to load DejaVu fonts: {e2}")
                player_name_font = ImageFont.load_default()
                username_font = ImageFont.load_default()
                text_font = ImageFont.load_default()
                team_font = ImageFont.load_default()
                print("⚠️ Using default font")

        async with aiohttp.ClientSession() as session:
            # ========================================
            # PLACE FLAG
            # ========================================
            flag_x = LAYOUT['flag_x']
            flag_y = LAYOUT['flag_y']
            flag_size = LAYOUT['flag_size']

            if team_name.lower() == "west indies":
                try:
                    flag_img = Image.open("westindies.jpg").convert('RGBA')
                    flag_img = flag_img.resize((flag_size, flag_size), Image.Resampling.LANCZOS)

                    mask = Image.new('L', (flag_size, flag_size), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.ellipse((0, 0, flag_size, flag_size), fill=255)

                    circular_flag = Image.new('RGBA', (flag_size, flag_size), (0, 0, 0, 0))
                    circular_flag.paste(flag_img, (0, 0), mask)

                    img.paste(circular_flag, (flag_x, flag_y), circular_flag)
                    print(f"✅ Pasted West Indies flag at ({flag_x}, {flag_y})")
                except Exception as e:
                    print(f"❌ Error loading West Indies flag: {e}")
            else:
                flag_url = get_team_flag_url(team_name)
                if flag_url:
                    try:
                        async with session.get(flag_url) as resp:
                            if resp.status == 200:
                                flag_data = await resp.read()
                                flag_img = Image.open(io.BytesIO(flag_data)).convert('RGBA')
                                flag_img = flag_img.resize((flag_size, flag_size), Image.Resampling.LANCZOS)

                                mask = Image.new('L', (flag_size, flag_size), 0)
                                mask_draw = ImageDraw.Draw(mask)
                                mask_draw.ellipse((0, 0, flag_size, flag_size), fill=255)

                                circular_flag = Image.new('RGBA', (flag_size, flag_size), (0, 0, 0, 0))
                                circular_flag.paste(flag_img, (0, 0), mask)

                                img.paste(circular_flag, (flag_x, flag_y), circular_flag)
                                print(f"✅ Pasted {team_name} flag at ({flag_x}, {flag_y})")
                    except Exception as e:
                        print(f"❌ Error loading team flag: {e}")

            # ========================================
            # PLACE USER AVATAR
            # ========================================
            avatar_x = LAYOUT['avatar_x']
            avatar_y = LAYOUT['avatar_y']
            avatar_size = LAYOUT['avatar_size']

            if user.avatar:
                try:
                    async with session.get(str(user.avatar.url)) as resp:
                        if resp.status == 200:
                            avatar_data = await resp.read()
                            avatar_img = Image.open(io.BytesIO(avatar_data)).convert('RGBA')
                        else:
                            avatar_img = Image.new('RGBA', (avatar_size, avatar_size), (128, 128, 128, 255))
                except:
                    avatar_img = Image.new('RGBA', (avatar_size, avatar_size), (128, 128, 128, 255))
            else:
                avatar_img = Image.new('RGBA', (avatar_size, avatar_size), (128, 128, 128, 255))

            avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)

            mask = Image.new('L', (avatar_size, avatar_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)

            border_thickness = 6
            bordered_size = avatar_size + (border_thickness * 2)
            bordered_avatar = Image.new('RGBA', (bordered_size, bordered_size), (255, 255, 255, 255))

            border_mask = Image.new('L', (bordered_size, bordered_size), 0)
            border_mask_draw = ImageDraw.Draw(border_mask)
            border_mask_draw.ellipse((0, 0, bordered_size, bordered_size), fill=255)

            bordered_avatar.paste(avatar_img, (border_thickness, border_thickness), mask)

            img.paste(bordered_avatar, (avatar_x - border_thickness, avatar_y - border_thickness), border_mask)
            print(f"✅ Pasted user avatar at ({avatar_x}, {avatar_y})")

            # ========================================
            # PLACE PLAYER IMAGE
            # ========================================
            player_x = LAYOUT['player_x']
            player_y = LAYOUT['player_y']
            player_size = LAYOUT['player_size']

            player_img = None
            if player_data.get('image'):
                try:
                    async with session.get(player_data['image']) as resp:
                        if resp.status == 200:
                            img_data = await resp.read()
                            player_img = Image.open(io.BytesIO(img_data)).convert('RGBA')
                            print("✅ Downloaded player image")
                except Exception as e:
                    print(f"❌ Error downloading player image: {e}")

            if not player_img:
                try:
                    player_img = Image.open("fallback.webp").convert('RGBA')
                    print("✅ Using fallback image")
                except:
                    await interaction.followup.send("❌ Could not load player image!", ephemeral=True)
                    return

            player_img = player_img.resize((player_size, player_size), Image.Resampling.LANCZOS)
            img.paste(player_img, (player_x, player_y), player_img)
            print(f"✅ Pasted player image at ({player_x}, {player_y})")

        # ========================================
        # DRAW ALL TEXT
        # ========================================
        img = img.convert('RGB')
        draw = ImageDraw.Draw(img)

        text_color = LAYOUT['text_color']
        outline_color = LAYOUT['text_outline_color']
        outline_width = LAYOUT['text_outline_width']

        # ========================================
        # Draw Player Name (WITH OUTLINE)
        # ========================================
        player_name_x = LAYOUT['player_name_x']
        player_name_y = LAYOUT['player_name_y']

        # Check if player name is too wide
        current_font = player_name_font
        bbox = draw.textbbox((0, 0), player_name, font=current_font)
        text_width = bbox[2] - bbox[0]

        # Scale down font if text is too wide
        if text_width > LAYOUT['player_name_max_width']:
            scale_factor = LAYOUT['player_name_max_width'] / text_width
            new_size = int(LAYOUT['player_name_size'] * scale_factor)
            try:
                current_font = ImageFont.truetype("nor.otf", new_size)
            except:
                try:
                    current_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", new_size)
                except:
                    current_font = ImageFont.load_default()

        print(f"Drawing player name '{player_name}' at ({player_name_x}, {player_name_y})")

        # Draw outline
        for adj_x in range(-outline_width, outline_width + 1):
            for adj_y in range(-outline_width, outline_width + 1):
                draw.text((player_name_x + adj_x, player_name_y + adj_y), player_name, font=current_font, fill=outline_color)
        # Draw main text
        draw.text((player_name_x, player_name_y), player_name, font=current_font, fill=text_color)

        # ========================================
        # Draw Username (NO OUTLINE)
        # ========================================
        username_text = f"@{user.name}"
        username_x = LAYOUT['username_x']
        username_y = LAYOUT['username_y']

        # Check if username is too wide
        current_username_font = username_font
        bbox = draw.textbbox((0, 0), username_text, font=current_username_font)
        text_width = bbox[2] - bbox[0]

        # Scale down font if text is too wide
        if text_width > LAYOUT['username_max_width']:
            scale_factor = LAYOUT['username_max_width'] / text_width
            new_size = int(LAYOUT['username_size'] * scale_factor)
            try:
                current_username_font = ImageFont.truetype("nor.otf", new_size)
            except:
                try:
                    current_username_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", new_size)
                except:
                    current_username_font = ImageFont.load_default()

        print(f"Drawing username '{username_text}' at ({username_x}, {username_y})")
        draw.text((username_x, username_y), username_text, font=current_username_font, fill=text_color)

        # ========================================
        # Draw Achievement Text (NO OUTLINE, NO WORD WRAP)
        # ========================================
        achievement_x = LAYOUT['achievement_x']
        achievement_y = LAYOUT['achievement_y']

        # Check if achievement text is too wide
        current_achievement_font = text_font
        bbox = draw.textbbox((0, 0), text, font=current_achievement_font)
        text_width = bbox[2] - bbox[0]

        # Scale down font if text is too wide
        if text_width > LAYOUT['achievement_max_width']:
            scale_factor = LAYOUT['achievement_max_width'] / text_width
            new_size = int(LAYOUT['achievement_size'] * scale_factor)
            try:
                current_achievement_font = ImageFont.truetype("nor.otf", new_size)
            except:
                try:
                    current_achievement_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", new_size)
                except:
                    current_achievement_font = ImageFont.load_default()

        print(f"Drawing achievement text '{text}' at ({achievement_x}, {achievement_y})")
        draw.text((achievement_x, achievement_y), text, font=current_achievement_font, fill=text_color)

        # ========================================
        # Draw Team Name (NO OUTLINE)
        # ========================================
        team_name_x = LAYOUT['team_name_x']
        team_name_y = achievement_y + LAYOUT['team_name_spacing']

        print(f"Drawing team name '{team_name}' at ({team_name_x}, {team_name_y})")
        draw.text((team_name_x, team_name_y), team_name, font=team_font, fill=text_color)

        # ========================================
        # SAVE AND SEND
        # ========================================
        output = io.BytesIO()
        img.save(output, format='PNG', quality=95)
        output.seek(0)

        embed = discord.Embed(
            title="🎗️ SPOTLIGHT Perfomance",
            color=get_team_color(team_name)
        )

        embed.set_image(url="attachment://player_of_match.png")
        embed.set_footer(text="CWC HEROES™")

        file = discord.File(output, filename="player_of_match.png")
        message = await interaction.channel.send(embed=embed, file=file)

        # Add fire emoji reaction
        await message.add_reaction("🔥")

        print("✅ Sent image to channel")

        await interaction.followup.send("✅ Player of the Match graphic sent!", ephemeral=True)

    except FileNotFoundError as e:
        error_msg = f"❌ File not found: {e}\nMake sure starbackground.png and fonts are in the bot's directory!"
        await interaction.followup.send(error_msg, ephemeral=True)
        print(error_msg)
    except Exception as e:
        error_msg = f"❌ Error creating graphic: {e}"
        await interaction.followup.send(error_msg, ephemeral=True)
        print(error_msg)
        import traceback
        traceback.print_exc()

@dom_command.error
async def dom_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You need administrator permissions to use this command!", ephemeral=True)

# ========================================
# COMMENTATOR SYSTEM
# ========================================
commentator_assignments = {}  # Format: {user_id: "Commentator Name"}

@bot.command(name='commentator')
@is_staff_or_admin()
async def assign_commentator(ctx, member: discord.Member, *, commentator_name: str):
    """Assign a commentator role to a user"""
    commentator_assignments[member.id] = commentator_name
    await ctx.send(f"✅ {member.mention} has been assigned as **{commentator_name}**!")

@bot.tree.command(name="commentate", description="Post a commentary message")
@app_commands.describe(text="Your commentary text")
async def commentate(interaction: discord.Interaction, text: str):
    """Post commentary if user is assigned as a commentator"""
    user_id = interaction.user.id

    # Check if user is assigned as a commentator
    if user_id not in commentator_assignments:
        await interaction.response.send_message("❌ You are not assigned as a commentator!", ephemeral=True)
        return

    commentator_name = commentator_assignments[user_id]

    # Determine thumbnail based on commentator name
    thumbnail_url = None
    if "Ravi Shastri" in commentator_name:
        thumbnail_url = "https://i.ibb.co/Q7D7Gfp1/shastri.jpg"
    elif "Grant Elliot" in commentator_name:
        thumbnail_url = "https://i.ibb.co/7J6jZcrZ/images-2.jpg"

    # Create embed
    embed = discord.Embed(
        title="LIVE MATCH",
        description=f'*"{text}"*',
        color=discord.Color.blue()
    )

    # Set author with commentator info and user's avatar
    embed.set_author(
        name=f"Commentator: {commentator_name} (@{interaction.user.name})",
        icon_url=interaction.user.display_avatar.url
    )

    # Set thumbnail if available
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)

    # Set footer
    embed.set_footer(
        text="TFH CWC26 FINALS",
        icon_url="https://i.ibb.co/dsLVTTYb/HC-Nations-CWC-Pakistan-2026.png"
    )

    # Send hidden response to user
    await interaction.response.send_message("✅ Commentary posted!", ephemeral=True)

    # Send the embed to the channel
    message = await interaction.channel.send(embed=embed)

    # Add reaction emojis
    await message.add_reaction("🔥")
    await message.add_reaction("😭")
    await message.add_reaction("🤯")
    await message.add_reaction("👍")
    await message.add_reaction("🥱")

@assign_commentator.error
async def assign_commentator_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need administrator permissions to assign commentators!")

    @bot.command(name="oldreps", help="View all players you previously represented")
    async def oldreps_command(ctx, member: discord.Member = None):
        target = member or ctx.author

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS old_representatives
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      player_name TEXT,
                      removed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

        c.execute("""SELECT player_name, removed_at FROM old_representatives 
                     WHERE user_id = ? ORDER BY removed_at DESC""", (target.id,))
        results = c.fetchall()
        conn.close()

        if not results:
            await ctx.send(f"❌ {'You have' if target == ctx.author else f'{target.name} has'} no previous player history.")
            return

        embed = discord.Embed(
            title=f"📜 {target.name}'s Player History",
            description=f"All players previously represented by {target.mention}:",
            color=0x0066CC
        )

        history_text = ""
        for player_name, removed_at in results:
            players, team_names = find_player(player_name)
            flag = get_team_flag(team_names[0]) if team_names else "🏳️"
            try:
                dt = datetime.strptime(removed_at, '%Y-%m-%d %H:%M:%S')
                timestamp = f"<t:{int(dt.timestamp())}:D>"
            except:
                timestamp = removed_at

            history_text += f"{flag} **{player_name}** — left {timestamp}\n"

        embed.description = history_text
        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=embed)

@bot.command(name="fetchonline")
async def fetchonline(ctx):
    if ctx.guild is None:
        await ctx.send("This command can only be used inside a server!")
        return

    online_members = []
    offline_members = []

    # Sort members into online and offline lists
    for member in ctx.guild.members:
        # We use display_name to get their server nickname, or their username if they don't have one
        if member.status != discord.Status.offline:
            online_members.append(member.display_name)
        else:
            offline_members.append(member.display_name)

    # Helper function to prevent the bot from crashing if the list of names is too long
    def format_names(name_list):
        if not name_list:
            return "None"

        full_string = ", ".join(name_list)

        # If the string is safely under Discord's 1024 character limit, return it
        if len(full_string) <= 1000:
            return full_string

        # If it's too long, truncate it safely
        truncated_string = ""
        added_count = 0
        for name in name_list:
            # Leave room for the "... and X more" text
            if len(truncated_string) + len(name) + 2 > 900: 
                break
            truncated_string += name + ", "
            added_count += 1

        remaining = len(name_list) - added_count
        return truncated_string + f"**...and {remaining} more**"

    # Create the embed
    embed = discord.Embed(
        title=f"👥 Member Status in {ctx.guild.name}",
        color=discord.Color.blue()
    )

    # Add the online and offline fields
    embed.add_field(
        name=f"🟢 Online ({len(online_members)})", 
        value=format_names(online_members), 
        inline=False
    )
    embed.add_field(
        name=f"⚪ Offline ({len(offline_members)})", 
        value=format_names(offline_members), 
        inline=False
    )

    await ctx.send(embed=embed)

@bot.command(name="allunc", help="[OWNER] DM all members with the unclaimed role")
async def allunc_command(ctx):
    OWNER_ID = 765965975761715241
    TARGET_ROLE_ID = 1461764869282857010

    if ctx.author.id != OWNER_ID:
        return

    role = ctx.guild.get_role(TARGET_ROLE_ID)
    if not role:
        await ctx.send("❌ Could not find the target role.")
        return

    members = [m for m in role.members if not m.bot]
    if not members:
        await ctx.send("❌ No members found with that role.")
        return

    status_msg = await ctx.send(f"⏳ Sending DMs to **{len(members)}** members…")

    embed = discord.Embed(
        title="Join FIRST EVER ODI WC with 30 TEAMS! ⭐",
        description=(
            "**SAY -rep in https://discord.com/channels/1451591563078533292/1452997837330714704 "
            "to REPRESENT A PLAYER AND GET STARTED!**\n\n"
            "Or captain a nation"
        ),
        color=0xFFD700
    )
    embed.set_image(url="https://i.ibb.co/Fb3fz5Ld/LET-S-PLAY-13.png")

    sent = 0
    failed = 0
    for member in members:
        try:
            await member.send(embed=embed)
            sent += 1
            await asyncio.sleep(1.0)
        except Exception:
            failed += 1

    await status_msg.edit(
        content=f"✅ Done! Sent: **{sent}** | Failed (DMs closed): **{failed}**"
    )


# ══════════════════════════════════════════════════════════════
# EMBED MANAGER  (owner-only: 765965975761715241)
# ══════════════════════════════════════════════════════════════
_EMBED_OWNER_ID = 765965975761715241

def _init_embeds_table():
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS user_embeds (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        title       TEXT    DEFAULT '',
        description TEXT    DEFAULT '',
        image_url   TEXT    DEFAULT '',
        color       INTEGER DEFAULT 5814143,
        footer      TEXT    DEFAULT '',
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()


# ── DB helpers ────────────────────────────────────────────────
def _em_save(user_id, title, description, image_url, color, footer):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(
        "INSERT INTO user_embeds (user_id,title,description,image_url,color,footer) "
        "VALUES (?,?,?,?,?,?)",
        (user_id, title, description, image_url, color, footer)
    )
    conn.commit()
    eid = c.lastrowid
    conn.close()
    return eid

def _em_list(user_id):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(
        "SELECT id,title,description,image_url,color,footer,created_at "
        "FROM user_embeds WHERE user_id=? ORDER BY created_at DESC",
        (user_id,)
    )
    rows = c.fetchall()
    conn.close()
    return rows

def _em_get(embed_id):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(
        "SELECT id,title,description,image_url,color,footer "
        "FROM user_embeds WHERE id=?",
        (embed_id,)
    )
    row = c.fetchone()
    conn.close()
    return row

def _em_update(embed_id, title, description, image_url, color, footer):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(
        "UPDATE user_embeds SET title=?,description=?,image_url=?,color=?,footer=? "
        "WHERE id=?",
        (title, description, image_url, color, footer, embed_id)
    )
    conn.commit()
    conn.close()

def _em_build(row) -> discord.Embed:
    """Turn a DB row (id,title,desc,image,color,footer) into a discord.Embed."""
    _, title, description, image_url, color, footer = row
    embed = discord.Embed(color=color or 0x58B9FF)
    if title:       embed.title       = title
    if description: embed.description = description
    if image_url:   embed.set_image(url=image_url)
    if footer:      embed.set_footer(text=footer)
    return embed


# ── Modify modal (5 fields: title / description / image / color / footer) ──
class EmbedModifyModal(discord.ui.Modal, title="✏️ Modify Embed"):
    m_title = discord.ui.TextInput(
        label="Title", required=False, max_length=256,
        placeholder="Leave blank to have no title"
    )
    m_description = discord.ui.TextInput(
        label="Description", required=False,
        style=discord.TextStyle.paragraph, max_length=4000,
        placeholder="Main body of the embed"
    )
    m_image = discord.ui.TextInput(
        label="Image URL", required=False, max_length=512,
        placeholder="https://… (leave blank to remove)"
    )
    m_color = discord.ui.TextInput(
        label="Color (hex, e.g. #FF5733)", required=False, max_length=7,
        placeholder="#58B9FF"
    )
    m_footer = discord.ui.TextInput(
        label="Footer text", required=False, max_length=2048,
        placeholder="Leave blank to remove footer"
    )

    def __init__(self, embed_id: int, row):
        super().__init__()
        self.embed_id = embed_id
        _, title, desc, img, color, footer = row
        if title:   self.m_title.default       = title
        if desc:    self.m_description.default  = desc
        if img:     self.m_image.default        = img
        if color:   self.m_color.default        = f"#{color:06X}"
        if footer:  self.m_footer.default       = footer

    async def on_submit(self, interaction: discord.Interaction):
        title       = self.m_title.value.strip()
        description = self.m_description.value.strip()
        image_url   = self.m_image.value.strip()
        footer      = self.m_footer.value.strip()
        raw_color   = self.m_color.value.strip().lstrip('#')
        try:
            color = int(raw_color, 16) if raw_color else 0x58B9FF
        except ValueError:
            color = 0x58B9FF

        _em_update(self.embed_id, title, description, image_url, color, footer)
        new_row   = _em_get(self.embed_id)
        new_embed = _em_build(new_row)
        new_embed.set_author(name=f"✅ Embed #{self.embed_id} updated — preview:")
        view = EmbedActionView(self.embed_id, interaction.user.id)
        await interaction.response.send_message(embed=new_embed, view=view)


# ── Confirm-before-DM view ────────────────────────────────────
class ConfirmDMSendView(discord.ui.View):
    def __init__(self, embed_id: int, owner_id: int, guild: discord.Guild):
        super().__init__(timeout=60)
        self.embed_id = embed_id
        self.owner_id = owner_id
        self.guild    = guild

    @discord.ui.button(label="✅ Yes, send to everyone", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Not your button.", ephemeral=True)
        row = _em_get(self.embed_id)
        if not row:
            return await interaction.response.send_message("❌ Embed not found.", ephemeral=True)
        embed   = _em_build(row)
        members = [m for m in self.guild.members if not m.bot]
        channel = interaction.channel
        await interaction.response.edit_message(
            content=f"⏳ Sending to **{len(members)}** members…", embed=None, view=None
        )
        sent = failed = 0
        for member in members:
            try:
                await member.send(embed=embed)
                sent += 1
                await asyncio.sleep(0.8)
            except Exception:
                failed += 1
        # Use channel.send instead of edit_original_response —
        # the interaction token expires after 15 min and the DM loop
        # can easily exceed that for large servers.
        await channel.send(
            f"✅ Done! Sent: **{sent}** | Failed (DMs closed): **{failed}**"
        )
        self.stop()

    @discord.ui.button(label="✖ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Not your button.", ephemeral=True)
        await interaction.response.edit_message(content="❌ Cancelled.", embed=None, view=None)
        self.stop()


# ── Action view shown under every embed preview ───────────────
class EmbedActionView(discord.ui.View):
    def __init__(self, embed_id: int, owner_id: int):
        super().__init__(timeout=300)
        self.embed_id = embed_id
        self.owner_id = owner_id

    @discord.ui.button(label="✏️ Modify", style=discord.ButtonStyle.primary)
    async def modify_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Not your button.", ephemeral=True)
        row = _em_get(self.embed_id)
        if not row:
            return await interaction.response.send_message("❌ Embed not found.", ephemeral=True)
        await interaction.response.send_modal(EmbedModifyModal(self.embed_id, row))

    @discord.ui.button(label="📨 Send to All DMs", style=discord.ButtonStyle.danger)
    async def send_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Not your button.", ephemeral=True)
        members = [m for m in interaction.guild.members if not m.bot]
        view    = ConfirmDMSendView(self.embed_id, self.owner_id, interaction.guild)
        await interaction.response.send_message(
            content=(
                f"⚠️ This will DM **{len(members)}** members in **{interaction.guild.name}**.\n"
                f"Are you sure you want to send this embed to everyone?"
            ),
            view=view
        )


# ── -myembeds Select ──────────────────────────────────────────
class MyEmbedsSelect(discord.ui.Select):
    def __init__(self, owner_id: int, rows):
        self.owner_id = owner_id
        options = []
        for r in rows[:25]:
            eid, title, desc, *_ = r
            label   = (title or "Untitled embed")[:100]
            preview = (desc  or "")[:50]
            options.append(discord.SelectOption(
                label       = label,
                description = (preview + "…") if len(desc or "") > 50 else (preview or "No description"),
                value       = str(eid),
            ))
        super().__init__(placeholder="📋 Pick an embed to preview…", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Not your menu.", ephemeral=True)
        embed_id = int(self.values[0])
        row = _em_get(embed_id)
        if not row:
            return await interaction.response.send_message("❌ Embed not found.", ephemeral=True)
        embed = _em_build(row)
        embed.set_author(name=f"Embed #{embed_id}")
        await interaction.response.send_message(
            embed=embed, view=EmbedActionView(embed_id, self.owner_id)
        )

class MyEmbedsView(discord.ui.View):
    def __init__(self, owner_id: int, rows):
        super().__init__(timeout=120)
        self.add_item(MyEmbedsSelect(owner_id, rows))


# ── -categorychannels selector ────────────────────────────────
class CategoryChannelsSelect(discord.ui.Select):
    def __init__(self, owner_id: int, categories, page: int, page_size: int = 25):
        self.owner_id = owner_id
        self.categories = categories
        self.page = page
        self.page_size = page_size

        start = page * page_size
        page_categories = categories[start:start + page_size]
        options = [
            discord.SelectOption(
                label=category.name[:100],
                description=f"{len(category.channels)} channel(s) • ID {category.id}"[:100],
                value=str(category.id),
            )
            for category in page_categories
        ]

        super().__init__(
            placeholder="📁 Choose a category…",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message(
                "❌ This category menu belongs to the administrator who used the command.",
                ephemeral=True,
            )

        category_id = int(self.values[0])
        category = interaction.guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.edit_message(
                content="❌ That category no longer exists.",
                view=None,
            )

        channels = list(category.channels)
        header = (
            f"📁 **{category.name}**\n"
            f"Category ID: `{category.id}`\n"
            f"Channels: **{len(channels)}**\n\n"
        )

        if not channels:
            return await interaction.response.edit_message(
                content=header + "No channels are in this category.",
                view=None,
            )

        lines = [
            f"• `{channel.name}` — `{channel.id}` "
            f"({str(channel.type).replace('ChannelType.', '').replace('_', ' ').title()})"
            for channel in channels
        ]

        # Discord message content is limited to 2,000 characters. Keep each
        # follow-up within the limit while preserving the complete channel list.
        chunks = []
        current = header
        for line in lines:
            if len(current) + len(line) + 1 > 1900:
                chunks.append(current)
                current = ""
            current += line + "\n"
        if current:
            chunks.append(current)

        await interaction.response.edit_message(content=chunks[0], view=None)
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)


class CategoryChannelsView(discord.ui.View):
    def __init__(self, owner_id: int, categories, page: int = 0):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.categories = categories
        self.page = page
        self.page_size = 25
        self.max_page = max(0, (len(categories) - 1) // self.page_size)
        self.add_item(CategoryChannelsSelect(owner_id, categories, page, self.page_size))

        previous = discord.ui.Button(
            label="Previous",
            emoji="◀️",
            style=discord.ButtonStyle.secondary,
            disabled=page == 0,
        )
        next_button = discord.ui.Button(
            label="Next",
            emoji="▶️",
            style=discord.ButtonStyle.secondary,
            disabled=page >= self.max_page,
        )
        previous.callback = self.previous_callback
        next_button.callback = self.next_callback
        self.add_item(previous)
        self.add_item(next_button)

    async def _change_page(self, interaction: discord.Interaction, page: int):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message(
                "❌ This category menu belongs to the administrator who used the command.",
                ephemeral=True,
            )

        view = CategoryChannelsView(self.owner_id, self.categories, page)
        total_pages = self.max_page + 1
        await interaction.response.edit_message(
            content=(
                "📁 **Choose a category**\n"
                f"Page **{page + 1}/{total_pages}** "
                f"({len(self.categories)} categories available)"
            ),
            view=view,
        )

    async def previous_callback(self, interaction: discord.Interaction):
        await self._change_page(interaction, max(0, self.page - 1))

    async def next_callback(self, interaction: discord.Interaction):
        await self._change_page(interaction, min(self.max_page, self.page + 1))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


@bot.command(name="categorychannels", help="[ADMIN] Choose a category and list all channels in it")
@commands.has_permissions(administrator=True)
async def categorychannels_command(ctx):
    """Show a category selector, then list every channel in the selected category."""
    categories = sorted(ctx.guild.categories, key=lambda category: category.position)
    if not categories:
        return await ctx.send("❌ This server has no categories.")

    view = CategoryChannelsView(ctx.author.id, categories)
    total_pages = view.max_page + 1
    await ctx.send(
        "📁 **Choose a category**\n"
        f"Page **1/{total_pages}** ({len(categories)} categories available)",
        view=view,
    )


@bot.command(
    name="giverolemention",
    help="[ADMIN] Allow a role to use @everyone/@here in every server channel",
)
@commands.has_permissions(administrator=True)
async def give_role_mention_command(ctx, role_id: str):
    """Allow the specified role to mention everyone in every channel."""
    if ctx.guild is None:
        return await ctx.send("❌ This command can only be used in a server.")

    try:
        role = ctx.guild.get_role(int(role_id.strip()))
    except (TypeError, ValueError):
        role = None

    if role is None:
        return await ctx.send(
            "❌ Role not found. Use the role's numeric ID, for example: "
            "`-giverolemention 123456789012345678`"
        )

    updated = 0
    failed = []
    for channel in ctx.guild.channels:
        try:
            # Start with the existing overwrite so every unrelated permission
            # remains unchanged; only enable Mention Everyone.
            overwrite = channel.overwrites_for(role)
            overwrite.mention_everyone = True
            await channel.set_permissions(
                role,
                overwrite=overwrite,
                reason=f"{ctx.author} granted Mention Everyone via -giverolemention",
            )
            updated += 1
        except (discord.Forbidden, discord.HTTPException) as error:
            failed.append(f"{channel.name} ({type(error).__name__})")

    result = (
        f"✅ **{role.name}** can now use `@everyone` and `@here` in "
        f"**{updated}** channel(s)."
    )
    if failed:
        result += (
            f"\n⚠️ Could not update **{len(failed)}** channel(s): "
            + ", ".join(failed[:10])
        )
        if len(failed) > 10:
            result += f" and {len(failed) - 10} more."
    await ctx.send(result)


# ── Commands ──────────────────────────────────────────────────
@bot.command(name="convertembed")
async def convertembed_command(ctx):
    """Reply to any message to convert it into a stored embed."""
    if ctx.author.id != _EMBED_OWNER_ID:
        return

    if not ctx.message.reference:
        return await ctx.send("❌ **Reply** to a message to convert it into an embed.")

    try:
        ref = await ctx.channel.fetch_message(ctx.message.reference.message_id)
    except Exception:
        return await ctx.send("❌ Could not fetch the referenced message.")

    # Pull content from the referenced message
    description = ref.content or ""
    image_url   = ""
    title       = ""
    footer      = ""

    # Image from attachments
    for att in ref.attachments:
        if att.content_type and att.content_type.startswith("image/"):
            image_url = att.url
            break

    # If the message itself had embeds, prefer those fields
    if ref.embeds:
        first = ref.embeds[0]
        if first.title:                      title       = first.title
        if first.description:                description = first.description
        if first.footer and first.footer.text: footer    = first.footer.text
        # Image from embed if not already found in attachments
        if not image_url:
            if first.image and first.image.url:
                image_url = first.image.url
            elif first.thumbnail and first.thumbnail.url:
                image_url = first.thumbnail.url

    color = 0x58B9FF
    eid   = _em_save(ctx.author.id, title, description, image_url, color, footer)

    preview = _em_build((eid, title, description, image_url, color, footer))
    preview.set_author(name=f"✅ Saved as Embed #{eid}  •  use -myembeds to find it later")
    await ctx.send(embed=preview, view=EmbedActionView(eid, ctx.author.id))


@bot.command(name="myembeds")
async def myembeds_command(ctx):
    """View, modify, and send your saved embeds."""
    if ctx.author.id != _EMBED_OWNER_ID:
        return

    rows = _em_list(ctx.author.id)
    if not rows:
        return await ctx.send(
            "📭 No saved embeds yet. Use **-convertembed** by replying to any message."
        )

    list_embed = discord.Embed(
        title       = "📋 Your Saved Embeds",
        description = f"**{len(rows)}** embed(s). Pick one from the dropdown to preview it.",
        color       = 0x58B9FF,
    )
    for r in rows[:10]:
        eid, title, desc, img, color, footer, created = r
        snippet = (desc[:80] + "…") if desc and len(desc) > 80 else (desc or "*(no description)*")
        list_embed.add_field(
            name  = f"#{eid} — {title or 'Untitled'}",
            value = snippet,
            inline= False,
        )
    if len(rows) > 10:
        list_embed.set_footer(text=f"Showing first 10 of {len(rows)}. All {len(rows)} are in the dropdown.")

    await ctx.send(embed=list_embed, view=MyEmbedsView(ctx.author.id, rows))


# ══════════════════════════════════════════════════════════════

_DMALLROLE_OWNER_ID = 765965975761715241

@bot.command(name="doublesync", help="[OWNER ONLY] Remove unclaimed role from members who have a specific role")
async def doublesync_command(ctx):
    """Remove unclaimed role (1461764869282857010) from members who also have role 1530242270186704997. Only usable by user 765965975761715241."""
    if ctx.author.id != _DMALLROLE_OWNER_ID:
        return

    unclaimed_role = ctx.guild.get_role(1461764869282857010)
    target_role = ctx.guild.get_role(1530242270186704997)

    if not unclaimed_role:
        await ctx.send("❌ Unclaimed role (1461764869282857010) not found!")
        return
    if not target_role:
        await ctx.send("❌ Target role (1530242270186704997) not found!")
        return

    await ctx.send(f"🔄 Removing unclaimed role from members who have **{target_role.name}**...")

    removed_count = 0
    skipped_count = 0
    failed_list = []

    for member in target_role.members:
        if unclaimed_role not in member.roles:
            skipped_count += 1
            continue
        try:
            await member.remove_roles(unclaimed_role, reason=f"doublesync by {ctx.author}")
            removed_count += 1
        except discord.Forbidden:
            failed_list.append(f"{member.name} - No permission")
        except discord.HTTPException:
            failed_list.append(f"{member.name} - HTTP error")

    embed = discord.Embed(
        title="✅ Double Sync Complete",
        color=unclaimed_role.color or 0x5865F2
    )
    embed.description = (
        f"**Target Role:** {target_role.mention}\n"
        f"**Unclaimed Role:** {unclaimed_role.mention}\n\n"
        f"🗑️ **Removed:** {removed_count}\n"
        f"ℹ️ **Didn't have unclaimed role:** {skipped_count}\n"
        f"❌ **Failed:** {len(failed_list)}"
    )
    if failed_list:
        failures = "\n".join([f"• {f}" for f in failed_list[:10]])
        if len(failed_list) > 10:
            failures += f"\n...and {len(failed_list) - 10} more."
        embed.add_field(name="Failed", value=failures, inline=False)
    embed.set_footer(text=f"Executed by {ctx.author.name}")
    embed.timestamp = discord.utils.utcnow()

    await ctx.send(embed=embed)

@bot.command(name="dmallrole", help="[OWNER ONLY] DM all users with a given role")
async def dmallrole_command(ctx, role_id: int, *, message: str):
    """DM all members with the specified role. Only usable by user 765965975761715241."""
    if ctx.author.id != _DMALLROLE_OWNER_ID:
        return  # Silently ignore unauthorized users

    role = ctx.guild.get_role(role_id)
    if not role:
        await ctx.send(f"❌ Role with ID `{role_id}` not found.")
        return

    await ctx.send(f"📨 Sending DMs to all members with **{role.name}**...")

    sent_count = 0
    failed_count = 0
    failed_list = []

    for member in role.members:
        if member.bot:
            continue
        try:
            await member.send(message)
            sent_count += 1
        except discord.Forbidden:
            failed_count += 1
            failed_list.append(f"{member.name} - DMs closed")
        except discord.HTTPException:
            failed_count += 1
            failed_list.append(f"{member.name} - HTTP error")

    embed = discord.Embed(
        title="📨 DM Blast Complete",
        color=role.color or 0x5865F2
    )
    embed.description = (
        f"**Role:** {role.mention}\n\n"
        f"✅ **Sent:** {sent_count}\n"
        f"❌ **Failed:** {failed_count}"
    )
    if failed_list:
        failures = "\n".join([f"• {f}" for f in failed_list[:10]])
        if len(failed_list) > 10:
            failures += f"\n...and {len(failed_list) - 10} more."
        embed.add_field(name="Failed", value=failures, inline=False)
    embed.set_footer(text=f"Executed by {ctx.author.name}")
    embed.timestamp = discord.utils.utcnow()

    await ctx.send(embed=embed)

# ══════════════════════════════════════════════════════════════
token = os.getenv('TOKEN')
if token:
    keep_alive()
    bot.run(token)