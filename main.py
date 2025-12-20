import discord, os, json, random, sqlite3, pickle
from discord.ui import Select, View
import asyncio
import time
import aiohttp
from typing import Dict, Optional
from discord.ext import commands, tasks
from keep_alive import keep_alive
from discord.ext.commands.cooldowns import BucketType
from discord import app_commands
keep_alive()
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
mydb = sqlite3.connect("players.db")
crsr = mydb.cursor()
mydb.commit()

bot = commands.Bot(
    command_prefix=".",
    description="Cricket Player Database Bot - View player info, search, and manage player representatives",
    intents=intents,
    case_insensitive=True,
    strip_after_prefix=True,
    help_command=commands.HelpCommand()
)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


@bot.listen()
async def on_command_error(ctx, error):
    await ctx.send(error)

# Database setup
def init_db():
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS player_representatives
                 (player_name TEXT PRIMARY KEY, user_id INTEGER, username TEXT)''')
    conn.commit()
    conn.close()

# Load players from JSON
def load_players():
    with open('players.json', 'r', encoding='utf-8') as f:
        return json.load(f)

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
        "Afghanistan": 0xFF0000,  # Red
    }
    return colors.get(team_name, 0x808080)  # Default gray

# Get team flag emoji
def get_team_flag(team_name):
    flags = {
        "India": "🇮🇳",
        "Pakistan": "🇵🇰",
        "Australia": "🇦🇺",
        "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
        "New Zealand": "🇳🇿",
        "South Africa": "🇿🇦",
        "West Indies": "🏴",
        "Sri Lanka": "🇱🇰",
        "Bangladesh": "🇧🇩",
        "Afghanistan": "🇦🇫",
    }
    return flags.get(team_name, "🏳️")

# Get role emoji
def get_role_emoji(role):
    if "Batsman" in role:
        return "<:bat:1451967322146213980>"
    elif "Bowler" in role:
        return "<:ball:1451974295793172547>"
    elif "All-Rounder" in role or "All-rounder" in role:
        return "<:allrounder:1451978476033671279>"
    return ""

# Find player by name
def find_player(player_name):
    teams_data = load_players()
    player_name_lower = player_name.lower()

    for team_data in teams_data:
        for player in team_data['players']:
            if player['name'].lower() == player_name_lower:
                return player, team_data['team']
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

@bot.tree.command(name="player", description="Search and view a cricket player")
@app_commands.describe(name="The name of the player to search for")
async def player_command(interaction: discord.Interaction, name: str):
    player, team_name = find_player(name)

    if not player:
        await interaction.response.send_message(
            f"❌ Player '{name}' not found. Please check the spelling and try again.",
            ephemeral=True
        )
        return

    embed = await create_player_embed(player, team_name, interaction.guild)

    # Check if we need to send default.jpg file
    rep_info = get_representative(player['name'])
    if not rep_info:
        try:
            file = discord.File("default.jpg", filename="default.jpg")
            await interaction.response.send_message(embed=embed, file=file)
        except FileNotFoundError:
            await interaction.response.send_message(embed=embed)
    else:
        member = interaction.guild.get_member(rep_info[0])
        if not member or not member.avatar:
            try:
                file = discord.File("default.jpg", filename="default.jpg")
                await interaction.response.send_message(embed=embed, file=file)
            except FileNotFoundError:
                await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

@bot.tree.command(name="claim", description="[ADMIN] Add a representative to a player")
@app_commands.describe(
    player_name="The name of the player",
    user="The Discord user who will represent this player"
)
@app_commands.default_permissions(administrator=True)
async def claim_command(interaction: discord.Interaction, player_name: str, user: discord.Member):
    player, team_name = find_player(player_name)

    if not player:
        await interaction.response.send_message(
            f"❌ Player '{player_name}' not found.",
            ephemeral=True
        )
        return

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Check if player is already claimed
    c.execute("SELECT username FROM player_representatives WHERE player_name = ?", 
              (player['name'],))
    existing = c.fetchone()

    if existing:
        await interaction.response.send_message(
            f"⚠️ {player['name']} is already represented by @{existing[0]}. Use `/unclaim` first to remove them.",
            ephemeral=True
        )
        conn.close()
        return

    # Add representative
    c.execute("INSERT INTO player_representatives VALUES (?, ?, ?)",
              (player['name'], user.id, user.name))
    conn.commit()
    conn.close()

    await interaction.response.send_message(
        f"✅ {user.mention} is now representing **{player['name']}** from {team_name}!",
        ephemeral=False
    )

@bot.tree.command(name="unclaim", description="[ADMIN] Remove a player's representative")
@app_commands.describe(player_name="The name of the player")
@app_commands.default_permissions(administrator=True)
async def unclaim_command(interaction: discord.Interaction, player_name: str):
    player, team_name = find_player(player_name)

    if not player:
        await interaction.response.send_message(
            f"❌ Player '{player_name}' not found.",
            ephemeral=True
        )
        return

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Check if player has a representative
    c.execute("SELECT username FROM player_representatives WHERE player_name = ?", 
              (player['name'],))
    existing = c.fetchone()

    if not existing:
        await interaction.response.send_message(
            f"⚠️ {player['name']} is not currently claimed by anyone.",
            ephemeral=True
        )
        conn.close()
        return

    # Remove representative
    c.execute("DELETE FROM player_representatives WHERE player_name = ?",
              (player['name'],))
    conn.commit()
    conn.close()

    await interaction.response.send_message(
        f"✅ Removed @{existing[0]} as the representative of **{player['name']}**.",
        ephemeral=False
    )

@bot.tree.command(name="myclaim", description="View the player you represent")
async def myclaim_command(interaction: discord.Interaction):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", 
              (interaction.user.id,))
    result = c.fetchone()
    conn.close()

    if not result:
        await interaction.response.send_message(
            "❌ You don't represent any player yet.",
            ephemeral=True
        )
        return

    player_name = result[0]
    player, team_name = find_player(player_name)

    if player:
        embed = await create_player_embed(player, team_name, interaction.guild)
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(
            f"⚠️ Error: Player data for {player_name} not found.",
            ephemeral=True
        )


token = os.getenv('TOKEN')
if token:
    bot.run(token)
