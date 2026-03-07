import discord
import sqlite3
import re
import json
import random
import io
import aiohttp
from discord.ext import commands
from discord.ui import View, Button, Select
from PIL import Image, ImageDraw, ImageFont

# ========== DB INIT ==========

def init_series_db():
    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS series
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT,
                  teams TEXT,
                  is_active INTEGER DEFAULT 1,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS series_fixtures
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  series_id INTEGER,
                  match_number INTEGER,
                  team1 TEXT,
                  team2 TEXT,
                  channel_id INTEGER,
                  is_played INTEGER DEFAULT 0,
                  winner TEXT,
                  FOREIGN KEY (series_id) REFERENCES series(id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS series_match_stats
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  series_id INTEGER,
                  user_id INTEGER,
                  runs INTEGER DEFAULT 0,
                  balls_faced INTEGER DEFAULT 0,
                  runs_conceded INTEGER DEFAULT 0,
                  balls_bowled INTEGER DEFAULT 0,
                  wickets INTEGER DEFAULT 0,
                  not_out INTEGER DEFAULT 0,
                  FOREIGN KEY (series_id) REFERENCES series(id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS series_teams
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  series_id INTEGER,
                  team_name TEXT,
                  matches_played INTEGER DEFAULT 0,
                  wins INTEGER DEFAULT 0,
                  losses INTEGER DEFAULT 0,
                  nrr REAL DEFAULT 0.0,
                  FOREIGN KEY (series_id) REFERENCES series(id))''')

    conn.commit()
    conn.close()

# ========== HELPERS ==========

MATCH_CHANNELS = {
    1464251938521485403: "Dubai International Cricket Stadium",
    1464648443371978832: "Gaddafi Stadium Lahore",
    1464677627506987202: "National Stadium Karachi",
    1464677685593768047: "Rawalpindi Cricket Stadium",
    1464648571898036469: "Multan Cricket Stadium",
    1464677944222810429: "Arbab Niaz Stadium",
    1471920655955136736: "Abu Dhabi Cricket Stadium",
    1474421673858961550: "Malahide Cricket Stadium",
    1474442540936728740: "Castle Avenue Cricket Stadium",
}

FIXTURES_CHANNEL = 1474130877951906028

def get_team_flag(team_name):
    flags = {
        "India": "🇮🇳", "Pakistan": "🇵🇰", "Australia": "🇦🇺",
        "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "New Zealand": "🇳🇿", "South Africa": "🇿🇦",
        "West Indies": "🏝️", "Sri Lanka": "🇱🇰", "Bangladesh": "🇧🇩",
        "Afghanistan": "🇦🇫", "Netherlands": "🇳🇱", "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
        "Ireland": "🇮🇪", "Zimbabwe": "🇿🇼", "UAE": "🇦🇪",
        "Canada": "🇨🇦", "USA": "🇺🇸"
    }
    return flags.get(team_name, "🏳️")

def get_team_color(team_name):
    colors = {
        "India": 0x0066CC, "Pakistan": 0x006400, "Australia": 0xFFD700,
        "England": 0x012169, "New Zealand": 0x000000, "South Africa": 0x006B3F,
        "West Indies": 0x7B0041, "Sri Lanka": 0x003DA5, "Bangladesh": 0x006A4E,
        "Afghanistan": 0x5363ED, "Netherlands": 0xFF3600, "Scotland": 0xA100F2,
        "Ireland": 0x9DFF2E, "Zimbabwe": 0xFF2121, "UAE": 0xFC4444,
        "Canada": 0xFF0000, "USA": 0x080026
    }
    return colors.get(team_name, 0x808080)

def get_team_color_rgb(team_name):
    colors = {
        "India": (0, 102, 204), "Pakistan": (0, 100, 0), "Australia": (255, 215, 0),
        "England": (1, 33, 105), "New Zealand": (0, 0, 0), "South Africa": (0, 107, 63),
        "West Indies": (123, 0, 65), "Sri Lanka": (0, 61, 165), "Bangladesh": (0, 106, 78),
        "Afghanistan": (83, 99, 237), "Netherlands": (255, 54, 0), "Scotland": (161, 0, 242),
        "Ireland": (157, 255, 46), "Zimbabwe": (255, 33, 33), "UAE": (252, 68, 68),
        "Canada": (255, 0, 0), "USA": (8, 0, 38)
    }
    return colors.get(team_name, (128, 128, 128))

def get_team_flag_url(team_name):
    flag_codes = {
        "India": "1f1ee-1f1f3", "Pakistan": "1f1f5-1f1f0", "Australia": "1f1e6-1f1fa",
        "England": "1f3f4-e0067-e0062-e0065-e006e-e0067-e007f", "New Zealand": "1f1f3-1f1ff",
        "South Africa": "1f1ff-1f1e6", "Sri Lanka": "1f1f1-1f1f0", "Bangladesh": "1f1e7-1f1e9",
        "Afghanistan": "1f1e6-1f1eb", "Netherlands": "1f1f3-1f1f1",
        "Scotland": "1f3f4-e0067-e0062-e0073-e0063-e0074-e007f",
        "Ireland": "1f1ee-1f1ea", "Zimbabwe": "1f1ff-1f1fc", "UAE": "1f1e6-1f1ea",
        "Canada": "1f1e8-1f1e6", "USA": "1f1fa-1f1f8"
    }
    code = flag_codes.get(team_name)
    if code:
        return f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{code}.png"
    return None

def get_team_role_id(team_name):
    role_ids = {
        "India": 1460376137594044567, "Pakistan": 1460376138755866644,
        "Australia": 1460376139611640025, "England": 1460376141314654424,
        "New Zealand": 1460376142342000762, "South Africa": 1460376143633846527,
        "West Indies": 1460376148751028408, "Sri Lanka": 1460376147715166282,
        "Bangladesh": 1460376144862908523, "Afghanistan": 1460376146163273739,
        "Netherlands": 1460376154480312370, "Scotland": 1460376151795961897,
        "Ireland": 1460376149908525191, "Zimbabwe": 1460376157668245545,
        "UAE": 1460376158985130114, "Canada": 1460376154958725152,
        "USA": 1460376156250570824
    }
    return role_ids.get(team_name)

def get_player_name_by_user_id(user_id):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def get_user_team(user_id):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    if not result:
        return None
    player_name = result[0]
    try:
        with open('players.json', 'r', encoding='utf-8') as f:
            teams_data = json.load(f)
        for team_data in teams_data:
            for player in team_data['players']:
                if player['name'] == player_name:
                    return team_data['team']
    except:
        pass
    return None

def get_active_series():
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT id, name, teams FROM series WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
    result = c.fetchone()
    conn.close()
    return result

# ========== IMAGE GENERATION ==========

async def create_series_vs_image(team1, team2, stadium_name, series_name):
    """Create VS image for series fixture"""
    try:
        bg = Image.open("series.png").convert('RGBA')  # Changed from overlap.png
        width, height = bg.size

        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay, 'RGBA')

        color1 = get_team_color_rgb(team1)
        color2 = get_team_color_rgb(team2)

        for x in range(width // 2):
            progress = x / (width // 2)
            alpha = int(150 * (1 - progress))
            for y in range(height):
                draw.point((x, y), fill=color1 + (alpha,))

        for x in range(width // 2, width):
            progress = (x - width // 2) / (width // 2)
            alpha = int(150 * progress)
            for y in range(height):
                draw.point((x, y), fill=color2 + (alpha,))

        img = Image.alpha_composite(bg, overlay)
        flag_size = 200

        async with aiohttp.ClientSession() as session:
            for team, side in [(team1, 'left'), (team2, 'right')]:
                if team.lower() == "west indies":
                    try:
                        flag_img = Image.open("westindies.jpg").convert('RGBA')
                        flag_img = flag_img.resize((flag_size, flag_size), Image.Resampling.LANCZOS)
                        x = width // 4 - flag_size // 2 if side == 'left' else 3 * width // 4 - flag_size // 2
                        img.paste(flag_img, (x, height // 2 - flag_size // 2), flag_img)
                    except:
                        pass
                else:
                    flag_url = get_team_flag_url(team)
                    if flag_url:
                        try:
                            async with session.get(flag_url) as resp:
                                if resp.status == 200:
                                    flag_data = await resp.read()
                                    flag_img = Image.open(io.BytesIO(flag_data)).convert('RGBA')
                                    flag_img = flag_img.resize((flag_size, flag_size), Image.Resampling.LANCZOS)
                                    x = width // 4 - flag_size // 2 if side == 'left' else 3 * width // 4 - flag_size // 2
                                    img.paste(flag_img, (x, height // 2 - flag_size // 2), flag_img)
                        except:
                            pass

        draw_final = ImageDraw.Draw(img, 'RGBA')

        try:
            font = ImageFont.truetype("nor.otf", 80)
            small_font = ImageFont.truetype("nor.otf", 50)
        except:
            font = ImageFont.load_default()
            small_font = font

        # Stadium name at bottom
        bbox = draw_final.textbbox((0, 0), stadium_name, font=font)
        text_x = (width - (bbox[2] - bbox[0])) // 2
        text_y = height - (bbox[3] - bbox[1]) - 120
        for ox in [-2, 0, 2]:
            for oy in [-2, 0, 2]:
                if ox != 0 or oy != 0:
                    draw_final.text((text_x + ox, text_y + oy), stadium_name, font=font, fill=(0, 0, 0, 255))
        draw_final.text((text_x, text_y), stadium_name, font=font, fill=(255, 255, 255, 255))

        # Series name at top - WHITE  (changed from yellow)
        s_bbox = draw_final.textbbox((0, 0), series_name, font=small_font)
        s_x = (width - (s_bbox[2] - s_bbox[0])) // 2
        for ox in [-2, 0, 2]:
            for oy in [-2, 0, 2]:
                if ox != 0 or oy != 0:
                    draw_final.text((s_x + ox, 30 + oy), series_name, font=small_font, fill=(0, 0, 0, 255))
        draw_final.text((s_x, 30), series_name, font=small_font, fill=(255, 255, 255, 255))  # Changed to white

        output = io.BytesIO()
        img = img.convert('RGB')
        img.save(output, format='PNG', quality=95)
        output.seek(0)
        return output
    except Exception as e:
        print(f"Error creating series VS image: {e}")
        return None

async def create_series_standings_image(series_name, teams_data, fixtures):
    """Create a standings image for the series"""
    try:
        width = 1200
        header_height = 80
        row_height = 80
        top_padding = 40
        fixture_section_height = max(len(fixtures) * 60 + 80, 100)
        total_height = top_padding + header_height + (len(teams_data) * row_height) + fixture_section_height + 60

        img = Image.new('RGB', (width, total_height), (15, 25, 60))
        draw = ImageDraw.Draw(img)

        # Gradient background
        for y in range(total_height):
            ratio = y / total_height
            r = int(10 + (30 - 10) * ratio)
            g = int(20 + (50 - 20) * ratio)
            b = int(60 + (100 - 60) * ratio)
            draw.rectangle([(0, y), (width, y+1)], fill=(r, g, b))

        try:
            title_font = ImageFont.truetype("nor.otf", 60)
            header_font = ImageFont.truetype("nor.otf", 38)
            cell_font = ImageFont.truetype("nor.otf", 36)
            small_font = ImageFont.truetype("nor.otf", 30)
        except:
            title_font = ImageFont.load_default()
            header_font = title_font
            cell_font = title_font
            small_font = title_font

        # Title
        title_bbox = draw.textbbox((0, 0), series_name, font=title_font)
        title_w = title_bbox[2] - title_bbox[0]
        draw.text(((width - title_w) // 2, 10), series_name, fill=(255, 215, 0), font=title_font)

        cols = {'pos': 40, 'flag': 100, 'team': 175, 'w': 600, 'm': 720, 'l': 840, 'nrr': 960}

        # Header
        header_y = top_padding + 70
        header_bg = Image.new('RGB', (width, 50), (0, 80, 200))
        img.paste(header_bg, (0, header_y))

        for key, text in [('pos', 'POS'), ('team', 'TEAM'), ('w', 'W'), ('m', 'M'), ('l', 'L'), ('nrr', 'NRR')]:
            draw.text((cols[key], header_y + 10), text, fill=(255, 255, 255), font=header_font)

        # Flag cache
        flag_cache = {}
        async with aiohttp.ClientSession() as session:
            for team_name, *_ in teams_data:
                flag_url = get_team_flag_url(team_name)
                if flag_url and team_name not in flag_cache:
                    try:
                        async with session.get(flag_url) as resp:
                            if resp.status == 200:
                                flag_data = await resp.read()
                                flag_img = Image.open(io.BytesIO(flag_data)).convert('RGBA')
                                flag_img = flag_img.resize((45, 45), Image.Resampling.LANCZOS)
                                flag_cache[team_name] = flag_img
                    except:
                        pass

        for idx, (team_name, mp, w, l, nrr) in enumerate(teams_data):
            row_y = header_y + 50 + (idx * row_height)

            # Row bg
            bg_color = (20, 50, 120) if idx % 2 == 0 else (15, 40, 100)
            draw.rectangle([(0, row_y), (width, row_y + row_height)], fill=bg_color)

            # Team color accent
            tc = get_team_color_rgb(team_name)
            for x in range(8):
                draw.rectangle([(x, row_y), (x, row_y + row_height)], fill=tc)

            pos_color = (255, 215, 0) if idx == 0 else (200, 200, 200) if idx == 1 else (205, 127, 50) if idx == 2 else (255, 255, 255)
            draw.text((cols['pos'], row_y + 20), str(idx + 1), fill=pos_color, font=cell_font)

            if team_name in flag_cache:
                img.paste(flag_cache[team_name], (cols['flag'], row_y + 18), flag_cache[team_name])

            draw.text((cols['team'], row_y + 20), team_name, fill=(255, 255, 255), font=cell_font)
            draw.text((cols['w'], row_y + 20), str(w), fill=(100, 255, 100), font=cell_font)
            draw.text((cols['m'], row_y + 20), str(mp), fill=(255, 255, 255), font=cell_font)
            draw.text((cols['l'], row_y + 20), str(l), fill=(255, 100, 100), font=cell_font)
            nrr_color = (100, 255, 100) if nrr >= 0 else (255, 100, 100)
            draw.text((cols['nrr'], row_y + 20), f"{nrr:+.3f}", fill=nrr_color, font=cell_font)
            draw.line([(0, row_y + row_height - 1), (width, row_y + row_height - 1)], fill=(40, 70, 160), width=1)

        # Fixtures section
        fixtures_y = header_y + 50 + (len(teams_data) * row_height) + 30
        draw.text((40, fixtures_y), "FIXTURES", fill=(255, 215, 0), font=header_font)
        fixtures_y += 50

        for match_num, team1, team2, channel_id, is_played, winner in fixtures:
            f1 = get_team_flag(team1)
            f2 = get_team_flag(team2)
            if is_played:
                status = f"✓ {winner} WON" if winner else "✓ Played"
                color = (100, 200, 100)
            else:
                status = "Upcoming"
                color = (180, 180, 180)
            line = f"Match {match_num}: {team1} vs {team2}  —  {status}"
            draw.text((40, fixtures_y), line, fill=color, font=small_font)
            fixtures_y += 55

        output = io.BytesIO()
        img.save(output, format='PNG', quality=95)
        output.seek(0)
        return output
    except Exception as e:
        print(f"Error creating series standings: {e}")
        import traceback
        traceback.print_exc()
        return None

# ========== COG ==========

class Series(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        init_series_db()

    @commands.command(name="seriesmake", aliases=["seriesm"], help="Create a new series (2-3 teams)")
    @commands.has_permissions(administrator=True)
    async def seriesmake(self, ctx, *teams):
        """Create a series with 2 or 3 teams. Usage: -seriesmake India Pakistan [Australia]"""

        if len(teams) < 2 or len(teams) > 3:
            await ctx.send("❌ You must specify 2 or 3 teams!\nUsage: `-seriesmake Team1 Team2 [Team3]`")
            return

        # Validate team names
        valid_teams = [
            "India", "Pakistan", "Australia", "England", "New Zealand",
            "South Africa", "West Indies", "Sri Lanka", "Bangladesh",
            "Afghanistan", "Netherlands", "Scotland", "Ireland", "Zimbabwe",
            "UAE", "Canada", "USA"
        ]

        teams_list = list(teams)
        for team in teams_list:
            if team not in valid_teams:
                await ctx.send(f"❌ Invalid team: `{team}`\nValid teams: {', '.join(valid_teams)}")
                return

        if len(set(teams_list)) != len(teams_list):
            await ctx.send("❌ Duplicate teams detected!")
            return

        # Ask for series name
        await ctx.send("📝 What should this series be called? (e.g. `Pakistan vs India - 3 Match Series`)")

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            name_msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            series_name = name_msg.content.strip()
        except TimeoutError:
            await ctx.send("❌ Timeout! Series creation cancelled.")
            return

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Deactivate any existing active series
        c.execute("UPDATE series SET is_active = 0 WHERE is_active = 1")

        # Create series
        c.execute("INSERT INTO series (name, teams) VALUES (?, ?)",
                  (series_name, json.dumps(teams_list)))
        series_id = c.lastrowid

        # Create series team entries
        for team in teams_list:
            c.execute("INSERT INTO series_teams (series_id, team_name) VALUES (?, ?)",
                      (series_id, team))

        conn.commit()
        conn.close()

        flags = " vs ".join([f"{get_team_flag(t)} **{t}**" for t in teams_list])
        embed = discord.Embed(
            title="✅ Series Created!",
            description=f"**{series_name}**\n\n{flags}\n\n"
                        f"Use `-seriesfixture` to add fixtures.\n"
                        f"Use `-seriesstats` to view standings.",
            color=0x00FF00
        )
        embed.set_footer(text=f"Series ID: {series_id}")
        await ctx.send(embed=embed)

    @commands.command(name="seriesfixture", aliases=["sf2"], help="[ADMIN] Post a fixture for the active series")
    @commands.has_permissions(administrator=True)
    async def seriesfixture(self, ctx, team1: str, team2: str):
        """Add and post a fixture for the active series"""

        series = get_active_series()
        if not series:
            await ctx.send("❌ No active series! Use `-seriesmake` first.")
            return

        series_id, series_name, teams_json = series
        series_teams = json.loads(teams_json)

        if team1 not in series_teams or team2 not in series_teams:
            await ctx.send(f"❌ Both teams must be in the series! Series teams: {', '.join(series_teams)}")
            return

        if team1 == team2:
            await ctx.send("❌ Teams must be different!")
            return

        # Get next match number
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM series_fixtures WHERE series_id = ?", (series_id,))
        match_num = c.fetchone()[0] + 1
        conn.close()

        # Stadium selection view
        class StadiumView(View):
            def __init__(self):
                super().__init__(timeout=60)
                self.selected_channel_id = None
                options = [
                    discord.SelectOption(label=name, value=str(cid), emoji="🏟️")
                    for cid, name in MATCH_CHANNELS.items()
                ]
                select = Select(placeholder="🏟️ Select Stadium", options=options)
                select.callback = self.stadium_callback
                self.add_item(select)

            async def stadium_callback(self, interaction: discord.Interaction):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message("❌ Not your menu!", ephemeral=True)
                    return
                self.selected_channel_id = int(interaction.data['values'][0])
                self.stop()
                await interaction.response.defer()

        view = StadiumView()
        select_embed = discord.Embed(
            title="🏟️ Select Stadium",
            description=f"{get_team_flag(team1)} **{team1}** vs {get_team_flag(team2)} **{team2}**\n"
                        f"Match #{match_num} — {series_name}",
            color=0x0066CC
        )
        msg = await ctx.send(embed=select_embed, view=view)
        await view.wait()

        if not view.selected_channel_id:
            await ctx.send("❌ Timed out! No stadium selected.")
            return

        stadium = MATCH_CHANNELS[view.selected_channel_id]

        # Save fixture
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("INSERT INTO series_fixtures (series_id, match_number, team1, team2, channel_id) VALUES (?, ?, ?, ?, ?)",
                  (series_id, match_num, team1, team2, view.selected_channel_id))
        conn.commit()
        conn.close()

        # Create and post VS image
        vs_image = await create_series_vs_image(team1, team2, stadium, series_name)

        embed = discord.Embed(
            title=f"🏏 {series_name}",
            description=f"**Match #{match_num}**",
            color=0x00FF00
        )
        embed.add_field(name="Match",
                        value=f"{get_team_flag(team1)} **{team1}** vs {get_team_flag(team2)} **{team2}**",
                        inline=False)
        embed.add_field(name="Stadium", value=f"🏟️ <#{view.selected_channel_id}>", inline=False)
        embed.set_footer(text="TourneyFanHub")

        fixtures_channel = ctx.guild.get_channel(FIXTURES_CHANNEL)
        if fixtures_channel:
            role1_id = get_team_role_id(team1)
            role2_id = get_team_role_id(team2)
            ping_text = " ".join(filter(None, [
                f"<@&{role1_id}>" if role1_id else "",
                f"<@&{role2_id}>" if role2_id else ""
            ]))

            if vs_image:
                file = discord.File(vs_image, filename=f"series_match{match_num}.png")
                embed.set_image(url=f"attachment://series_match{match_num}.png")
                if ping_text:
                    await fixtures_channel.send(content=ping_text, embed=embed, file=file)
                else:
                    await fixtures_channel.send(embed=embed, file=file)
            else:
                if ping_text:
                    await fixtures_channel.send(content=ping_text, embed=embed)
                else:
                    await fixtures_channel.send(embed=embed)

        await msg.edit(content=f"✅ Match #{match_num} fixture posted!", embed=None, view=None)

    @commands.command(name="seriesaddstats", aliases=["sas"], help="[ADMIN] Add stats for a series match (also updates overall stats)")
    @commands.has_any_role(1452028308735922339)
    async def seriesaddstats(self, ctx):
        """Add stats that count for BOTH series AND overall/international stats"""

        series = get_active_series()
        if not series:
            await ctx.send("❌ No active series! Use `-seriesmake` first.")
            return

        series_id, series_name, teams_json = series

        if not ctx.message.reference:
            await ctx.send("❌ Please reply to a message containing match statistics!")
            return

        replied_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        content = replied_msg.content

        code_block_pattern = r'```(?:python)?\s*([\s\S]*?)```'
        code_blocks = re.findall(code_block_pattern, content)

        if not code_blocks:
            await ctx.send("❌ No code block found in the message!")
            return

        first_block = code_blocks[0]
        pattern = r'(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)'
        matches = re.findall(pattern, first_block)

        if not matches:
            await ctx.send("❌ No valid statistics found!")
            return

        # Detect teams
        teams_detected = set()
        for match in matches:
            user_id = int(match[0])
            team = get_user_team(user_id)
            if team:
                teams_detected.add(team)

        teams_list = list(teams_detected)
        if len(teams_list) != 2:
            await ctx.send(f"❌ Expected 2 teams, detected {len(teams_list)}: {', '.join(teams_list)}")
            return

        series_teams = json.loads(teams_json)
        for team in teams_list:
            if team not in series_teams:
                await ctx.send(f"❌ {team} is not part of this series ({series_name})!")
                return

        # Ask for scores
        team_scores = {}
        for i, team in enumerate(teams_list):
            flag = get_team_flag(team)
            embed = discord.Embed(
                title=f"📊 Score Input — {team}",
                description=f"{flag} **{team}**\n\nFormat: `runs/wickets overs`\nExample: `145/8 10.0`",
                color=get_team_color(team)
            )
            embed.set_footer(text=f"Team {i+1} of {len(teams_list)} • {series_name}")
            await ctx.send(embed=embed)

            def check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

            try:
                msg = await self.bot.wait_for('message', timeout=300.0, check=check)
                input_pattern = r'(\d+)/(\d+)\s+(\d+(?:\.\d+)?)'
                match_obj = re.match(input_pattern, msg.content.strip(), re.IGNORECASE)
                if not match_obj:
                    await ctx.send("❌ Invalid format! Cancelled.")
                    return

                runs = int(match_obj.group(1))
                wickets = int(match_obj.group(2))
                overs_str = match_obj.group(3)
                overs_parts = overs_str.split('.')
                balls = int(overs_parts[0]) * 6
                if len(overs_parts) > 1:
                    balls += int(overs_parts[1])

                team_scores[team] = {'runs': runs, 'wickets': wickets, 'balls': balls}
                await ctx.send(f"✅ {team}: **{runs}/{wickets}** in **{overs_str}** overs recorded!")
            except TimeoutError:
                await ctx.send("❌ Timeout!")
                return

        team1, team2 = teams_list
        t1 = team_scores[team1]
        t2 = team_scores[team2]

        # Determine winner
        if t1['runs'] == t2['runs']:
            await ctx.send("🟰 Scores tied! Type the winning team name (Super Over winner):")

            def check2(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content in [team1, team2]

            try:
                w_msg = await self.bot.wait_for('message', timeout=60.0, check=check2)
                winner = w_msg.content.strip()
            except TimeoutError:
                await ctx.send("❌ Timeout!")
                return
        else:
            winner = team1 if t1['runs'] > t2['runs'] else team2

        loser = team2 if winner == team1 else team1

        # Batting order
        await ctx.send(f"🏏 Which team batted **first**?\n1. {team1}\n2. {team2}")
        try:
            order_msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            if "1" in order_msg.content or team1.lower() in order_msg.content.lower():
                bat_first, bat_second = team1, team2
            else:
                bat_first, bat_second = team2, team1
        except TimeoutError:
            bat_first, bat_second = team1, team2 # Fallback

        # NRR calculation
        t1_rr = (t1['runs'] / t1['balls']) * 6 if t1['balls'] > 0 else 0
        t2_rr = (t2['runs'] / t2['balls']) * 6 if t2['balls'] > 0 else 0
        nrr_change = abs(t1_rr - t2_rr)

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # 1) Insert into series_match_stats (series-specific)
        for match in matches:
            user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out = map(int, match)
            c.execute("""INSERT INTO series_match_stats
                         (series_id, user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                      (series_id, user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out))

        # 2) Insert into match_stats (overall/international stats)
        for match in matches:
            user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out = map(int, match)
            user_team = get_user_team(user_id)
            bat_order = 1 if user_team == bat_first else 2
            
            c.execute("""INSERT INTO match_stats (user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out)
                 VALUES (?, ?, ?, ?, ?, ?, ?)""",
              (user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out))

        # 3) Update series_teams standings
        c.execute("""UPDATE series_teams 
                    SET wins = wins + 1, matches_played = matches_played + 1, nrr = nrr + ?
                    WHERE series_id = ? AND team_name = ?""",
                  (nrr_change, series_id, winner))

        c.execute("""UPDATE series_teams 
                    SET losses = losses + 1, matches_played = matches_played + 1, nrr = nrr - ?
                    WHERE series_id = ? AND team_name = ?""",
                  (nrr_change, series_id, loser))

        # 4) Mark fixture as played
        c.execute("""SELECT id FROM series_fixtures 
                    WHERE series_id = ? 
                    AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))
                    AND is_played = 0
                    ORDER BY match_number ASC
                    LIMIT 1""", (series_id, team1, team2, team2, team1))
        fixture_row = c.fetchone()
        if fixture_row:
            c.execute("UPDATE series_fixtures SET is_played = 1, winner = ? WHERE id = ?", (winner, fixture_row[0]))

        conn.commit()
        conn.close()

        flag1 = get_team_flag(team1)
        flag2 = get_team_flag(team2)
        winner_flag = get_team_flag(winner)

        embed = discord.Embed(
            title="✅ Series Match Stats Added",
            description=f"**{series_name}**\n\n"
                        f"{flag1} **{team1}**: {t1['runs']}/{t1['wickets']} in {t1['balls']//6}.{t1['balls']%6} overs\n"
                        f"{flag2} **{team2}**: {t2['runs']}/{t2['wickets']} in {t2['balls']//6}.{t2['balls']%6} overs\n\n"
                        f"{winner_flag} **{winner} WON!**\n\n"
                        f"✅ Stats added to **series** standings\n"
                        f"✅ Stats added to **overall/international** records",
            color=0x00FF00
        )
        embed.set_footer(text=f"{len(matches)} players • {series_name}")
        await ctx.send(embed=embed)

    @commands.command(name="seriesstats", aliases=["ss2"], help="View current series standings")
    async def seriesstats(self, ctx):
        """View current series standings and fixtures"""
        series = get_active_series()
        if not series:
            await ctx.send("❌ No active series!")
            return

        series_id, series_name, teams_json = series

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        c.execute("""SELECT team_name, matches_played, wins, losses, nrr
                    FROM series_teams WHERE series_id = ?
                    ORDER BY wins DESC, nrr DESC""", (series_id,))
        teams_data = c.fetchall()

        c.execute("""SELECT match_number, team1, team2, channel_id, is_played, winner
                    FROM series_fixtures WHERE series_id = ?
                    ORDER BY match_number ASC""", (series_id,))
        fixtures = c.fetchall()
        conn.close()

        image = await create_series_standings_image(series_name, teams_data, fixtures)

        if image:
            file = discord.File(image, filename="series_standings.png")
            embed = discord.Embed(title=f"📊 {series_name}", color=0x1E90FF)
            embed.set_image(url="attachment://series_standings.png")

            # Quick text summary
            played = sum(1 for f in fixtures if f[4])
            total = len(fixtures)
            embed.set_footer(text=f"Matches: {played}/{total} played")
            await ctx.send(embed=embed, file=file)
        else:
            # Fallback text embed
            embed = discord.Embed(title=f"📊 {series_name}", color=0x1E90FF)
            for team_name, mp, w, l, nrr in teams_data:
                flag = get_team_flag(team_name)
                embed.add_field(
                    name=f"{flag} {team_name}",
                    value=f"W: {w} | L: {l} | M: {mp} | NRR: {nrr:+.3f}",
                    inline=False
                )
            await ctx.send(embed=embed)

    @commands.command(name="seriesend", aliases=["se"], help="[ADMIN] End the current series")
    @commands.has_permissions(administrator=True)
    async def seriesend(self, ctx):
        """End the active series"""
        series = get_active_series()
        if not series:
            await ctx.send("❌ No active series!")
            return

        series_id, series_name, teams_json = series

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Get final standings
        c.execute("""SELECT team_name, wins, losses, matches_played
                    FROM series_teams WHERE series_id = ?
                    ORDER BY wins DESC, matches_played ASC""", (series_id,))
        standings = c.fetchall()

        c.execute("UPDATE series SET is_active = 0 WHERE id = ?", (series_id,))
        conn.commit()
        conn.close()

        winner_team = standings[0][0] if standings else "Unknown"
        winner_flag = get_team_flag(winner_team)

        embed = discord.Embed(
            title="🏆 Series Ended!",
            description=f"**{series_name}**\n\n{winner_flag} **{winner_team}** wins the series!\n\n**Final Standings:**",
            color=0xFFD700
        )

        medals = ["🥇", "🥈", "🥉"]
        for i, (team_name, wins, losses, mp) in enumerate(standings):
            flag = get_team_flag(team_name)
            medal = medals[i] if i < len(medals) else f"{i+1}."
            embed.add_field(
                name=f"{medal} {flag} {team_name}",
                value=f"W: {wins} | L: {losses} | Played: {mp}",
                inline=False
            )

        await ctx.send(embed=embed)

    @commands.command(name="seriesinfo", help="View active series info")
    async def seriesinfo(self, ctx):
        """Quick info about the active series"""
        series = get_active_series()
        if not series:
            await ctx.send("❌ No active series!")
            return

        series_id, series_name, teams_json = series
        series_teams = json.loads(teams_json)

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("""SELECT match_number, team1, team2, channel_id, is_played, winner
                    FROM series_fixtures WHERE series_id = ?
                    ORDER BY match_number""", (series_id,))
        fixtures = c.fetchall()
        conn.close()

        flags = " vs ".join([f"{get_team_flag(t)} **{t}**" for t in series_teams])
        embed = discord.Embed(title=f"🏏 {series_name}", description=flags, color=0x1E90FF)

        played_text = ""
        upcoming_text = ""
        for match_num, t1, t2, ch_id, is_played, winner in fixtures:
            f1 = get_team_flag(t1)
            f2 = get_team_flag(t2)
            if is_played:
                w_flag = get_team_flag(winner) if winner else ""
                played_text += f"Match {match_num}: {f1} {t1} vs {f2} {t2} → {w_flag} **{winner}**\n"
            else:
                upcoming_text += f"Match {match_num}: {f1} {t1} vs {f2} {t2} • <#{ch_id}>\n"

        if played_text:
            embed.add_field(name="✅ Played", value=played_text, inline=False)
        if upcoming_text:
            embed.add_field(name="📅 Upcoming", value=upcoming_text, inline=False)
        if not fixtures:
            embed.add_field(name="📅 Fixtures", value="None posted yet. Use `-seriesfixture`", inline=False)

        embed.set_footer(text=f"Series ID: {series_id} • Use -seriesstats for full standings")
        await ctx.send(embed=embed)

    @commands.command(name="serieswinner", help="[ADMIN] Record a winner for a series match manually")
    @commands.has_permissions(administrator=True)
    async def serieswinner(self, ctx, winner_team: str, opponent_team: str):
        """Record a match result manually. Usage: -serieswinner India Pakistan"""
        series = get_active_series()
        if not series:
            await ctx.send("❌ No active series found!")
            return

        series_id, series_name, teams_json = series
        series_teams = json.loads(teams_json)

        if winner_team not in series_teams or opponent_team not in series_teams:
            await ctx.send(f"❌ Both teams must be in the series! Teams: {', '.join(series_teams)}")
            return

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            # 1. Runs/Wickets for Winner
            await ctx.send(f"🏏 How many runs and wickets did **{winner_team}** make? (Format: `runs/wickets`, e.g., `180/4`)")
            msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            w_runs, w_wickets = map(int, msg.content.split('/'))

            # 2. Overs for Winner
            await ctx.send(f"⏳ How many overs did **{winner_team}** play? (e.g., `20.0`)")
            msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            w_overs = float(msg.content)

            # 3. Runs/Wickets for Opponent
            await ctx.send(f"🏏 How many runs and wickets did **{opponent_team}** make? (Format: `runs/wickets`, e.g., `150/10`)")
            msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            o_runs, o_wickets = map(int, msg.content.split('/'))

            # 4. Overs for Opponent
            await ctx.send(f"⏳ How many overs did **{opponent_team}** play? (e.g., `18.2`)")
            msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            o_overs = float(msg.content)

            # 5. Who batted first?
            await ctx.send(f"❓ Which team batted first?\n1. {winner_team}\n2. {opponent_team}")
            msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            bat_first = winner_team if "1" in msg.content else opponent_team

        except Exception as e:
            await ctx.send(f"❌ Error or Timeout: {e}")
            return

        # NRR Calculation helper
        def to_balls(overs):
            o = int(overs)
            b = int(round((overs - o) * 10))
            return o * 6 + b

        w_balls = to_balls(w_overs)
        o_balls = to_balls(o_overs)

        # Basic NRR: (Runs Scored / Overs Faced) - (Runs Conceded / Overs Bowled)
        # For simplicity in this manual command, we'll calculate the gap
        w_rr = (w_runs / w_balls) * 6 if w_balls > 0 else 0
        o_rr = (o_runs / o_balls) * 6 if o_balls > 0 else 0
        nrr_change = abs(w_rr - o_rr)

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Update standings
        c.execute("""UPDATE series_teams 
                    SET wins = wins + 1, matches_played = matches_played + 1, nrr = nrr + ?
                    WHERE series_id = ? AND team_name = ?""", (nrr_change, series_id, winner_team))
        
        c.execute("""UPDATE series_teams 
                    SET losses = losses + 1, matches_played = matches_played + 1, nrr = nrr - ?
                    WHERE series_id = ? AND team_name = ?""", (nrr_change, series_id, opponent_team))

        # Mark fixture as played if exists
        c.execute("""UPDATE series_fixtures SET is_played = 1, winner = ? 
                    WHERE series_id = ? AND is_played = 0 
                    AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))
                    LIMIT 1""", (winner_team, series_id, winner_team, opponent_team, opponent_team, winner_team))

        conn.commit()
        conn.close()

        await ctx.send(f"✅ Result recorded! **{winner_team}** beat **{opponent_team}**.\nNRR Impact: {nrr_change:+.3f}")

    @commands.command(name="sptsi", help="View the international points table for Series matches only")
    async def sptsi(self, ctx):
        """Points table for Series matches only"""
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Aggregate stats from series_teams
        c.execute("""
            SELECT team_name, SUM(wins) as w, SUM(losses) as l, SUM(matches_played) as mp, SUM(nrr) as n
            FROM series_teams
            GROUP BY team_name
            HAVING mp > 0
            ORDER BY w DESC, n DESC
        """)
        data = c.fetchall()
        conn.close()

        if not data:
            await ctx.send("❌ No series match data found!")
            return

        embed = discord.Embed(title="🌍 Series International Points Table", color=0x1E90FF)
        description = "```yaml\nPOS TEAM          W   L   M    NRR\n"
        for i, (team, w, l, mp, nrr) in enumerate(data, 1):
            flag = get_team_flag(team)
            description += f"{i:<3} {team:<13} {w:<3} {l:<3} {mp:<3} {nrr:>+6.3f}\n"
        description += "```"
        embed.description = description
        await ctx.send(embed=embed)

    @commands.command(name="serieslb", aliases=["slb"], help="View leaderboard for a specific series")
    async def serieslb(self, ctx):
        """View leaderboard for a specific series"""
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("SELECT id, name FROM series WHERE is_active = 1")
        active_series = c.fetchall()
        
        if not active_series:
            await ctx.send("❌ No active series found!")
            conn.close()
            return

        class SeriesSelect(Select):
            def __init__(self, series_list, bot):  # Add bot parameter
                options = [discord.SelectOption(label=name, value=str(sid)) for sid, name in series_list]
                super().__init__(placeholder="Select a series...", options=options)
                self.bot = bot  # Store it

            async def callback(self, interaction: discord.Interaction):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message("❌ Not your menu!", ephemeral=True)
                    return

                series_id = int(self.values[0])
                from cricket_stats import LeaderboardView

                view = LeaderboardView(ctx, "runs", self.bot, series_id=series_id)  # Now works

                embed, graphic = await view.create_leaderboard_embed(0)
                view.update_buttons()

                if graphic:
                    file = discord.File(graphic, filename="leaderboard_top5.png")
                    await interaction.response.edit_message(embed=embed, attachments=[file], view=view)
                else:
                    await interaction.response.edit_message(embed=embed, view=view)

                view.message = interaction.message

        view = View()
        view.add_item(SeriesSelect(active_series, self.bot))  # Pass self.bot here
        await ctx.send("📋 Select a series to view its leaderboard:", view=view)

    @commands.command(name="sremindd", aliases=["srrrd"], help="Remind teams about their latest series match")
    async def sremind(self, ctx, team1: str, team2: str):
        """Remind teams about their latest series match"""
        series = get_active_series()
        if not series:
            await ctx.send("❌ No active series found!")
            return

        series_id, series_name, _ = series

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("""SELECT match_number, channel_id FROM series_fixtures 
                    WHERE series_id = ? 
                    AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))
                    AND is_played = 0
                    ORDER BY match_number ASC LIMIT 1""", 
                 (series_id, team1, team2, team2, team1))
        fixture = c.fetchone()
        conn.close()

        if not fixture:
            await ctx.send(f"❌ No upcoming match found between **{team1}** and **{team2}** in the current series!")
            return

        match_num, channel_id = fixture
        role1_id = get_team_role_id(team1)
        role2_id = get_team_role_id(team2)

        ping_text = ""
        if role1_id: ping_text += f"<@&{role1_id}> "
        if role2_id: ping_text += f"<@&{role2_id}> "

        embed = discord.Embed(
            title=f"🔔 Match Reminder: {series_name}",
            description=f"**Match #{match_num}**: {get_team_flag(team1)} **{team1}** vs {get_team_flag(team2)} **{team2}**\n"
                        f"Stadium: <#{channel_id}>\n\n"
                        f"Please get ready for your match!",
            color=0xFFA500
        )
        
        await ctx.send(content=ping_text.strip(), embed=embed)

async def setup(bot):
    await bot.add_cog(Series(bot))