import discord
import os
import json
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
from discord.ui import Select, View
from discord.ext import commands, tasks
from discord.ext.commands.cooldowns import BucketType
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True  # Required for voice
intents.guilds = True  # Required for voice
mydb = sqlite3.connect("players.db")
crsr = mydb.cursor()
mydb.commit()

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


@bot.event
async def on_ready():
    global elite_players
    init_db()
    init_fantasy_db()  # ADD THIS LINE
    init_nicknames_db()  # ADD THIS LINE
    elite_players = load_elite_players()
    # Load the stats cog
    await bot.load_extension('cricket_stats')
    await bot.load_extension('matchupdates')
    await bot.load_extension('tournament')
    await bot.tree.sync()
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is ready! Prefix: .')

class PlayerSelectionView(discord.ui.View):
    def __init__(self, india_players, nz_players):
        super().__init__(timeout=300)
        self.selected_players = []
        self.india_players = india_players
        self.nz_players = nz_players
        self.selection_complete = False
        
        all_players = india_players + nz_players
        
        options1 = []
        for player in all_players[:25]:
            rep = get_representative(player)
            desc = f"{'🇮🇳 India' if player in india_players else '🇳🇿 NZ'}"
            if rep:
                desc += f" (Claimed by @{rep[1]})"
            else:
                desc += " (Unclaimed)"
            options1.append(discord.SelectOption(
                label=player[:100],
                value=player,
                description=desc[:100]
            ))

        # Create a single select with up to 11 selections
        select = discord.ui.Select(
            placeholder="Select up to 11 players",
            min_values=1,
            max_values=11,
            options=options1
        )
        select.callback = self.player_select_callback
        self.add_item(select)
        
        # If more than 25 players, add another select
        if len(all_players) > 25:
            options2 = []
            for player in all_players[25:50]:
                rep = get_representative(player)
                desc = f"{'🇮🇳 India' if player in india_players else '🇳🇿 NZ'}"
                if rep:
                    desc += f" (Claimed by @{rep[1]})"
                else:
                    desc += " (Unclaimed)"
                options2.append(discord.SelectOption(
                    label=player[:100],
                    value=player,
                    description=desc[:100]
                ))
            select2 = discord.ui.Select(
                placeholder="More players (26-50)",
                min_values=0,
                max_values=11,
                options=options2
            )
            select2.callback = self.player_select_callback
            self.add_item(select2)
    
    async def player_select_callback(self, interaction: discord.Interaction):
        # We need to aggregate selections from all select menus in the view
        all_selected = []
        for child in self.children:
            if isinstance(child, discord.ui.Select):
                if child.values:
                    all_selected.extend(child.values)
        
        # Ensure uniqueness if they select from multiple menus
        self.selected_players = list(dict.fromkeys(all_selected))
        
        if len(self.selected_players) > 11:
            await interaction.response.send_message("❌ You can only select up to 11 players!", ephemeral=True)
            return

        # If they selected 11, we can auto-complete, but let's allow them to confirm manually if they want fewer
        # The create_fantasy11 logic checks for != 11, I should relax that too or keep it for the "exactly 11" if that's implied.
        # User said "only 11 players max", implying 1-11 is fine.
        
        content = f"**Selecting Fantasy 11** ({len(self.selected_players)}/11)\n\n" + \
                  "\n".join([f"{i+1}. {p}" for i, p in enumerate(self.selected_players)])
        
        if len(self.selected_players) == 11:
            content += "\n\n✅ **Max team size reached!** Proceed to confirm."
        else:
            content += f"\n\n⚠️ You can select up to {11 - len(self.selected_players)} more players."

        await interaction.response.edit_message(content=content, view=self)

    @discord.ui.button(label="Finish Selection", style=discord.ButtonStyle.primary, row=2)
    async def finish_selection(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_players:
            await interaction.response.send_message("❌ Please select at least one player!", ephemeral=True)
            return
        
        self.selection_complete = True
        self.stop()
        await interaction.response.edit_message(content=f"✅ **Selection Finished!** ({len(self.selected_players)} players)", view=None)


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

@bot.tree.command(name="createfantasy11", description="Create your Fantasy 11 from India & NZ players")
async def create_fantasy11(interaction: discord.Interaction):
    user_id = interaction.user.id
    
    existing_team, _ = get_fantasy_team(user_id)
    if existing_team:
        await interaction.response.send_message(
            "❌ You already have a Fantasy 11 team! You can only create one team.",
            ephemeral=True
        )
        return
    
    await interaction.response.defer(ephemeral=True)
    
    india_players, nz_players = get_india_nz_players()
    
    if not india_players or not nz_players:
        await interaction.followup.send("❌ Could not load player data.", ephemeral=True)
        return
    
    view = PlayerSelectionView(india_players, nz_players)
    
    await interaction.followup.send(
        "**🏏 Create Your Fantasy 11 Team**\n\n"
        "Select **up to 11 players** from India 🇮🇳 and New Zealand 🇳🇿.\n"
        "⚠️ You can only create ONE team and CANNOT edit it!\n\n"
        f"**Available:** {len(india_players)} India, {len(nz_players)} NZ players",
        view=view,
        ephemeral=True
    )
    
    await view.wait()
    
    if not view.selection_complete or not view.selected_players:
        await interaction.followup.send("❌ Team creation cancelled or incomplete.", ephemeral=True)
        return
    
    india_count = sum(1 for p in view.selected_players if p in india_players)
    nz_count = sum(1 for p in view.selected_players if p in nz_players)
    
    confirm_embed = discord.Embed(
        title="🏆 Confirm Your Fantasy Team",
        description="**⚠️ Once confirmed, you CANNOT edit or create a new team!**",
        color=0xFFD700
    )
    
    players_list = "\n".join([
        f"{i+1}. {'🇮🇳' if p in india_players else '🇳🇿'} {p}"
        for i, p in enumerate(view.selected_players)
    ])
    
    confirm_embed.add_field(name="Selected Players", value=players_list, inline=False)
    confirm_embed.add_field(
        name="Team Composition",
        value=f"🇮🇳 India: **{india_count}**\n🇳🇿 New Zealand: **{nz_count}**",
        inline=False
    )
    
    confirm_view = ConfirmationView()
    await interaction.followup.send(embed=confirm_embed, view=confirm_view, ephemeral=True)
    
    await confirm_view.wait()
    
    if not confirm_view.confirmed:
        await interaction.followup.send("❌ Team creation cancelled.", ephemeral=True)
        return
    
    team_data = {
        'players': view.selected_players,
        'india_count': india_count,
        'nz_count': nz_count
    }
    
    save_fantasy_team(user_id, team_data)
    
    await interaction.followup.send("✅ **Fantasy 11 created!** Check channel 1471951626058207292", ephemeral=True)
    
    # Post to channel
    fantasy_channel = bot.get_channel(1471951626058207292)
    
    if fantasy_channel:
        team_embed = discord.Embed(
            title=f"🏆 {interaction.user.name}'s Fantasy 11 Team",
            description=f"**Total Points:** 0\n\n🇮🇳 India: {india_count} | 🇳🇿 NZ: {nz_count}",
            color=0xFFD700
        )
        
        india_in_team = [p for p in view.selected_players if p in india_players]
        nz_in_team = [p for p in view.selected_players if p in nz_players]
        
        if india_in_team:
            team_embed.add_field(
                name="🇮🇳 India Players",
                value="\n".join([f"• {p}" for p in india_in_team]),
                inline=True
            )
        
        if nz_in_team:
            team_embed.add_field(
                name="🇳🇿 New Zealand Players",
                value="\n".join([f"• {p}" for p in nz_in_team]),
                inline=True
            )
        
        team_embed.set_thumbnail(url=interaction.user.display_avatar.url)
        team_embed.set_footer(text=f"Created by {interaction.user.name}")
        
        await fantasy_channel.send(embed=team_embed)

@bot.tree.command(name="sendmsg", description="Send a custom message in this channel")
@app_commands.describe(
    message="The message content to send",
    image="Optional image to attach"
)
@app_commands.checks.has_permissions(administrator=True)
async def sendmsg(interaction: discord.Interaction, message: str, image: Optional[discord.Attachment] = None):
    # Hide the slash command response (ephemeral)
    await interaction.response.send_message("✅ Message sent!", ephemeral=True)
    
    # Send the message separately in the same channel
    if image:
        file = await image.to_file()
        await interaction.channel.send(content=message, file=file)
    else:
        await interaction.channel.send(content=message)

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
    if isinstance(error, commands.CommandNotFound):
        return
    await ctx.send(f"❌ Error: {error}")


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
    # ADD THIS NEW TABLE FOR CAPTAINS
    c.execute('''CREATE TABLE IF NOT EXISTS team_captains
                 (team_name TEXT PRIMARY KEY, player_name TEXT, user_id INTEGER, username TEXT)''')
    conn.commit()
    conn.close()

def init_fantasy_db():
    """Initialize fantasy cricket database tables"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS fantasy_teams
                 (user_id INTEGER PRIMARY KEY,
                  team_data TEXT,
                  total_points INTEGER DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS fantasy_points_log
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  player_name TEXT,
                  match_id INTEGER,
                  points_earned INTEGER,
                  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
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

def get_india_nz_players():
    """Get all players from India and New Zealand teams"""
    try:
        with open('players.json', 'r', encoding='utf-8') as f:
            teams_data = json.load(f)
        
        india_players = []
        nz_players = []
        
        for team in teams_data:
            if team['team'] == 'India':
                india_players = [p['name'] for p in team['players']]
            elif team['team'] == 'New Zealand':
                nz_players = [p['name'] for p in team['players']]
        
        return india_players, nz_players
    except:
        return [], []

def get_fantasy_team(user_id):
    """Get user's fantasy team"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT team_data, total_points FROM fantasy_teams WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        return json.loads(result[0]), result[1]
    return None, 0

def save_fantasy_team(user_id, team_data):
    """Save user's fantasy team"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO fantasy_teams (user_id, team_data, total_points)
                 VALUES (?, ?, COALESCE((SELECT total_points FROM fantasy_teams WHERE user_id = ?), 0))""",
              (user_id, json.dumps(team_data), user_id))
    conn.commit()
    conn.close()

def update_fantasy_points(user_id, points_to_add):
    """Update fantasy team total points"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("UPDATE fantasy_teams SET total_points = total_points + ? WHERE user_id = ?",
              (points_to_add, user_id))
    conn.commit()
    conn.close()

def get_fantasy_leaderboard():
    """Get fantasy leaderboard data"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("""SELECT user_id, total_points, team_data 
                 FROM fantasy_teams 
                 ORDER BY total_points DESC""")
    results = c.fetchall()
    conn.close()
    return results

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
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO team_captains VALUES (?, ?, ?, ?)",
              (team_name, player_name, user_id, username))
    conn.commit()
    conn.close()

def remove_team_captain(team_name):
    """Remove captain from a team"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("DELETE FROM team_captains WHERE team_name = ?", (team_name,))
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
            f"⚠️ {player['name']} is already represented by @{existing[0]}. Use `-unclaim` first to remove them."
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

        # Create options for team selection
        options = []
        for team_data in teams_data[:25]:  # Discord limit is 25 options
            flag = get_team_flag(team_data['team'])

            # Check if all players are claimed
            total_players = len(team_data['players'])
            claimed_players = sum(1 for player in team_data['players'] if get_representative(player['name']))

            if claimed_players == total_players:
                description = f"(TEAM FULL) - All {total_players} players claimed"
            else:
                description = f"View {team_data['team']} players - {total_players - claimed_players} available"

            options.append(
                discord.SelectOption(
                    label=team_data['team'],
                    description=description,
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

            # Check if player is elite and use elite emoji instead
            if player['name'] in elite_players:
                elite_emoji = bot.get_emoji(1452949859412738110)
                if elite_emoji:
                    role_emoji = elite_emoji

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
                auction_channel = interaction.client.get_channel(1452950205715714120)
                channel_mention = auction_channel.mention if auction_channel else "<#1452950205715714120>"

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
@bot.command(name="represent", aliases=["rep"], help="Request to represent a cricket player")
@commands.has_permissions(administrator=True)
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
@bot.command(name="unrepresent", aliases=["unrep"], help="Remove yourself as a player representative")
@commands.has_permissions(administrator=True)
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
        f"You can use `-represent` to claim a new player."
    )

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

# Store emoji mappings {player_name: emoji_id}
player_emojis = {}

async def download_and_process_image(session, url, player_name):
    """Download player image and convert to emoji format (PNG, max 256KB)"""
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None

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
                # Reduce size if too large
                img = img.resize((64, 64), Image.Resampling.LANCZOS)
                output = BytesIO()
                img.save(output, format='PNG', optimize=True)
                output.seek(0)

            return output
    except Exception as e:
        print(f"❌ Error processing image for {player_name}: {e}")
        return None

async def upload_emojis_to_servers(bot):
    """Upload player emojis to all designated servers"""
    teams_data = load_players()

    # Collect all players
    all_players = []
    for team_data in teams_data:
        for player in team_data['players']:
            all_players.append({
                'name': player['name'],
                'image': player['image'],
                'team': team_data['team']
            })

    print(f"📊 Total players to process: {len(all_players)}")

    # Distribute players across servers (50 per server for regular, 25 for boosted servers)
    emojis_per_server = 50
    server_index = 0

    async with aiohttp.ClientSession() as session:
        for i in range(0, len(all_players), emojis_per_server):
            if server_index >= len(EMOJI_SERVERS):
                print("⚠️ Not enough servers to upload all emojis!")
                break

            server_id = EMOJI_SERVERS[server_index]
            guild = bot.get_guild(server_id)

            if not guild:
                print(f"❌ Cannot access server {server_id}")
                server_index += 1
                continue

            print(f"📤 Uploading to server: {guild.name} ({server_id})")

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
                        player['image'], 
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

    # Search for emoji across all emoji servers
    for guild_id in EMOJI_SERVERS:
        guild = bot.get_guild(guild_id)
        if guild:
            # Try to find emoji by name
            emoji_obj = discord.utils.get(guild.emojis, name=emoji_name)
            if emoji_obj:
                return str(emoji_obj)  # Returns <:emoji_name:emoji_id>

    # Fallback if emoji not found
    return "👤"

# Add command to trigger emoji upload
@bot.command(name="uploademojis", aliases=["ue"])
@commands.has_permissions(administrator=True)
async def upload_emojis_command(ctx):
    """[ADMIN] Upload player emojis to designated servers"""
    await ctx.send("🔄 Starting emoji upload process... This will take several minutes.")

    try:
        emojis = await upload_emojis_to_servers(bot)
        await ctx.send(f"✅ Emoji upload complete! {len(emojis)} players now have emojis.")
    except Exception as e:
        await ctx.send(f"❌ Error during upload: {e}")

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

    # Generate squad image
    squad_image = await create_squad_image(team_data['team'], team_data, ctx.guild)

    flag = get_team_flag(team_data['team'])
    flag_url = get_team_flag_url(team_data['team'])

    # Get team captain
    captain_name = get_team_captain(team_data['team'])

    embed = discord.Embed(
        title=f"{flag} Official {team_data['team']} Squad",
        color=get_team_color(team_data['team'])
    )

    # Set generated squad image as main embed image
    if squad_image:
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

        # Add (C) if this player is the captain
        captain_badge = " **(C)**" if player['name'] == captain_name else ""

        # Format: [emoji] · Player Name · Representative (C)
        player_line = f"{emoji} · {player['name']}{captain_badge} · {rep_text}"

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
@commands.has_permissions(administrator=True)
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
    for server_id in EMOJI_SERVERS:
        guild = bot.get_guild(server_id)
        if guild:
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
@commands.has_permissions(administrator=True)
async def test_emoji_command(ctx, *, player_name: str):
    """[ADMIN] Test emoji retrieval for a specific player"""
    emoji = get_player_emoji(player_name, bot)

    # Also check all servers
    found_emojis = []
    emoji_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in player_name)[:32]

    for guild_id in EMOJI_SERVERS:
        guild = bot.get_guild(guild_id)
        if guild:
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
@commands.has_permissions(administrator=True)
async def list_emojis_command(ctx, server_index: int = 0):
    """[ADMIN] List all emojis in a specific emoji server"""
    if server_index >= len(EMOJI_SERVERS):
        await ctx.send(f"❌ Server index must be between 0 and {len(EMOJI_SERVERS)-1}")
        return

    server_id = EMOJI_SERVERS[server_index]
    guild = bot.get_guild(server_id)

    if not guild:
        await ctx.send(f"❌ Cannot access server {server_id}")
        return

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
@commands.has_permissions(administrator=True)
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
    auction_channel = bot.get_channel(1452950205715714120)
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
@commands.has_permissions(administrator=True)
async def unelite_command(ctx, *, players: str):
    """
    Remove elite status from players
    Usage: -unelite player1, player2, player3
    """
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
@commands.has_permissions(administrator=True)
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

        # Iterate through all emoji servers
        for server_id in EMOJI_SERVERS:
            guild = bot.get_guild(server_id)

            if not guild:
                print(f"❌ Cannot access server {server_id}")
                continue

            print(f"🗑️ Removing emojis from: {guild.name} ({server_id})")

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
@commands.has_permissions(administrator=True)
async def sync_left_command(ctx):
    await ctx.send("🔄 Checking for representatives who left the server...")
    
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    
    # Fetch all current claims
    c.execute("SELECT player_name, user_id FROM player_representatives")
    all_claims = c.fetchall()
    
    removed_count = 0
    removed_list = []
    
    for player_name, user_id in all_claims:
        # ctx.guild.get_member relies on the member cache (requires intents.members = True)
        member = ctx.guild.get_member(user_id)
        
        # If member is None, they are likely not in the server anymore
        if member is None:
            # Remove from representatives
            c.execute("DELETE FROM player_representatives WHERE player_name = ?", (player_name,))
            
            # Remove from captains if they were one
            c.execute("DELETE FROM team_captains WHERE player_name = ?", (player_name,))
            
            removed_list.append(player_name)
            removed_count += 1
    
    conn.commit()
    conn.close()
    
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
@commands.has_permissions(administrator=True)
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

    # Get player info from database
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name, user_id FROM player_representatives WHERE username = ?", (username,))
    result = c.fetchone()
    conn.close()

    if not result:
        await ctx.send(f"❌ No player representative found with username `{username}`.\nMake sure they have claimed a player first.")
        return

    player_name, user_id = result

    # Verify the player is from the specified team
    players, team_names = find_player(player_name)
    if not players or team_names[0] != team_data['team']:
        await ctx.send(f"❌ **{player_name}** (represented by @{username}) is not from **{team_data['team']}**!")
        return

    # Set as captain
    set_team_captain(team_data['team'], player_name, user_id, username)

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
@commands.has_permissions(administrator=True)
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

    embed = discord.Embed(
        title="👑 Team Captains",
        color=0xFFD700
    )

    has_captains = False

    for team_data in teams_data:
        captain_name = get_team_captain(team_data['team'])
        flag = get_team_flag(team_data['team'])

        if captain_name:
            rep_info = get_representative(captain_name)
            username = rep_info[1] if rep_info else "Unknown"
            embed.add_field(
                name=f"{flag} {team_data['team']}",
                value=f"**{captain_name}**\n@{username}",
                inline=True
            )
            has_captains = True
        else:
            embed.add_field(
                name=f"{flag} {team_data['team']}",
                value="*No captain set*",
                inline=True
            )

    if not has_captains:
        embed.description = "No captains have been assigned yet."

    await ctx.send(embed=embed)

@bot.command(name="fixcaptainstable", aliases=["fct"])
@commands.has_permissions(administrator=True)
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
@commands.has_permissions(administrator=True)
async def syncplayers_command(ctx):
    await ctx.send("🔄 Checking for representatives who left the server...")

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Fetch all current claims
    c.execute("SELECT player_name, user_id, username FROM player_representatives")
    all_claims = c.fetchall()

    removed_count = 0
    removed_list = []

    for player_name, user_id, username in all_claims:
        # Check if member is still in the server
        member = ctx.guild.get_member(user_id)

        # If member is None, they are not in the server anymore
        if member is None:
            # Remove from representatives
            c.execute("DELETE FROM player_representatives WHERE player_name = ?", (player_name,))

            # Remove from captains if they were one
            c.execute("DELETE FROM team_captains WHERE player_name = ?", (player_name,))

            removed_list.append(f"{player_name} (@{username})")
            removed_count += 1

    conn.commit()
    conn.close()

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
@commands.has_permissions(administrator=True)
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
    for guild_id in EMOJI_SERVERS:
        guild = bot.get_guild(guild_id)
        if guild:
            existing_emoji = discord.utils.get(guild.emojis, name=emoji_name)
            if existing_emoji:
                await ctx.send(f"✅ Emoji already exists: {existing_emoji} in {guild.name}")
                return

    # Find a server with available emoji slots
    target_guild = None
    for guild_id in EMOJI_SERVERS:
        guild = bot.get_guild(guild_id)
        if guild and len(guild.emojis) < guild.emoji_limit:
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

@bot.command(name="syncroles", aliases=["sr"], help="[ADMIN] Sync nationality roles for all claimed players")
@commands.has_permissions(administrator=True)
async def syncroles_command(ctx):
    await ctx.send("🔄 Syncing nationality roles for all claimed players...")

    # Get all team names for role checking
    teams_data = load_players()
    all_team_names = [team['team'] for team in teams_data]

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Fetch all current claims
    c.execute("SELECT player_name, user_id, username FROM player_representatives")
    all_claims = c.fetchall()

    conn.close()

    synced_count = 0
    failed_list = []
    already_had = 0
    roles_fixed = 0
    roles_fixed_list = []

    for player_name, user_id, username in all_claims:
        # Find the player's team
        players, team_names = find_player(player_name)

        if not players or not team_names:
            failed_list.append(f"{player_name} (@{username}) - Player data not found")
            continue

        correct_team = team_names[0]

        # Get the member
        member = ctx.guild.get_member(user_id)

        if not member:
            failed_list.append(f"{player_name} (@{username}) - Member not in server")
            continue

        # Find the correct role with the team name
        correct_role = discord.utils.find(lambda r: correct_team.lower() in r.name.lower(), ctx.guild.roles)

        if not correct_role:
            failed_list.append(f"{player_name} (@{username}) - Role for {correct_team} not found")
            continue

        # Find all nationality roles the member has
        member_nationality_roles = []
        for role in member.roles:
            for team_name in all_team_names:
                if team_name.lower() in role.name.lower():
                    member_nationality_roles.append((role, team_name))
                    break

        # Check if member has the correct role only
        has_correct_role_only = (
            len(member_nationality_roles) == 1 and 
            member_nationality_roles[0][1] == correct_team
        )

        if has_correct_role_only:
            already_had += 1
            continue

        # Member has wrong roles or multiple nationality roles - fix it
        try:
            # Remove all nationality roles
            for role, team_name in member_nationality_roles:
                await member.remove_roles(role, reason=f"Syncing roles - removing incorrect nationality")

            # Add correct role
            await member.add_roles(correct_role, reason=f"Synced nationality role for {player_name}")

            if len(member_nationality_roles) > 1 or (len(member_nationality_roles) == 1 and member_nationality_roles[0][1] != correct_team):
                roles_fixed += 1
                wrong_roles = ", ".join([team for _, team in member_nationality_roles])
                roles_fixed_list.append(f"{player_name} (@{username}) - Fixed from [{wrong_roles}] to {correct_team}")
            else:
                synced_count += 1

        except discord.Forbidden:
            failed_list.append(f"{player_name} (@{username}) - No permission to modify roles")
        except discord.HTTPException as e:
            failed_list.append(f"{player_name} (@{username}) - HTTP error: {e}")

    # Create summary embed
    embed = discord.Embed(
        title="🌍 Role Sync Complete",
        color=0x00FF00
    )

    summary = f"✅ **Roles Added:** {synced_count}\n"
    summary += f"🔧 **Roles Fixed (wrong/multiple):** {roles_fixed}\n"
    summary += f"ℹ️ **Already Correct:** {already_had}\n"
    summary += f"❌ **Failed:** {len(failed_list)}"

    embed.add_field(name="Summary", value=summary, inline=False)

    if roles_fixed_list:
        # Show first 10 fixed roles
        fixed = "\n".join([f"• {f}" for f in roles_fixed_list[:10]])
        if len(roles_fixed_list) > 10:
            fixed += f"\n...and {len(roles_fixed_list) - 10} more."

        embed.add_field(name="Fixed Roles", value=fixed, inline=False)

    if failed_list:
        # Show first 10 failures
        failures = "\n".join([f"• {f}" for f in failed_list[:10]])
        if len(failed_list) > 10:
            failures += f"\n...and {len(failed_list) - 10} more."

        embed.add_field(name="Failed", value=failures, inline=False)

    embed.set_footer(text=f"Synced by {ctx.author.name}")
    embed.timestamp = discord.utils.utcnow()

    await ctx.send(embed=embed)

@bot.command(name="playeremojiremove", aliases=["per"], help="[ADMIN] Remove emoji for a specific player")
@commands.has_permissions(administrator=True)
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

    # Search for emoji across all emoji servers
    emoji_found = False

    for guild_id in EMOJI_SERVERS:
        guild = bot.get_guild(guild_id)
        if guild:
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
@commands.has_permissions(administrator=True)
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
@commands.has_permissions(administrator=True)
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

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Get all user IDs who have claimed
    c.execute("SELECT user_id FROM player_representatives")
    claimed_user_ids = set(row[0] for row in c.fetchall())

    conn.close()

    added_count = 0
    already_had = 0
    failed_list = []

    # Iterate through all members with the player role
    for member in player_role.members:
        # Skip if they have claimed a player
        if member.id in claimed_user_ids:
            continue

        # Check if member already has the unclaimed role
        if unclaimed_role in member.roles:
            already_had += 1
            continue

        try:
            await member.add_roles(unclaimed_role, reason=f"Unclaimed player role by {ctx.author}")
            added_count += 1
        except discord.Forbidden:
            failed_list.append(f"{member.name} - No permission")
        except discord.HTTPException:
            failed_list.append(f"{member.name} - HTTP error")

    # Create summary embed
    embed = discord.Embed(
        title="✅ Unclaimed Role Assignment Complete",
        color=unclaimed_role.color
    )

    summary = f"**Player Role:** {player_role.mention}\n"
    summary += f"**Unclaimed Role:** {unclaimed_role.mention}\n\n"
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

@bot.command(name="rules", help="Display the game rules")
async def rules_command(ctx):
    """Display the game rules with well.png image"""

    embed = discord.Embed(
        title="📋 Rules",
        color=0x0066CC
    )

    # Format the rules nicely
    rules_text = (
        "`MAXIMUM BOWLING OVERS:`\n\n"
        "<:ball:1451974295793172547> **BOWLERS:** __4__ Full Overs\n"
        "<:allrounder:1451978476033671279> **ALL ROUNDERS:** __2__ Overs\n"
        "<:bat:1451967322146213980> **BATSMEN** / **WICKETKEEPERS:** __1__ Over\n\n"
        "*(Only ONE batsman / wicketkeeper allowed to bowl 2 overs)*\n\n"
        "**BATTING INNINGS ORDER:** `WICKETKEEPERS OR BATSMEN --> ALL-ROUNDERS --> BOWLERS`"
    )

    embed.description = rules_text

    # Set the image
    try:
        file = discord.File("well.png", filename="well.png")
        embed.set_image(url="attachment://well.png")
        await ctx.send(embed=embed, file=file)
    except FileNotFoundError:
        await ctx.send("❌ well.png file not found!")
    except Exception as e:
        await ctx.send(f"❌ Error loading image: {e}")

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
@commands.has_permissions(administrator=True)
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

class MatchTimeButtons(discord.ui.View):
    def __init__(self, requester_id, target_captain_id, requester_team_role_id, target_team_role_id, match_time, captain_id, channel):
        super().__init__(timeout=172800)  # 2 days in seconds
        self.requester_id = requester_id
        self.target_captain_id = target_captain_id
        self.requester_team_role_id = requester_team_role_id
        self.target_team_role_id = target_team_role_id
        self.match_time = match_time
        self.captain_id = captain_id
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

        # Send ping message first (separate from embed) as regular message
        await self.channel.send(
            content=f"{ping_text}**VS** at **{self.match_time}**"
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

        announce_embed.set_footer(text="Good luck to both teams!")

        await self.channel.send(embed=announce_embed)

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

@bot.tree.command(name="matchtime", description="Schedule a match time with another team")
@app_commands.describe(
    opponent="Select the opponent team",
    time="Select the match time"
)
@app_commands.choices(opponent=[
    app_commands.Choice(name="India", value="1460376137594044567"),
    app_commands.Choice(name="Pakistan", value="1460376138755866644"),
    app_commands.Choice(name="Australia", value="1460376139611640025"),
    app_commands.Choice(name="England", value="1460376141314654424"),
    app_commands.Choice(name="New Zealand", value="1460376142342000762"),
    app_commands.Choice(name="South Africa", value="1460376143633846527"),
    app_commands.Choice(name="West Indies", value="1460376148751028408"),
    app_commands.Choice(name="Sri Lanka", value="1460376147715166282"),
    app_commands.Choice(name="Bangladesh", value="1460376144862908523"),
    app_commands.Choice(name="Afghanistan", value="1460376146163273739"),
    app_commands.Choice(name="Netherlands", value="1460376154480312370"),
    app_commands.Choice(name="Scotland", value="1460376151795961897"),
    app_commands.Choice(name="Ireland", value="1460376149908525191"),
    app_commands.Choice(name="Zimbabwe", value="1460376157668245545"),
    app_commands.Choice(name="UAE", value="1460376158985130114"),
    app_commands.Choice(name="Canada", value="1460376154958725152"),
    app_commands.Choice(name="USA", value="1460376156250570824")
])
@app_commands.choices(time=[
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
    app_commands.Choice(name="9:30 PM IST", value="9:30PM IST")
])
async def matchtime(interaction: discord.Interaction, opponent: app_commands.Choice[str], time: app_commands.Choice[str]):
    # Check if user has the required role
    required_role = interaction.guild.get_role(1463220065657688285)
    if required_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You don't have permission to use this command!", ephemeral=True)
        return

    # Get user's team role
    role_ids = {
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
        "USA": 1460376156250570824
    }

    # Find requester's team
    requester_team_role = None
    requester_team_name = None
    for team_name, role_id in role_ids.items():
        role = interaction.guild.get_role(role_id)
        if role in interaction.user.roles:
            requester_team_role = role
            requester_team_name = team_name
            break

    if not requester_team_role:
        await interaction.response.send_message("❌ You don't have a team role!", ephemeral=True)
        return

    # Get opponent team role
    opponent_role = interaction.guild.get_role(int(opponent.value))
    if not opponent_role:
        await interaction.response.send_message("❌ Opponent team role not found!", ephemeral=True)
        return

    # Check if user is trying to challenge their own team
    if requester_team_role.id == opponent_role.id:
        await interaction.response.send_message("❌ You cannot challenge your own team!", ephemeral=True)
        return

    # Get opponent team captain
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT user_id, username FROM team_captains WHERE team_name = ?", (opponent.name,))
    captain_result = c.fetchone()
    conn.close()

    if not captain_result:
        await interaction.response.send_message(f"❌ {opponent.name} doesn't have a captain set yet!", ephemeral=True)
        return

    captain_id, captain_username = captain_result
    captain = interaction.guild.get_member(captain_id)

    if not captain:
        await interaction.response.send_message(f"❌ Captain of {opponent.name} is not in the server!", ephemeral=True)
        return

    # Build ping text for captain
    ping_text = f"<@{captain_id}>"

    # Send captain ping first as regular message (not reply)
    await interaction.channel.send(content=f"{ping_text} - Match Time Request")

    # Create request embed
    request_embed = discord.Embed(
        title="🏏 Match Time Request",
        description=f"The captain of **{requester_team_name}** wants to schedule a match!",
        color=0xFFA500
    )

    request_embed.add_field(
        name="Teams",
        value=f"{requester_team_role.mention} **VS** {opponent_role.mention}",
        inline=False
    )

    request_embed.add_field(
        name="Proposed Time",
        value=f"**{time.value}**",
        inline=False
    )

    request_embed.set_footer(text=f"Requested by {interaction.user.name}")

    # Create view with buttons
    view = MatchTimeButtons(
        requester_id=interaction.user.id,
        target_captain_id=captain_id,
        requester_team_role_id=requester_team_role.id,
        target_team_role_id=opponent_role.id,
        match_time=time.value,
        captain_id=captain_id,
        channel=interaction.channel
    )

    # Send embed as regular message (not reply) with buttons
    await interaction.channel.send(embed=request_embed, view=view)

    # Send ephemeral confirmation to the slash command user
    await interaction.response.send_message("✅ Match time request sent!", ephemeral=True)

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
@commands.has_permissions(administrator=True)
async def syncnicknames_command(ctx):
    """Sync nicknames for all claimed players"""
    loading_msg = await ctx.send("🔄 Syncing nicknames for all claimed players...")

    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name, user_id, username FROM player_representatives")
    all_claims = c.fetchall()
    conn.close()

    synced_count = 0
    failed_list = []
    skipped_count = 0

    for player_name, user_id, username in all_claims:
        # Try to fetch member from guild (forces cache update)
        try:
            member = await ctx.guild.fetch_member(user_id)
        except discord.NotFound:
            failed_list.append(f"{player_name} (@{username}) - Not in server")
            continue
        except discord.HTTPException:
            # Fallback to cache if fetch fails
            member = ctx.guild.get_member(user_id)
            if not member:
                failed_list.append(f"{player_name} (@{username}) - Not in server")
                continue

        # Save original nickname if not already saved
        current_nickname = member.display_name
        save_original_nickname(user_id, current_nickname)

        # Get custom nickname (if user hasn't set one, use their current display name)
        custom_nickname = get_user_custom_nickname(user_id)
        if not custom_nickname:
            custom_nickname = current_nickname
            update_custom_nickname(user_id, custom_nickname)

        # Format new nickname
        new_nickname = format_player_nickname(player_name, custom_nickname)

        # Skip if nickname is already correct
        if member.display_name == new_nickname:
            skipped_count += 1
            continue

        try:
            await member.edit(nick=new_nickname, reason=f"Nickname sync by {ctx.author}")
            synced_count += 1
        except discord.Forbidden:
            failed_list.append(f"{player_name} (@{username}) - No permission")
        except discord.HTTPException as e:
            failed_list.append(f"{player_name} (@{username}) - HTTP error: {e}")

    # Create summary embed
    embed = discord.Embed(
        title="✅ Nickname Sync Complete",
        color=0x00FF00
    )

    summary = f"✅ **Synced:** {synced_count}\n"
    summary += f"ℹ️ **Already Correct:** {skipped_count}\n"
    summary += f"❌ **Failed:** {len(failed_list)}"

    embed.add_field(name="Summary", value=summary, inline=False)

    if failed_list:
        failures = "\n".join([f"• {f}" for f in failed_list[:10]])
        if len(failed_list) > 10:
            failures += f"\n...and {len(failed_list) - 10} more."

        embed.add_field(name="Failed", value=failures, inline=False)

    embed.set_footer(text=f"Synced by {ctx.author.name}")
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
@commands.has_permissions(administrator=True)
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
@commands.has_permissions(administrator=True)
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
@commands.has_permissions(administrator=True)
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
@commands.has_permissions(administrator=True)
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
@commands.has_permissions(administrator=True)
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

    # 3. Remove from match_stats (using user_id)
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

    # 5. Remove from elite players
    if exact_player_name in elite_players:
        elite_players.remove(exact_player_name)
        save_elite_players()
        deletion_log.append(f"✅ Removed from elite players")

    # 6. Remove player emoji
    emoji_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in exact_player_name)[:32]
    emoji_removed = False

    for guild_id in EMOJI_SERVERS:
        guild = bot.get_guild(guild_id)
        if guild:
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
@app_commands.checks.has_permissions(administrator=True)
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

token = os.getenv('TOKEN')
if token:
    bot.run(token)