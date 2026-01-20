import discord
import sqlite3
import random
from discord.ext import commands
from discord.ui import View, Button, Select
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont
import io
import aiohttp

def init_tournament_db():
    """Initialize tournament database tables"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Tournament table
    c.execute('''CREATE TABLE IF NOT EXISTS tournaments
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT UNIQUE,
                  is_active INTEGER DEFAULT 1,
                  current_round INTEGER DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Participating teams
    c.execute('''CREATE TABLE IF NOT EXISTS tournament_teams
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tournament_id INTEGER,
                  team_name TEXT,
                  points INTEGER DEFAULT 0,
                  matches_played INTEGER DEFAULT 0,
                  wins INTEGER DEFAULT 0,
                  losses INTEGER DEFAULT 0,
                  nrr REAL DEFAULT 0.0,
                  fpp INTEGER DEFAULT 0,
                  FOREIGN KEY (tournament_id) REFERENCES tournaments(id))''')

    # Fixtures
    c.execute('''CREATE TABLE IF NOT EXISTS fixtures
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tournament_id INTEGER,
                  round_number INTEGER,
                  team1 TEXT,
                  team2 TEXT,
                  channel_id INTEGER,
                  is_played INTEGER DEFAULT 0,
                  is_reserved INTEGER DEFAULT 0,
                  winner TEXT,
                  FOREIGN KEY (tournament_id) REFERENCES tournaments(id))''')

    conn.commit()
    conn.close()

# Available match channels (stadiums)
MATCH_CHANNELS = {
    1452048274486726809: "Stadium"
}

# Channel for posting fixtures
FIXTURES_CHANNEL = 1452272794560757810

def get_active_tournament():
    """Get the currently active tournament"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT id, name, current_round FROM tournaments WHERE is_active = 1 LIMIT 1")
    result = c.fetchone()
    conn.close()
    return result

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

def get_team_color(team_name):
    """Get team color (imported from main.py logic)"""
    colors = {
        "India": 0x0066CC,
        "Pakistan": 0x006400,
        "Australia": 0xFFD700,
        "England": 0x012169,
        "New Zealand": 0x000000,
        "South Africa": 0x006B3F,
        "West Indies": 0x7B0041,
        "Sri Lanka": 0x003DA5,
        "Bangladesh": 0x006A4E,
        "Afghanistan": 0x5363ED,
        "Netherlands": 0xFF3600,
        "Scotland": 0xA100F2,
        "Ireland": 0x9DFF2E,
        "Zimbabwe": 0xFF2121,
        "UAE": 0xFC4444,
        "Canada": 0xFF0000,
        "USA": 0x080026
    }
    return colors.get(team_name, 0x808080)

def get_team_flag(team_name):
    """Get team flag emoji"""
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

def get_team_role_id(team_name):
    """Get role ID for a team"""
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
    return role_ids.get(team_name)

def get_user_team(user_id):
    """Get the team a user belongs to based on their claimed player"""
    import json

    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()

    if not result:
        return None

    player_name = result[0]

    # Load players.json to find which team this player belongs to
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

async def create_vs_image(team1, team2, stadium_name):
    """Create a VS image with gradient colors, team flags, and stadium name"""
    try:
        # Load the background
        bg = Image.open("overlap.png").convert('RGBA')
        width, height = bg.size

        # Create overlay for gradients with HIGHER intensity
        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay, 'RGBA')

        # Get team colors
        color1 = get_team_color_rgb(team1)
        color2 = get_team_color_rgb(team2)

        # Create smooth fading gradients with HIGHER alpha (150 instead of 80)
        # Left side gradient (team1 color)
        for x in range(width // 2):
            progress = x / (width // 2)
            alpha = int(150 * (1 - progress))  # Increased from 80

            for y in range(height):
                draw.point((x, y), fill=color1 + (alpha,))

        # Right side gradient (team2 color)
        for x in range(width // 2, width):
            progress = (x - width // 2) / (width // 2)
            alpha = int(150 * progress)  # Increased from 80

            for y in range(height):
                draw.point((x, y), fill=color2 + (alpha,))

        # Composite overlay onto background
        img = Image.alpha_composite(bg, overlay)

        # Download and paste team flags as emojis
        flag_size = 200  # Size of the flag emoji

        async with aiohttp.ClientSession() as session:
            # Left flag (team1)
            flag1_url = get_team_flag_url(team1)
            if flag1_url:
                try:
                    async with session.get(flag1_url) as resp:
                        if resp.status == 200:
                            flag_data = await resp.read()
                            flag1 = Image.open(io.BytesIO(flag_data)).convert('RGBA')
                            flag1 = flag1.resize((flag_size, flag_size), Image.Resampling.LANCZOS)

                            # Position on left side
                            flag1_x = width // 4 - flag_size // 2
                            flag1_y = height // 2 - flag_size // 2
                            img.paste(flag1, (flag1_x, flag1_y), flag1)
                except Exception as e:
                    print(f"Error loading team1 flag: {e}")

            # Right flag (team2)
            flag2_url = get_team_flag_url(team2)
            if flag2_url:
                try:
                    async with session.get(flag2_url) as resp:
                        if resp.status == 200:
                            flag_data = await resp.read()
                            flag2 = Image.open(io.BytesIO(flag_data)).convert('RGBA')
                            flag2 = flag2.resize((flag_size, flag_size), Image.Resampling.LANCZOS)

                            # Position on right side
                            flag2_x = 3 * width // 4 - flag_size // 2
                            flag2_y = height // 2 - flag_size // 2
                            img.paste(flag2, (flag2_x, flag2_y), flag2)
                except Exception as e:
                    print(f"Error loading team2 flag: {e}")

        # Add stadium name at the bottom
        draw_final = ImageDraw.Draw(img, 'RGBA')

        try: 
            font = ImageFont.truetype("nor.otf", 80)
        except:
            font = ImageFont.load_default()

        bbox = draw_final.textbbox((0, 0), stadium_name, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        text_x = (width - text_width) // 2
        text_y = height - text_height - 120

        # Draw text with outline
        for offset_x in [-2, 0, 2]:
            for offset_y in [-2, 0, 2]:
                if offset_x != 0 or offset_y != 0:
                    draw_final.text((text_x + offset_x, text_y + offset_y), 
                                  stadium_name, font=font, fill=(0, 0, 0, 255))
        draw_final.text((text_x, text_y), stadium_name, font=font, fill=(255, 255, 255, 255))

        # Convert to bytes
        output = io.BytesIO()
        img = img.convert('RGB')
        img.save(output, format='PNG', quality=95)
        output.seek(0)

        return output
    except Exception as e:
        print(f"Error creating VS image: {e}")
        return None

def get_team_flag_url(team_name):
    """Get team flag URL for downloading"""
    flag_codes = {
        "India": "1f1ee-1f1f3",
        "Pakistan": "1f1f5-1f1f0",
        "Australia": "1f1e6-1f1fa",
        "England": "1f3f4-e0067-e0062-e0065-e006e-e0067-e007f",
        "New Zealand": "1f1f3-1f1ff",
        "South Africa": "1f1ff-1f1e6",
        "West Indies": "1f3f4",
        "Sri Lanka": "1f1f1-1f1f0",
        "Bangladesh": "1f1e7-1f1e9",
        "Afghanistan": "1f1e6-1f1eb",
        "Netherlands": "1f1f3-1f1f1",
        "Scotland": "1f3f4-e0067-e0062-e0073-e0063-e0074-e007f",
        "Ireland": "1f1ee-1f1ea",
        "Zimbabwe": "1f1ff-1f1fc",
        "UAE": "1f1e6-1f1ea",
        "Canada": "1f1e8-1f1e6",
        "USA": "1f1fa-1f1f8"
    }
    code = flag_codes.get(team_name)
    if code:
        return f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{code}.png"
    return None

async def create_points_table_image(tournament_name, teams_data):
    """Create a beautiful points table image with team gradients and dividers"""
    try:
        # Image dimensions
        width = 1400
        header_height = 80  # Reduced from 120
        row_height = 90  # Increased from 80
        top_padding = 40  # Reduced from default
        total_height = top_padding + header_height + (len(teams_data) * row_height) + 80

        # Create white background
        img = Image.new('RGB', (width, total_height), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Load fonts - ALL using nor.otf with BIGGER sizes
        try:
            title_font = ImageFont.truetype("nor.otf", 70)  # Increased from 60
            header_font = ImageFont.truetype("nor.otf", 42)  # Increased from 36
            cell_font = ImageFont.truetype("nor.otf", 40)  # Increased from 32
            footer_font = ImageFont.truetype("nor.otf", 38)  # New
        except:
            title_font = ImageFont.load_default()
            header_font = ImageFont.load_default()
            cell_font = ImageFont.load_default()
            footer_font = ImageFont.load_default()

        # Draw title
        title_text = f"🏆 {tournament_name} - Points Table"
        title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        draw.text(((width - title_width) // 2, 10), title_text, fill=(0, 0, 0), font=title_font)

        # Column positions
        cols = {
            'pos': 50,
            'flag': 120,
            'team': 200,
            'pts': 650,
            'matches': 750,
            'wins': 850,
            'losses': 950,
            'nrr': 1050,
            'fpp': 1250
        }

        # Draw header row with gradient
        header_y = top_padding + 70  # Moved up
        header_gradient = Image.new('RGB', (width, 60), (0, 0, 0))
        gradient_draw = ImageDraw.Draw(header_gradient)

        for x in range(width):
            progress = x / width
            r = int(41 + (138 - 41) * progress)
            g = int(128 + (43 - 128) * progress)
            b = int(185 + (226 - 185) * progress)
            gradient_draw.line([(x, 0), (x, 60)], fill=(r, g, b))

        img.paste(header_gradient, (0, header_y))

        # Draw header text
        headers = {
            'pos': 'POS',
            'team': 'TEAM',
            'pts': 'PTS',
            'matches': 'M',
            'wins': 'W',
            'losses': 'L',
            'nrr': 'NRR',
            'fpp': 'FPP'
        }

        for key, text in headers.items():
            draw.text((cols[key], header_y + 12), text, fill=(255, 255, 255), font=header_font)

        # Download and cache flags
        flag_cache = {}
        async with aiohttp.ClientSession() as session:
            for idx, (team_name, points, matches, wins, losses, nrr, fpp) in enumerate(teams_data):
                flag_url = get_team_flag_url(team_name)
                if flag_url and team_name not in flag_cache:
                    try:
                        async with session.get(flag_url) as resp:
                            if resp.status == 200:
                                flag_data = await resp.read()
                                flag_img = Image.open(io.BytesIO(flag_data)).convert('RGBA')
                                flag_img = flag_img.resize((55, 55), Image.Resampling.LANCZOS)  # Slightly bigger
                                flag_cache[team_name] = flag_img
                    except:
                        pass

        # Draw team rows
        for idx, (team_name, points, matches, wins, losses, nrr, fpp) in enumerate(teams_data):
            row_y = header_y + 60 + (idx * row_height)

            # Alternate row colors
            if idx % 2 == 0:
                draw.rectangle([(0, row_y), (width, row_y + row_height)], fill=(248, 248, 248))

            # Draw team color GRADIENT BAR on left edge (not just fade)
            team_color = get_team_color_rgb(team_name)
            gradient_width = 12  # Width of gradient bar

            for x in range(gradient_width):
                # Create gradient from dark to light
                progress = x / gradient_width
                for y in range(row_height):
                    # Vertical gradient within the bar
                    y_progress = y / row_height

                    # Mix team color with white for gradient effect
                    r = int(team_color[0] * (1 - progress * 0.3))
                    g = int(team_color[1] * (1 - progress * 0.3))
                    b = int(team_color[2] * (1 - progress * 0.3))

                    # Add vertical fade
                    fade = 1 - (y_progress * 0.2)
                    final_color = (int(r * fade), int(g * fade), int(b * fade))

                    draw.point((x, row_y + y), fill=final_color)

            # Position
            draw.text((cols['pos'], row_y + 25), str(idx + 1), fill=(0, 0, 0), font=cell_font)

            # Flag
            if team_name in flag_cache:
                img.paste(flag_cache[team_name], (cols['flag'], row_y + 18), flag_cache[team_name])

            # Team name
            draw.text((cols['team'], row_y + 25), team_name, fill=(0, 0, 0), font=cell_font)

            # Stats
            draw.text((cols['pts'], row_y + 25), str(points), fill=(0, 128, 0), font=cell_font)
            draw.text((cols['matches'], row_y + 25), str(matches), fill=(0, 0, 0), font=cell_font)
            draw.text((cols['wins'], row_y + 25), str(wins), fill=(0, 0, 0), font=cell_font)
            draw.text((cols['losses'], row_y + 25), str(losses), fill=(0, 0, 0), font=cell_font)

            # NRR with color
            nrr_color = (0, 128, 0) if nrr >= 0 else (255, 0, 0)
            draw.text((cols['nrr'], row_y + 25), f"{nrr:+.3f}", fill=nrr_color, font=cell_font)

            # FPP
            fpp_color = (0, 128, 0) if fpp >= 0 else (255, 128, 0)
            draw.text((cols['fpp'], row_y + 25), f"{fpp:+d}", fill=fpp_color, font=cell_font)

            # Draw divider line
            draw.line([(0, row_y + row_height - 1), (width, row_y + row_height - 1)], fill=(200, 200, 200), width=2)

        # Footer
        footer_y = header_y + 60 + (len(teams_data) * row_height) + 15
        footer_text = "TOP 8 QUALIFY • TourneyFanHub"
        footer_bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
        footer_width = footer_bbox[2] - footer_bbox[0]
        draw.text(((width - footer_width) // 2, footer_y), footer_text, fill=(100, 100, 100), font=footer_font)

        # Convert to bytes
        output = io.BytesIO()
        img.save(output, format='PNG', quality=95)
        output.seek(0)

        return output
    except Exception as e:
        print(f"Error creating points table image: {e}")
        import traceback
        traceback.print_exc()
        return None

def get_played_matchups(tournament_id):
    """Get all matchups that have already been scheduled or reserved"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("""SELECT team1, team2 FROM fixtures 
                WHERE tournament_id = ?""", (tournament_id,))
    matchups = c.fetchall()
    conn.close()

    return {frozenset([t1, t2]) for t1, t2 in matchups}

# Team Selection View
class TeamSelectionView(View):
    def __init__(self, ctx, tournament_name, all_teams):
        super().__init__(timeout=300)
        self.ctx = ctx
        self.tournament_name = tournament_name
        self.selected_teams = []
        self.all_teams = all_teams
        self.message = None

        self.add_team_select()

    def add_team_select(self):
        options = []
        for team in self.all_teams[:25]:
            flag = get_team_flag(team)
            is_selected = team in self.selected_teams
            label = f"{'✅ ' if is_selected else ''}{team}"
            options.append(
                discord.SelectOption(
                    label=label,
                    value=team,
                    emoji=flag,
                    description="Selected" if is_selected else "Click to select"
                )
            )

        select = Select(
            placeholder=f"🏆 Select Teams ({len(self.selected_teams)} selected)",
            options=options,
            custom_id="team_select",
            min_values=0,
            max_values=len(options)  # Allow multiple selections
        )
        select.callback = self.team_callback

        self.clear_items()
        self.add_item(select)
        self.add_item(self.confirm_button)

    async def team_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        selected_values = interaction.data['values']
        self.selected_teams = selected_values

        self.add_team_select()

        embed = discord.Embed(
            title=f"🏆 Creating Tournament: {self.tournament_name}",
            description=f"**Selected Teams ({len(self.selected_teams)}):**\n" + 
                       "\n".join([f"{get_team_flag(t)} {t}" for t in self.selected_teams]) if self.selected_teams else "No teams selected yet.",
            color=0x00FF00
        )
        embed.set_footer(text="Select teams from the dropdown • Click Confirm when done")

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="✅ Confirm Selection", style=discord.ButtonStyle.success, custom_id="confirm")
    async def confirm_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        if len(self.selected_teams) < 2:
            await interaction.response.send_message("❌ You need at least 2 teams for a tournament!", ephemeral=True)
            return

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        try:
            c.execute("UPDATE tournaments SET is_active = 0")
            c.execute("INSERT INTO tournaments (name, current_round) VALUES (?, 0)", (self.tournament_name,))
            tournament_id = c.lastrowid

            for team in self.selected_teams:
                c.execute("""INSERT INTO tournament_teams 
                           (tournament_id, team_name) VALUES (?, ?)""",
                         (tournament_id, team))

            conn.commit()

            embed = discord.Embed(
                title="✅ Tournament Created!",
                description=f"**{self.tournament_name}**\n\n**Participating Teams:**\n" +
                           "\n".join([f"{get_team_flag(t)} {t}" for t in self.selected_teams]),
                color=0x00FF00
            )
            embed.set_footer(text=f"Tournament ID: {tournament_id} • Use -setfixtures to create Round 1 fixtures")

            for item in self.children:
                item.disabled = True

            await interaction.response.edit_message(embed=embed, view=self)

        except sqlite3.IntegrityError:
            await interaction.response.send_message(
                f"❌ A tournament named '{self.tournament_name}' already exists!",
                ephemeral=True
            )
        finally:
            conn.close()

# Fixture Editing View
class FixtureEditView(View):
    def __init__(self, ctx, bot, tournament_id, fixtures, round_number, available_teams):
        super().__init__(timeout=600)
        self.ctx = ctx
        self.bot = bot
        self.tournament_id = tournament_id
        self.fixtures = fixtures  # List of [team1, team2, channel_id, stadium_name]
        self.round_number = round_number
        self.available_teams = available_teams
        self.message = None

        self.add_controls()

    def add_controls(self):
        self.clear_items()

        # Add fixture selection dropdown
        fixture_options = []
        for idx, (team1, team2, channel_id, stadium) in enumerate(self.fixtures):
            flag1 = get_team_flag(team1)
            flag2 = get_team_flag(team2)
            fixture_options.append(
                discord.SelectOption(
                    label=f"{team1} vs {team2}",
                    value=str(idx),
                    emoji="🔄"
                )
            )

        if fixture_options:
            fixture_select = Select(
                placeholder="🔄 Select fixture to edit",
                options=fixture_options,
                custom_id="fixture_select"
            )
            fixture_select.callback = self.fixture_callback
            self.add_item(fixture_select)

        self.add_item(self.confirm_button)

    async def fixture_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        fixture_idx = int(interaction.data['values'][0])

        # Create edit options view
        edit_view = View(timeout=60)

        # Team 1 selection
        team1_options = []
        played_matchups = get_played_matchups(self.tournament_id)
        current_team2 = self.fixtures[fixture_idx][1]

        for team in self.available_teams:
            # Check if this team hasn't played against current team2
            matchup = frozenset([team, current_team2])
            if matchup not in played_matchups or team == self.fixtures[fixture_idx][0]:
                team1_options.append(
                    discord.SelectOption(
                        label=team,
                        value=team,
                        emoji=get_team_flag(team)
                    )
                )

        if team1_options:
            team1_select = Select(
                placeholder="Select Team 1",
                options=team1_options[:25],
                custom_id="team1_select"
            )

            async def team1_callback(inter: discord.Interaction):
                if inter.user.id != self.ctx.author.id:
                    await inter.response.send_message("❌ This is not your menu!", ephemeral=True)
                    return

                new_team1 = inter.data['values'][0]
                self.fixtures[fixture_idx][0] = new_team1

                self.add_controls()
                embed = await self.create_fixture_embed()
                await inter.response.edit_message(embed=embed, view=self)
                await interaction.delete_original_response()

            team1_select.callback = team1_callback
            edit_view.add_item(team1_select)

        # Team 2 selection
        team2_options = []
        current_team1 = self.fixtures[fixture_idx][0]

        for team in self.available_teams:
            matchup = frozenset([current_team1, team])
            if matchup not in played_matchups or team == self.fixtures[fixture_idx][1]:
                team2_options.append(
                    discord.SelectOption(
                        label=team,
                        value=team,
                        emoji=get_team_flag(team)
                    )
                )

        if team2_options:
            team2_select = Select(
                placeholder="Select Team 2",
                options=team2_options[:25],
                custom_id="team2_select"
            )

            async def team2_callback(inter: discord.Interaction):
                if inter.user.id != self.ctx.author.id:
                    await inter.response.send_message("❌ This is not your menu!", ephemeral=True)
                    return

                new_team2 = inter.data['values'][0]
                self.fixtures[fixture_idx][1] = new_team2

                self.add_controls()
                embed = await self.create_fixture_embed()
                await inter.response.edit_message(embed=embed, view=self)
                await interaction.delete_original_response()

            team2_select.callback = team2_callback
            edit_view.add_item(team2_select)

        # Stadium selection
        stadium_options = []
        for channel_id, stadium_name in MATCH_CHANNELS.items():
            stadium_options.append(
                discord.SelectOption(
                    label=stadium_name,
                    value=str(channel_id),
                    emoji="🏟️"
                )
            )

        stadium_select = Select(
            placeholder="Select Stadium",
            options=stadium_options,
            custom_id="stadium_select"
        )

        async def stadium_callback(inter: discord.Interaction):
            if inter.user.id != self.ctx.author.id:
                await inter.response.send_message("❌ This is not your menu!", ephemeral=True)
                return

            new_channel_id = int(inter.data['values'][0])
            new_stadium = MATCH_CHANNELS[new_channel_id]
            self.fixtures[fixture_idx][2] = new_channel_id
            self.fixtures[fixture_idx][3] = new_stadium

            self.add_controls()
            embed = await self.create_fixture_embed()
            await inter.response.edit_message(embed=embed, view=self)
            await interaction.delete_original_response()

        stadium_select.callback = stadium_callback
        edit_view.add_item(stadium_select)

        await interaction.response.send_message(
            f"Editing fixture {fixture_idx + 1}:",
            view=edit_view,
            ephemeral=True
        )

    async def create_fixture_embed(self):
        tournament = get_active_tournament()
        tournament_name = tournament[1] if tournament else "Tournament"

        embed = discord.Embed(
            title=f"🏆 {tournament_name} - Round {self.round_number} Fixtures",
            description=f"**Total Matches:** {len(self.fixtures)}\n\n**Fixture List:**",
            color=0x0066CC
        )

        fixture_text = ""
        for idx, (team1, team2, channel_id, stadium) in enumerate(self.fixtures, 1):
            flag1 = get_team_flag(team1)
            flag2 = get_team_flag(team2)
            fixture_text += f"**{idx}.** {flag1} {team1} vs {flag2} {team2}\n    🏟️ {stadium}\n\n"

        embed.description += f"\n{fixture_text}"
        embed.set_footer(text="Select fixture to edit teams/stadium • Click Confirm when ready")

        return embed

    @discord.ui.button(label="✅ Confirm & Post Fixtures", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        await interaction.response.defer()

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        for team1, team2, channel_id, stadium in self.fixtures:
            c.execute("""INSERT INTO fixtures 
                       (tournament_id, round_number, team1, team2, channel_id)
                       VALUES (?, ?, ?, ?, ?)""",
                     (self.tournament_id, self.round_number, team1, team2, channel_id))

        c.execute("UPDATE tournaments SET current_round = ? WHERE id = ?",
                 (self.round_number, self.tournament_id))

        conn.commit()
        conn.close()

        await self.post_fixtures()

        for item in self.children:
            item.disabled = True

        await self.message.edit(view=self)
        await interaction.followup.send("✅ Fixtures confirmed and posted!")

    async def post_fixtures(self):
        guild = self.ctx.guild
        fixtures_channel = guild.get_channel(FIXTURES_CHANNEL)

        if not fixtures_channel:
            print(f"❌ Fixtures channel {FIXTURES_CHANNEL} not found!")
            return

        tournament = get_active_tournament()
        tournament_name = tournament[1] if tournament else "Tournament"

        for team1, team2, channel_id, stadium in self.fixtures:
            vs_image = await create_vs_image(team1, team2, stadium)

            embed = discord.Embed(
                title=f"🏏 {tournament_name} - Round {self.round_number}",
                color=0x00FF00
            )

            flag1 = get_team_flag(team1)
            flag2 = get_team_flag(team2)

            embed.add_field(
                name="Match",
                value=f"{flag1} **{team1}** vs {flag2} **{team2}**",
                inline=False
            )

            # Link to the stadium channel
            embed.add_field(
                name="Stadium",
                value=f"🏟️ <#{channel_id}>",
                inline=False
            )

            embed.set_footer(text="TourneyFanHub")

            role1_id = get_team_role_id(team1)
            role2_id = get_team_role_id(team2)

            ping_text = ""
            if role1_id:
                ping_text += f"<@&{role1_id}> "
            if role2_id:
                ping_text += f"<@&{role2_id}> "

            if vs_image:
                file = discord.File(vs_image, filename=f"{team1}_vs_{team2}.png")
                embed.set_image(url=f"attachment://{team1}_vs_{team2}.png")

                if ping_text:
                    await fixtures_channel.send(content=ping_text, embed=embed, file=file)
                else:
                    await fixtures_channel.send(embed=embed, file=file)
            else:
                if ping_text:
                    await fixtures_channel.send(content=ping_text, embed=embed)
                else:
                    await fixtures_channel.send(embed=embed)

class Tournament(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        init_tournament_db()

    @commands.command(name="createtournament", aliases=["ct"], help="[ADMIN] Create a new tournament")
    @commands.has_permissions(administrator=True)
    async def createtournament(self, ctx, *, tournament_name: str):
        import json
        try:
            with open('players.json', 'r', encoding='utf-8') as f:
                teams_data = json.load(f)
                all_teams = [team['team'] for team in teams_data]
        except FileNotFoundError:
            await ctx.send("❌ players.json not found!")
            return

        embed = discord.Embed(
            title=f"🏆 Creating Tournament: {tournament_name}",
            description="Select the teams that will participate in this tournament.",
            color=0x0066CC
        )
        embed.set_footer(text="Select multiple teams from the dropdown below")

        view = TeamSelectionView(ctx, tournament_name, all_teams)
        view.message = await ctx.send(embed=embed, view=view)

    @commands.command(name="pts", aliases=["points", "pointstable"], help="View tournament points table")
    async def points_table(self, ctx):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, current_round = tournament

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("""SELECT team_name, points, matches_played, wins, losses, nrr, fpp
                    FROM tournament_teams 
                    WHERE tournament_id = ?
                    ORDER BY points DESC, nrr DESC""", (tournament_id,))
        teams = c.fetchall()
        conn.close()

        if not teams:
            await ctx.send("❌ No teams found in the tournament!")
            return

        # Create points table image
        table_image = await create_points_table_image(tournament_name, teams)

        if not table_image:
            await ctx.send("❌ Failed to create points table image!")
            return

        file = discord.File(table_image, filename="points_table.png")

        embed = discord.Embed(
            title=f"🏆 {tournament_name}",
            color=0xFFD700
        )
        embed.set_image(url="attachment://points_table.png")
        embed.set_footer(text="TourneyFanHub")

        await ctx.send(embed=embed, file=file)

    @commands.command(name="fixturemake", aliases=["fm"], help="[ADMIN] Manually create a single fixture")
    @commands.has_permissions(administrator=True)
    async def fixturemake(self, ctx, team1: str, team2: str):
        """Manually create a fixture between two teams for the next round"""

        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, current_round = tournament
        next_round = current_round + 1

        # Verify both teams are in the tournament
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        c.execute("SELECT team_name FROM tournament_teams WHERE tournament_id = ? AND team_name IN (?, ?)",
                 (tournament_id, team1, team2))
        found_teams = [row[0] for row in c.fetchall()]

        if len(found_teams) != 2:
            missing = [t for t in [team1, team2] if t not in found_teams]
            await ctx.send(f"❌ Team(s) not found in tournament: {', '.join(missing)}")
            conn.close()
            return

        # Check if this matchup already exists
        c.execute("""SELECT id FROM fixtures 
                    WHERE tournament_id = ? 
                    AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))""",
                 (tournament_id, team1, team2, team2, team1))

        if c.fetchone():
            await ctx.send(f"❌ A fixture between {team1} and {team2} already exists!")
            conn.close()
            return

        # Assign a random stadium
        channel_id = random.choice(list(MATCH_CHANNELS.keys()))
        stadium = MATCH_CHANNELS[channel_id]

        # Create the fixture
        c.execute("""INSERT INTO fixtures 
                   (tournament_id, round_number, team1, team2, channel_id)
                   VALUES (?, ?, ?, ?, ?)""",
                 (tournament_id, next_round, team1, team2, channel_id))

        # Update tournament round if this is the first fixture for this round
        c.execute("SELECT COUNT(*) FROM fixtures WHERE tournament_id = ? AND round_number = ?",
                 (tournament_id, next_round))
        fixture_count = c.fetchone()[0]

        if fixture_count == 1:  # First fixture of this round
            c.execute("UPDATE tournaments SET current_round = ? WHERE id = ?",
                     (next_round, tournament_id))

        conn.commit()
        conn.close()

        # Create and post the fixture
        vs_image = await create_vs_image(team1, team2, stadium)

        embed = discord.Embed(
            title=f"🏏 {tournament_name} - Round {next_round}",
            color=0x00FF00
        )

        flag1 = get_team_flag(team1)
        flag2 = get_team_flag(team2)

        embed.add_field(
            name="Match",
            value=f"{flag1} **{team1}** vs {flag2} **{team2}**",
            inline=False
        )

        embed.add_field(
            name="Stadium",
            value=f"🏟️ <#{channel_id}>",
            inline=False
        )

        embed.set_footer(text="TourneyFanHub")

        # Post to fixtures channel
        fixtures_channel = ctx.guild.get_channel(FIXTURES_CHANNEL)
        if fixtures_channel:
            role1_id = get_team_role_id(team1)
            role2_id = get_team_role_id(team2)

            ping_text = ""
            if role1_id:
                ping_text += f"<@&{role1_id}> "
            if role2_id:
                ping_text += f"<@&{role2_id}> "

            if vs_image:
                file = discord.File(vs_image, filename=f"{team1}_vs_{team2}.png")
                embed.set_image(url=f"attachment://{team1}_vs_{team2}.png")

                if ping_text:
                    await fixtures_channel.send(content=ping_text, embed=embed, file=file)
                else:
                    await fixtures_channel.send(embed=embed, file=file)
            else:
                if ping_text:
                    await fixtures_channel.send(content=ping_text, embed=embed)
                else:
                    await fixtures_channel.send(embed=embed)

        await ctx.send(f"✅ Fixture created: **{team1}** vs **{team2}** (Round {next_round})")

    @commands.command(name="setfixtures", aliases=["sf"], help="[ADMIN] Generate tournament fixtures")
    @commands.has_permissions(administrator=True)
    async def setfixtures(self, ctx):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, current_round = tournament
        next_round = current_round + 1

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("SELECT team_name FROM tournament_teams WHERE tournament_id = ?", (tournament_id,))
        all_teams = [row[0] for row in c.fetchall()]

        # Get teams that already have fixtures in this round (from manual fixtures)
        c.execute("""SELECT DISTINCT team1, team2 FROM fixtures 
                    WHERE tournament_id = ? AND round_number = ?""",
                 (tournament_id, next_round))
        existing_fixtures = c.fetchall()
        conn.close()

        teams_with_fixtures = set()
        for t1, t2 in existing_fixtures:
            teams_with_fixtures.add(t1)
            teams_with_fixtures.add(t2)

        if len(teams_with_fixtures) < len(all_teams):
            # There are teams without fixtures, continue generating
            available_teams = [t for t in all_teams if t not in teams_with_fixtures]

            if len(available_teams) < 2:
                await ctx.send("✅ All teams already have fixtures for this round!")
                return

            played_matchups = get_played_matchups(tournament_id)
            fixtures = []

            random.shuffle(available_teams)

            # Maximum 6 matches per round
            max_matches = 6 - len(existing_fixtures)
            matches_created = 0

            while len(available_teams) >= 2 and matches_created < max_matches:
                team1 = available_teams[0]
                matched = False

                for i in range(1, len(available_teams)):
                    team2 = available_teams[i]
                    matchup = frozenset([team1, team2])

                    if matchup not in played_matchups:
                        channel_id = random.choice(list(MATCH_CHANNELS.keys()))
                        stadium = MATCH_CHANNELS[channel_id]
                        fixtures.append([team1, team2, channel_id, stadium])

                        available_teams.remove(team1)
                        available_teams.remove(team2)
                        matches_created += 1
                        matched = True
                        break

                if not matched:
                    available_teams.remove(team1)

            if not fixtures:
                if existing_fixtures:
                    await ctx.send("✅ Manual fixtures already created for this round!")
                else:
                    await ctx.send("✅ All possible matchups have been played!")
                return

            embed = await FixtureEditView(ctx, self.bot, tournament_id, fixtures, next_round, all_teams).create_fixture_embed()
            view = FixtureEditView(ctx, self.bot, tournament_id, fixtures, next_round, all_teams)
            view.message = await ctx.send(embed=embed, view=view)
        else:
            await ctx.send("✅ All teams already have fixtures for this round!")

    @commands.command(name="setfpp", help="[ADMIN] Set FPP for a team")
    @commands.has_permissions(administrator=True)
    async def setfpp(self, ctx, team_name: str, fpp_change: int):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id = tournament[0]

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        c.execute("""UPDATE tournament_teams 
                    SET fpp = fpp + ?
                    WHERE tournament_id = ? AND team_name = ?""",
                 (fpp_change, tournament_id, team_name))

        if c.rowcount == 0:
            await ctx.send(f"❌ Team '{team_name}' not found in the tournament!")
            conn.close()
            return

        conn.commit()

        c.execute("SELECT fpp FROM tournament_teams WHERE tournament_id = ? AND team_name = ?",
                 (tournament_id, team_name))
        new_fpp = c.fetchone()[0]
        conn.close()

        flag = get_team_flag(team_name)
        embed = discord.Embed(
            title="✅ FPP Updated",
            description=f"{flag} **{team_name}**\n\nFPP Change: **{fpp_change:+d}**\nNew FPP: **{new_fpp:+d}**",
            color=get_team_color(team_name)
        )

        await ctx.send(embed=embed)

    @commands.command(name="reservematch", aliases=["rm"], help="[ADMIN] Mark a match as reserved")
    @commands.has_permissions(administrator=True)
    async def reservematch(self, ctx, team1: str, team2: str):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id = tournament[0]

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        c.execute("""SELECT id FROM fixtures 
                    WHERE tournament_id = ? 
                    AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))
                    AND is_played = 0""",
                 (tournament_id, team1, team2, team2, team1))

        fixture = c.fetchone()

        if not fixture:
            await ctx.send(f"❌ No unplayed fixture found between {team1} and {team2}!")
            conn.close()
            return

        fixture_id = fixture[0]

        c.execute("UPDATE fixtures SET is_reserved = 1 WHERE id = ?", (fixture_id,))
        conn.commit()
        conn.close()

        flag1 = get_team_flag(team1)
        flag2 = get_team_flag(team2)

        embed = discord.Embed(
            title="📌 Match Reserved",
            description=f"{flag1} **{team1}** vs {flag2} **{team2}**\n\nThis match will be played later.",
            color=0xFFA500
        )

        await ctx.send(embed=embed)

    @commands.command(name="reserves", help="View all reserved matches")
    async def reserves(self, ctx):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, _ = tournament

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("""SELECT team1, team2, round_number, channel_id
                    FROM fixtures 
                    WHERE tournament_id = ? AND is_reserved = 1 AND is_played = 0""",
                 (tournament_id,))
        reserved = c.fetchall()
        conn.close()

        if not reserved:
            await ctx.send("✅ No reserved matches!")
            return

        embed = discord.Embed(
            title=f"📌 {tournament_name} - Reserved Matches",
            color=0xFFA500
        )

        for team1, team2, round_num, channel_id in reserved:
            flag1 = get_team_flag(team1)
            flag2 = get_team_flag(team2)
            stadium = MATCH_CHANNELS.get(channel_id, "Unknown Stadium")

            embed.add_field(
                name=f"Round {round_num}",
                value=f"{flag1} **{team1}** vs {flag2} **{team2}**\n🏟️ {stadium}",
                inline=False
            )

        await ctx.send(embed=embed)

    @commands.command(name="unreserve", help="[ADMIN] Remove reserve status from a match")
    @commands.has_permissions(administrator=True)
    async def unreserve(self, ctx, team1: str, team2: str):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id = tournament[0]

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        c.execute("""UPDATE fixtures SET is_reserved = 0
                    WHERE tournament_id = ? 
                    AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))
                    AND is_reserved = 1""",
                 (tournament_id, team1, team2, team2, team1))

        if c.rowcount == 0:
            await ctx.send(f"❌ No reserved match found between {team1} and {team2}!")
            conn.close()
            return

        conn.commit()
        conn.close()

        await ctx.send(f"✅ Match between **{team1}** and **{team2}** is no longer reserved!")

    @commands.command(name="deletetournament", aliases=["dt"], help="[ADMIN] Delete the current tournament")
    @commands.has_permissions(administrator=True)
    async def deletetournament(self, ctx):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, _ = tournament

        embed = discord.Embed(
            title="⚠️ Delete Tournament?",
            description=f"Are you sure you want to delete **{tournament_name}**?\n\n"
                       "This will delete:\n"
                       "• All team data\n"
                       "• All fixtures\n"
                       "• All points and statistics\n\n"
                       "**This action cannot be undone!**",
            color=0xFF0000
        )

        view = View(timeout=60)

        async def confirm_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("❌ Only the command author can confirm!", ephemeral=True)
                return

            conn = sqlite3.connect('players.db')
            c = conn.cursor()

            c.execute("DELETE FROM fixtures WHERE tournament_id = ?", (tournament_id,))
            c.execute("DELETE FROM tournament_teams WHERE tournament_id = ?", (tournament_id,))
            c.execute("DELETE FROM tournaments WHERE id = ?", (tournament_id,))

            conn.commit()
            conn.close()

            await interaction.response.edit_message(
                content=f"✅ Tournament **{tournament_name}** has been deleted!",
                embed=None,
                view=None
            )

        async def cancel_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("❌ Only the command author can cancel!", ephemeral=True)
                return

            await interaction.response.edit_message(
                content="❌ Tournament deletion cancelled.",
                embed=None,
                view=None
            )

        confirm_btn = Button(label="✅ Confirm Delete", style=discord.ButtonStyle.danger)
        cancel_btn = Button(label="❌ Cancel", style=discord.ButtonStyle.secondary)

        confirm_btn.callback = confirm_callback
        cancel_btn.callback = cancel_callback

        view.add_item(confirm_btn)
        view.add_item(cancel_btn)

        await ctx.send(embed=embed, view=view)

    @commands.command(name="clearfixtures", aliases=["cf"], help="[ADMIN] Clear all fixtures")
    @commands.has_permissions(administrator=True)
    async def clearfixtures(self, ctx):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id = tournament[0]

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("DELETE FROM fixtures WHERE tournament_id = ?", (tournament_id,))
        deleted = c.rowcount

        c.execute("UPDATE tournaments SET current_round = 0 WHERE id = ?", (tournament_id,))

        conn.commit()
        conn.close()

        await ctx.send(f"✅ Cleared **{deleted}** fixtures and reset tournament to Round 0!")

async def setup(bot):
    await bot.add_cog(Tournament(bot))