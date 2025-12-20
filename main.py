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
mydb = sqlite3.connect("user.db")
crsr = mydb.cursor()
mydb.commit()

bot = commands.Bot(
    command_prefix=".",
    description="",
    intents=intents,
    case_insensitive=True,
    strip_after_prefix=True,
    help_command=commands.MinimalHelpCommand()
)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


@bot.listen()
async def on_command_error(ctx, error):
    await ctx.send(error)

# API Configuration
API_KEY = 'd2d06e71-040b-4f16-b3f8-b36bc7d64b79'
BASE_URL = 'https://api.cricapi.com/v1'

# Player database
player_database: Dict[str, dict] = {}
is_loading = False
total_players = 0

async def fetch_all_players():
    """Fetch all cricket players from the API with pagination"""
    global player_database, is_loading, total_players

    try:
        is_loading = True
        print('Starting to fetch all cricket players...')

        offset = 0
        limit = 25  # API returns 25 players per request
        has_more = True
        fetched_count = 0

        async with aiohttp.ClientSession() as session:
            while has_more:
                try:
                    url = f"{BASE_URL}/players"
                    params = {
                        'apikey': API_KEY,
                        'offset': offset
                    }

                    async with session.get(url, params=params) as response:
                        data = await response.json()

                        if data and data.get('status') == 'success' and data.get('data'):
                            players = data['data']

                            # Store each player in database
                            for player in players:
                                key = player['name'].lower().strip()
                                player_database[key] = {
                                    'id': player['id'],
                                    'name': player['name'],
                                    'country': player['country'],
                                    # Use ESPN Cricinfo image format
                                    'image': f"https://img1.hscicdn.com/image/upload/f_auto,t_ds_square_w_320,q_50/lsci/db/PICTURES/CMS/players/{player['id']}.png"
                                }
                                fetched_count += 1

                            total_players = data['info']['totalRows']
                            offset += limit

                            # Log progress every 100 players
                            if fetched_count % 100 == 0:
                                print(f"Fetched {fetched_count}/{total_players} players...")

                            # Check if we've fetched all players
                            if fetched_count >= total_players:
                                has_more = False

                            # Small delay to avoid rate limiting
                            await asyncio.sleep(0.1)
                        else:
                            print('Invalid response from API')
                            has_more = False

                except Exception as err:
                    print(f"Error fetching at offset {offset}: {err}")
                    offset += limit
                    if offset > total_players:
                        has_more = False

        print(f"✓ Successfully loaded {len(player_database)} players!")
        is_loading = False

    except Exception as error:
        print(f'Fatal error fetching players: {error}')
        is_loading = False

def find_player(search_name: str) -> Optional[dict]:
    """Fuzzy search function to find closest match"""
    search = search_name.lower().strip()

    # Direct match
    if search in player_database:
        return player_database[search]

    # Partial match (player name contains search term)
    partial_matches = [
        player for key, player in player_database.items()
        if search in key or search in player['name'].lower()
    ]

    if len(partial_matches) == 1:
        return partial_matches[0]

    if len(partial_matches) > 1:
        # Return best match (shortest name that contains search)
        return sorted(partial_matches, key=lambda p: len(p['name']))[0]

    return None

@bot.event
async def on_ready():
    print(f'✓ Logged in as {bot.user.name}')
    print('Fetching player database... This may take a few minutes.')
    await fetch_all_players()

@bot.command(name='view')
async def view_player(ctx, *, player_name: str = None):
    """View a cricket player's image and name"""
    if is_loading:
        await ctx.send('⏳ Still loading player database... Please wait a moment.')
        return

    if not player_name:
        await ctx.send('Please provide a player name. Example: `.view Virat Kohli`')
        return

    player = find_player(player_name)

    if player:
        embed = discord.Embed(
            title=player['name'],
            color=discord.Color.blue()
        )
        embed.set_image(url=player['image'])

        await ctx.send(embed=embed)
    else:
        await ctx.send(f"❌ Player \"{player_name}\" not found in database. Try using their full name or use `.search {player_name}` to find similar names.")

@bot.command(name='search')
async def search_player(ctx, *, search_term: str = None):
    """Search for cricket players by name"""
    if is_loading:
        await ctx.send('⏳ Still loading player database... Please wait a moment.')
        return

    if not search_term:
        await ctx.send('Please provide a search term. Example: `.search kohli`')
        return

    search_lower = search_term.lower()
    matches = [
        player for player in player_database.values()
        if search_lower in player['name'].lower()
    ][:20]  # Limit to 20 results

    if not matches:
        await ctx.send(f"No players found matching \"{search_term}\".")
        return

    player_list = '\n'.join([f"• {p['name']} ({p['country']})" for p in matches])

    embed = discord.Embed(
        title=f"🔍 Search Results for \"{search_term}\"",
        description=player_list,
        color=discord.Color.orange()
    )
    embed.set_footer(text=f"Found {len(matches)} player(s)")

    await ctx.send(embed=embed)

@bot.command(name='stats')
async def show_stats(ctx):
    """Show bot statistics"""
    status = '⏳ Loading...' if is_loading else '✅ Ready'

    embed = discord.Embed(
        title='📊 Bot Statistics',
        description=f"**Total Players in Database:** {len(player_database)}\n**Status:** {status}",
        color=discord.Color.green()
    )

    await ctx.send(embed=embed)

@bot.command(name='commands')
async def show_help(ctx):
    """Show help message"""
    embed = discord.Embed(
        title='🏏 Cricket Player Bot - Commands',
        description=(
            '**`.view <player name>`** - View player image and name\n'
            '   Example: `.view Virat Kohli`\n\n'
            '**`.search <name>`** - Search for players by name\n'
            '   Example: `.search dhoni`\n\n'
            '**`.stats`** - Show bot statistics\n\n'
            '**`.help`** - Show this help message'
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"{len(player_database)} players available")

    await ctx.send(embed=embed)


bot.run(os.getenv('TOKEN'))
