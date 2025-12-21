import discord, os, json, random, sqlite3, pickle
from discord.ui import Select, View
import asyncio
import time
import aiohttp
from typing import Dict, Optional
from discord.ext import commands, tasks
from keep_alive import keep_alive
from discord.ext.commands.cooldowns import BucketType
keep_alive()
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
mydb = sqlite3.connect("players.db")
crsr = mydb.cursor()
mydb.commit()

bot = commands.Bot(
    command_prefix=".",
    description="TFHEx - All For TFH",
    intents=intents,
    case_insensitive=True,
    strip_after_prefix=True,
    help_command=None  # Disable default help to use custom
)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

@bot.event
async def on_ready():
    init_db()
    # Load the stats cog
    await bot.load_extension('cricket_stats')
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is ready! Prefix: .')

@bot.listen()
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    await ctx.send(f"❌ Error: {error}")

# Database setup
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
    conn.commit()
    conn.close()

# Load players from JSON
def load_players():
    try:
        with open('players.json', 'r', encoding='utf-8') as f:
            return json.load(f)
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
        "USA": 0x080026
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
        "West Indies": "1f3f4",  # 🏴
        "Sri Lanka": "1f1f1-1f1f0",  # 🇱🇰
        "Bangladesh": "1f1e7-1f1e9",  # 🇧🇩
        "Afghanistan": "1f1e6-1f1eb",  # 🇦🇫
        "Netherlands": "1f1f3-1f1f1",  # 🇳🇱
        "Scotland": "1f3f4-e0067-e0062-e0073-e0063-e0074-e007f",  # 🏴󠁧󠁢󠁳󠁣󠁴󠁿
        "Ireland": "1f1ee-1f1ea",  # 🇮🇪
        "Zimbabwe": "1f1ff-1f1fc",  # 🇿🇼
        "UAE": "1f1e6-1f1ea",  # 🇦🇪
        "Canada": "1f1e8-1f1e6",  # 🇨🇦
        "USA": "1f1fa-1f1f8"  # 🇺🇸
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
        "USA": "🇺🇸"
    }
    return flags.get(team_name, "🏳️")

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
@commands.has_permissions(administrator=True)
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
            f"⚠️ {player['name']} is already represented by @{existing[0]}. Use `.unclaim` first to remove them."
        )
        conn.close()
        return

    # Add representative
    c.execute("INSERT INTO player_representatives VALUES (?, ?, ?)",
              (player['name'], user.id, user.name))
    conn.commit()
    conn.close()

    await ctx.send(
        f"✅ {user.mention} is now representing **{player['name']}** from {team_name}!"
    )

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

@bot.command(name="unclaim", aliases=["uc"], help="[ADMIN] Remove a player's representative")
@commands.has_permissions(administrator=True)
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
    conn.commit()
    conn.close()

    await ctx.send(
        f"✅ Removed @{existing[0]} as the representative of **{player['name']}**."
    )

@bot.command(name="myclaim", aliases=["mc"], help="View the player you represent")
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
            description += f"**{idx}.** {flag} **{player['name']}** {role_emoji}\n"
            description += f"    └ *{player['team']}* • {player['representative']}\n\n"

        embed.description = description
        embed.set_footer(text=f"Page {len(pages)+1}/{(len(all_players)-1)//players_per_page + 1} • Total Players: {len(all_players)}")
        pages.append(embed)

    if len(pages) == 1:
        await ctx.send(embed=pages[0])
    else:
        view = PlayerListView(pages, ctx)
        view.message = await ctx.send(embed=pages[0], view=view)

@bot.command(name="viewteam", aliases=["vt"], help="View all players in a specific team")
async def viewteam_command(ctx, *, team_name: str):
    teams_data = load_players()

    if not teams_data:
        await ctx.send("❌ No player data available.")
        return

    # Find the team
    team_data = None
    for t in teams_data:
        if t['team'].lower() == team_name.lower():
            team_data = t
            break

    if not team_data:
        available_teams = ", ".join([t['team'] for t in teams_data])
        await ctx.send(f"❌ Team '{team_name}' not found.\n\n**Available teams:** {available_teams}")
        return

    flag = get_team_flag(team_data['team'])
    flag_url = get_team_flag_url(team_data['team'])

    embed = discord.Embed(
        title=f"{flag} Official {team_data['team']} Squad",
        color=get_team_color(team_data['team'])
    )

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
        rep_text = f" • **@{rep_info[1]}**" if rep_info else " • *Unclaimed*"

        player_line = f"• {player['name']}{rep_text}"

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

    embed.set_footer(text=f"Total Players: {total_players} • Claimed: {claimed} • Unclaimed: {total_players - claimed}")

    await ctx.send(embed=embed)

@bot.command(name="help", aliases=["h", "commands"], help="Show all available commands")
async def help_command(ctx):
    embed = discord.Embed(
        title="TFHEx - Commands",
        description="Manage and view cricket player information",
        color=0x0066CC
    )

    embed.add_field(
        name="📋 General Commands",
        value=(
            "`.view <name>` or `.v <name>`\n"
            "└ Search and view a cricket player\n"
            "└ Example: `.view Virat Kohli` or `.v kohli`\n\n"
            "`.myclaim` or `.mc`\n"
            "└ View the player you represent\n\n"
            "`.stats [@user]` or `.s [@user]`\n"
            "└ View your or another user's statistics\n"
            "└ Example: `.stats` or `.stats @john`\n\n"
            "`.leaderboard` or `.lb`\n"
            "└ View tournament leaderboards\n\n"
            "`.playerlist` or `.pl`\n"
            "└ View all players in a paginated list\n\n"
            "`.viewteam <team_name>` or `.vt <team_name>`\n"
            "└ View all players in a specific team\n"
            "└ Example: `.viewteam Pakistan`"
        ),
        inline=False
    )

    embed.add_field(
        name="👑 Admin Commands",
        value=(
            "`.claim @user <player_name>` or `.c @user <player_name>`\n"
            "└ Assign a player to a Discord user\n"
            "└ Example: `.claim @john Virat Kohli`\n\n"
            "`.unclaim <player_name>` or `.uc <player_name>`\n"
            "└ Remove a player's representative\n"
            "└ Example: `.unclaim Virat Kohli`\n\n"
            "`.addstats` or `.as`\n"
            "└ Reply to a bot message with raw stats to add them\n"
            "└ Example: Reply to stats message with `.addstats`"
        ),
        inline=False
    )

    embed.add_field(
        name="ℹ️ Info",
        value=(
            "• All player names are case-insensitive\n"
            "• Admin commands require Administrator permission\n"
            "• Use `.help` or `.h` to view this message again"
        ),
        inline=False
    )

    embed.set_footer(text="TourneyFanHub")

    await ctx.send(embed=embed)

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

        # Create options for team selection
        options = []
        for team_data in teams_data[:25]:  # Discord limit is 25 options
            flag = get_team_flag(team_data['team'])
            options.append(
                discord.SelectOption(
                    label=team_data['team'],
                    description=f"View {team_data['team']} players",
                    emoji=flag
                )
            )

        select = Select(
            placeholder="🏏 Select Your Nation",
            options=options,
            custom_id="team_select"
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
                f"Use `.unrepresent` to remove your current player before claiming another.",
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

        # Send approval request to admin channel
        approval_channel = interaction.client.get_channel(1452272794560757810)

        if approval_channel:
            flag = get_team_flag(team_name)
            role_emoji = get_role_emoji(player['role'])

            approval_embed = discord.Embed(
                title="🎯 New Player Representation Request",
                description=f"{interaction.user.mention} wants to represent **{player['name']}**",
                color=get_team_color(team_name)
            )

            approval_embed.add_field(
                name=f"{flag} Player Info",
                value=f"**{player['name']}**\n{role_emoji} {player['role']}\n*{team_name}*",
                inline=True
            )

            approval_embed.add_field(
                name="👤 Requesting User",
                value=f"{interaction.user.mention}\n{interaction.user.name}",
                inline=True
            )

            approval_embed.set_thumbnail(url=player['image'])
            approval_embed.set_footer(text=f"User ID: {interaction.user.id} | Player: {player['name']}")
            approval_embed.timestamp = discord.utils.utcnow()

            # Create approval view with buttons
            approval_view = ApprovalView(interaction.user, player['name'], team_name, player)
            approval_msg = await approval_channel.send(
                content="@here **New Representation Request**",
                embed=approval_embed,
                view=approval_view
            )
            approval_view.message = approval_msg

            await interaction.response.send_message(
                f"✅ Your request to represent **{player['name']}** has been submitted!\n"
                f"You'll receive a DM once an admin reviews your request.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ Error: Approval channel not found!",
                ephemeral=True
            )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True

# Approval View for Admins
class ApprovalView(View):
    def __init__(self, user, player_name, team_name, player_data):
        super().__init__(timeout=None)
        self.user = user
        self.player_name = player_name
        self.team_name = team_name
        self.player_data = player_data
        self.message = None

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success)
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only administrators can approve requests!",
                ephemeral=True
            )
            return

        # Check if player is still unclaimed
        rep_info = get_representative(self.player_name)
        if rep_info:
            await interaction.response.send_message(
                f"❌ This player is already claimed by @{rep_info[1]}!",
                ephemeral=True
            )
            return

        # Check if user still doesn't have a player
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", 
                  (self.user.id,))
        existing = c.fetchone()

        if existing:
            await interaction.response.send_message(
                f"❌ {self.user.mention} already represents **{existing[0]}**!",
                ephemeral=True
            )
            conn.close()
            return

        # Add the claim
        c.execute("INSERT INTO player_representatives VALUES (?, ?, ?)",
                  (self.player_name, self.user.id, self.user.name))
        conn.commit()
        conn.close()

        # Update the approval message
        approved_embed = discord.Embed(
            title="✅ Request Approved",
            description=f"{self.user.mention} now represents **{self.player_name}**",
            color=0x00FF00
        )
        approved_embed.add_field(
            name="Approved By",
            value=interaction.user.mention,
            inline=True
        )
        approved_embed.timestamp = discord.utils.utcnow()

        # Disable buttons
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=approved_embed, view=self)

        # DM the user
        try:
            dm_embed = discord.Embed(
                title="🎉 Representation Request Approved!",
                description=f"Your request to represent **{self.player_name}** has been approved!",
                color=get_team_color(self.team_name)
            )

            flag = get_team_flag(self.team_name)
            role_emoji = get_role_emoji(self.player_data['role'])

            dm_embed.add_field(
                name=f"{flag} Your Player",
                value=f"**{self.player_name}**\n{role_emoji} {self.player_data['role']}\n*{self.team_name}*",
                inline=False
            )

            dm_embed.set_thumbnail(url=self.player_data['image'])
            dm_embed.set_footer(text="Use .myclaim to view your player anytime!")

            await self.user.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        # Send to claims channel
        claims_channel = interaction.client.get_channel(1452037538792476682)
        if claims_channel:
            claim_embed = discord.Embed(
                title="🎉 Player Update!",
                description=f"{self.user.mention} Officially Represents **{self.player_name}**",
                color=get_team_color(self.team_name)
            )

            flag = get_team_flag(self.team_name)
            role_emoji = get_role_emoji(self.player_data['role'])

            claim_embed.set_author(
                icon_url=player['image']
            )

            claim_embed.add_field(
                name=f"{flag} Player Info",
                value=f"**{self.player_name}**\n{role_emoji} {self.player_data['role']}",
                inline=True
            )

            claim_embed.add_field(
                name="👤 Representative",
                value=f"{self.user.mention}",
                inline=True
            )

            claim_embed.set_thumbnail(url=self.user.avatar.url if self.user.avatar else None)
            claim_embed.set_image(url=self.player_data['image'])
            claim_embed.set_footer(text=f"TFH Nations")
            claim_embed.timestamp = discord.utils.utcnow()

            await claims_channel.send(embed=claim_embed)

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger)
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only administrators can deny requests!",
                ephemeral=True
            )
            return

        # Update the approval message
        denied_embed = discord.Embed(
            title="❌ Request Denied",
            description=f"Request from {self.user.mention} for **{self.player_name}** was denied",
            color=0xFF0000
        )
        denied_embed.add_field(
            name="Denied By",
            value=interaction.user.mention,
            inline=True
        )
        denied_embed.timestamp = discord.utils.utcnow()

        # Disable buttons
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=denied_embed, view=self)

        # DM the user
        try:
            dm_embed = discord.Embed(
                title="❌ Representation Request Denied",
                description=f"Your request to represent **{self.player_name}** has been denied by the admins.",
                color=0xFF0000
            )
            dm_embed.set_footer(text="You can try requesting a different player with .represent")

            await self.user.send(embed=dm_embed)
        except discord.Forbidden:
            pass

# Main represent command
@bot.command(name="represent", aliases=["rep"], help="Request to represent a cricket player")
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
            f"Use `.unrepresent` to remove your current player before claiming another."
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
@bot.command(name="unrepresent", aliases=["unrep"], help="Remove yourself as a player representative")
async def unrepresent_command(ctx):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Check if user represents a player
    c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", 
              (ctx.author.id,))
    result = c.fetchone()

    if not result:
        await ctx.send("❌ You don't represent any player!")
        conn.close()
        return

    player_name = result[0]

    # Remove the representation
    c.execute("DELETE FROM player_representatives WHERE user_id = ?", (ctx.author.id,))
    conn.commit()
    conn.close()

    await ctx.send(
        f"✅ You are no longer representing **{player_name}**.\n"
        f"You can use `.represent` to claim a new player."
    )


token = os.getenv('TOKEN')
if token:
    bot.run(token)