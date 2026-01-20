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
        return f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/svg/{code}.svg"
    return None

def get_team_role_id(team_name):
    """Get role ID for a team"""
    # TODO: Add actual role IDs for each team
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

async def create_vs_image(team1, team2, stadium_name):
    """Create a VS image with team flags and stadium name"""
    try:
        # Load the background
        bg = Image.open("overlap.png").convert('RGBA')
        width, height = bg.size

        # Create a copy to draw on
        img = bg.copy()
        draw = ImageDraw.Draw(img, 'RGBA')

        # Get team colors
        color1 = get_team_color_rgb(team1)
        color2 = get_team_color_rgb(team2)

        # Create gradient overlays for left and right sides
        # Left side gradient (team1 color)
        for x in range(width // 2):
            alpha = int(200 * (1 - x / (width // 2)))  # Fade from 200 to 0
            for y in range(height):
                draw.point((x, y), fill=color1 + (alpha,))

        # Right side gradient (team2 color)
        for x in range(width // 2, width):
            alpha = int(200 * ((x - width // 2) / (width // 2)))  # Fade from 0 to 200
            for y in range(height):
                draw.point((x, y), fill=color2 + (alpha,))

        # Download and paste team flags
        async with aiohttp.ClientSession() as session:
            # Left flag (team1)
            flag1_url = get_team_flag_url(team1)
            if flag1_url:
                try:
                    async with session.get(flag1_url) as resp:
                        if resp.status == 200:
                            flag_data = await resp.read()
                            flag1 = Image.open(io.BytesIO(flag_data)).convert('RGBA')
                            flag1 = flag1.resize((300, 300), Image.Resampling.LANCZOS)

                            # Paste left flag
                            flag1_x = width // 4 - 150
                            flag1_y = height // 2 - 150
                            img.paste(flag1, (flag1_x, flag1_y), flag1)
                except:
                    pass

            # Right flag (team2)
            flag2_url = get_team_flag_url(team2)
            if flag2_url:
                try:
                    async with session.get(flag2_url) as resp:
                        if resp.status == 200:
                            flag_data = await resp.read()
                            flag2 = Image.open(io.BytesIO(flag_data)).convert('RGBA')
                            flag2 = flag2.resize((300, 300), Image.Resampling.LANCZOS)

                            # Paste right flag
                            flag2_x = 3 * width // 4 - 150
                            flag2_y = height // 2 - 150
                            img.paste(flag2, (flag2_x, flag2_y), flag2)
                except:
                    pass

        # Add VS text in center
        try:
            font_large = ImageFont.truetype("arial.ttf", 180)
        except:
            font_large = ImageFont.load_default()

        vs_text = "VS"
        vs_bbox = draw.textbbox((0, 0), vs_text, font=font_large)
        vs_width = vs_bbox[2] - vs_bbox[0]
        vs_height = vs_bbox[3] - vs_bbox[1]
        vs_x = (width - vs_width) // 2
        vs_y = (height - vs_height) // 2 - 50

        # Draw VS with outline
        for offset_x in [-3, 0, 3]:
            for offset_y in [-3, 0, 3]:
                draw.text((vs_x + offset_x, vs_y + offset_y), vs_text, font=font_large, fill=(0, 0, 0, 255))
        draw.text((vs_x, vs_y), vs_text, font=font_large, fill=(255, 255, 255, 255))

        # Add stadium name below VS
        try:
            font_small = ImageFont.truetype("arial.ttf", 40)
        except:
            font_small = ImageFont.load_default()

        stadium_bbox = draw.textbbox((0, 0), stadium_name, font=font_small)
        stadium_width = stadium_bbox[2] - stadium_bbox[0]
        stadium_x = (width - stadium_width) // 2
        stadium_y = vs_y + vs_height + 20

        # Draw stadium name with outline
        for offset_x in [-2, 0, 2]:
            for offset_y in [-2, 0, 2]:
                draw.text((stadium_x + offset_x, stadium_y + offset_y), stadium_name, font=font_small, fill=(0, 0, 0, 255))
        draw.text((stadium_x, stadium_y), stadium_name, font=font_small, fill=(255, 255, 255, 255))

        # Convert to bytes
        output = io.BytesIO()
        img = img.convert('RGB')
        img.save(output, format='PNG', quality=95)
        output.seek(0)

        return output
    except Exception as e:
        print(f"Error creating VS image: {e}")
        return None

def get_played_matchups(tournament_id):
    """Get all matchups that have already been scheduled or reserved"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("""SELECT team1, team2 FROM fixtures 
                WHERE tournament_id = ?""", (tournament_id,))
    matchups = c.fetchall()
    conn.close()

    # Create a set of frozensets for easy lookup (order doesn't matter)
    return {frozenset([t1, t2]) for t1, t2 in matchups}

def has_team_played_this_round(tournament_id, round_number, team_name):
    """Check if a team already has a fixture in this round"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("""SELECT COUNT(*) FROM fixtures 
                WHERE tournament_id = ? AND round_number = ? 
                AND (team1 = ? OR team2 = ?)""",
             (tournament_id, round_number, team_name, team_name))
    count = c.fetchone()[0]
    conn.close()
    return count > 0

# Team Selection View
class TeamSelectionView(View):
    def __init__(self, ctx, tournament_name, all_teams):
        super().__init__(timeout=300)
        self.ctx = ctx
        self.tournament_name = tournament_name
        self.selected_teams = []
        self.all_teams = all_teams
        self.message = None

        # Add team selection dropdown
        self.add_team_select()

    def add_team_select(self):
        options = []
        for team in self.all_teams[:25]:  # Discord limit
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
            min_values=1,
            max_values=1
        )
        select.callback = self.team_callback

        # Clear existing selects and add new one
        self.clear_items()
        self.add_item(select)
        self.add_item(self.confirm_button)

    async def team_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        selected = interaction.data['values'][0]

        if selected in self.selected_teams:
            self.selected_teams.remove(selected)
        else:
            self.selected_teams.append(selected)

        # Update the view
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

        # Create tournament in database
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        try:
            # Deactivate any existing active tournaments
            c.execute("UPDATE tournaments SET is_active = 0")

            # Create new tournament
            c.execute("INSERT INTO tournaments (name, current_round) VALUES (?, 0)", (self.tournament_name,))
            tournament_id = c.lastrowid

            # Add teams
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

            # Disable all buttons
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

# Fixture Swap View
class FixtureSwapView(View):
    def __init__(self, ctx, bot, tournament_id, fixtures, round_number):
        super().__init__(timeout=600)
        self.ctx = ctx
        self.bot = bot
        self.tournament_id = tournament_id
        self.fixtures = fixtures  # List of (team1, team2, channel_id, stadium_name)
        self.round_number = round_number
        self.message = None

        # Add swap select
        self.add_swap_select()

    def add_swap_select(self):
        # Clear existing items
        self.clear_items()

        # Add fixture selection dropdown for swapping
        options = []
        for idx, (team1, team2, channel_id, stadium) in enumerate(self.fixtures):
            flag1 = get_team_flag(team1)
            flag2 = get_team_flag(team2)
            options.append(
                discord.SelectOption(
                    label=f"{team1} vs {team2}",
                    value=str(idx),
                    description=stadium,
                    emoji="🔄"
                )
            )

        if options:
            select = Select(
                placeholder="🔄 Select fixture to swap stadium",
                options=options,
                custom_id="swap_select",
                min_values=1,
                max_values=1
            )
            select.callback = self.swap_callback
            self.add_item(select)

        # Add confirm button
        self.add_item(self.confirm_button)

    async def swap_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        fixture_idx = int(interaction.data['values'][0])

        # Show stadium selection
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
            placeholder="🏟️ Select new stadium",
            options=stadium_options,
            custom_id="stadium_select"
        )

        async def stadium_callback(inter: discord.Interaction):
            if inter.user.id != self.ctx.author.id:
                await inter.response.send_message("❌ This is not your menu!", ephemeral=True)
                return

            new_channel_id = int(inter.data['values'][0])
            new_stadium = MATCH_CHANNELS[new_channel_id]

            # Update fixture
            team1, team2, old_channel, old_stadium = self.fixtures[fixture_idx]
            self.fixtures[fixture_idx] = (team1, team2, new_channel_id, new_stadium)

            # Refresh view
            self.add_swap_select()

            embed = await self.create_fixture_embed()
            await inter.response.edit_message(embed=embed, view=self)

        stadium_select.callback = stadium_callback

        temp_view = View(timeout=60)
        temp_view.add_item(stadium_select)

        await interaction.response.send_message(
            "Select the new stadium for this fixture:",
            view=temp_view,
            ephemeral=True
        )

    async def create_fixture_embed(self):
        """Create embed showing current fixtures"""
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
        embed.set_footer(text="Use dropdown to swap stadiums • Click Confirm when ready")

        return embed

    @discord.ui.button(label="✅ Confirm & Post Fixtures", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        await interaction.response.defer()

        # Save fixtures to database
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        for team1, team2, channel_id, stadium in self.fixtures:
            c.execute("""INSERT INTO fixtures 
                       (tournament_id, round_number, team1, team2, channel_id)
                       VALUES (?, ?, ?, ?, ?)""",
                     (self.tournament_id, self.round_number, team1, team2, channel_id))

        # Update tournament round
        c.execute("UPDATE tournaments SET current_round = ? WHERE id = ?",
                 (self.round_number, self.tournament_id))

        conn.commit()
        conn.close()

        # Post fixtures to announcement channel
        await self.post_fixtures()

        # Disable buttons
        for item in self.children:
            item.disabled = True

        await self.message.edit(view=self)
        await interaction.followup.send("✅ Fixtures confirmed and posted!")

    async def post_fixtures(self):
        """Post fixtures to the fixtures announcement channel"""
        guild = self.ctx.guild
        fixtures_channel = guild.get_channel(FIXTURES_CHANNEL)

        if not fixtures_channel:
            print(f"❌ Fixtures channel {FIXTURES_CHANNEL} not found!")
            return

        tournament = get_active_tournament()
        tournament_name = tournament[1] if tournament else "Tournament"

        # Post each fixture
        for team1, team2, channel_id, stadium in self.fixtures:
            # Create VS image
            vs_image = await create_vs_image(team1, team2, stadium)

            # Create embed
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

            embed.add_field(
                name="Stadium",
                value=f"🏟️ {stadium}",
                inline=False
            )

            embed.set_footer(text=f"Round {self.round_number}")
            embed.timestamp = discord.utils.utcnow()

            # Get team roles and ping them
            role1_id = get_team_role_id(team1)
            role2_id = get_team_role_id(team2)

            ping_text = ""
            if role1_id:
                ping_text += f"<@&{role1_id}> "
            if role2_id:
                ping_text += f"<@&{role2_id}> "

            # If no VS image, just send embed
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
        """Create a new tournament and select participating teams"""

        # Load all available teams from players.json
        import json
        try:
            with open('players.json', 'r', encoding='utf-8') as f:
                teams_data = json.load(f)
                all_teams = [team['team'] for team in teams_data]
        except FileNotFoundError:
            await ctx.send("❌ players.json not found!")
            return

        # Create team selection view
        embed = discord.Embed(
            title=f"🏆 Creating Tournament: {tournament_name}",
            description="Select the teams that will participate in this tournament.",
            color=0x0066CC
        )
        embed.set_footer(text="Select teams from the dropdown below")

        view = TeamSelectionView(ctx, tournament_name, all_teams)
        view.message = await ctx.send(embed=embed, view=view)

    @commands.command(name="pts", aliases=["points", "pointstable"], help="View tournament points table")
    async def points_table(self, ctx):
        """Display the current tournament points table"""

        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, current_round = tournament

        # Get all teams with their stats
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

        # Create embed
        embed = discord.Embed(
            title=f"🏆 {tournament_name} - Points Table",
            color=0xFFD700
        )

        # Create table
        table = "```\n"
        table += "POS  TEAM              PT  M  W  L   NRR    FPP\n"
        table += "═" * 50 + "\n"

        for idx, (team_name, points, matches, wins, losses, nrr, fpp) in enumerate(teams, 1):
            team_display = team_name[:15].ljust(15)
            table += f"{idx:2d}   {team_display}  {points:2d}  {matches:2d} {wins:2d} {losses:2d}  {nrr:+.3f}  {fpp:+2d}\n"

        table += "```"

        embed.description = table
        embed.set_footer(text="TOP 8 QUALIFY")
        embed.timestamp = discord.utils.utcnow()

        await ctx.send(embed=embed)

    @commands.command(name="setfixtures", aliases=["sf"], help="[ADMIN] Generate tournament fixtures")
    @commands.has_permissions(administrator=True)
    async def setfixtures(self, ctx):
        """Generate fixtures for the next round"""

        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, current_round = tournament
        next_round = current_round + 1

        # Get all teams
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("SELECT team_name FROM tournament_teams WHERE tournament_id = ?", (tournament_id,))
        teams = [row[0] for row in c.fetchall()]
        conn.close()

        if len(teams) < 2:
            await ctx.send("❌ Need at least 2 teams to generate fixtures!")
            return

        # Get all matchups that have been played or scheduled
        played_matchups = get_played_matchups(tournament_id)

        # Find available teams for this round
        available_teams = teams.copy()
        fixtures = []

        # Try to create fixtures
        random.shuffle(available_teams)

        while len(available_teams) >= 2:
            team1 = available_teams[0]
            matched = False

            for i in range(1, len(available_teams)):
                team2 = available_teams[i]
                matchup = frozenset([team1, team2])

                # Check if this matchup hasn't been scheduled before
                if matchup not in played_matchups:
                    # Assign a random stadium
                    channel_id = random.choice(list(MATCH_CHANNELS.keys()))
                    stadium = MATCH_CHANNELS[channel_id]
                    fixtures.append((team1, team2, channel_id, stadium))

                    # Remove both teams from available
                    available_teams.remove(team1)
                    available_teams.remove(team2)
                    matched = True
                    break

            if not matched:
                # Can't find a match for this team
                available_teams.remove(team1)

        if not fixtures:
            await ctx.send("✅ All teams have already played against each other! Tournament complete.")
            return

        # Show fixtures for confirmation/swapping
        embed = discord.Embed(
            title=f"🏆 {tournament_name} - Round {next_round} Fixtures",
            description=f"**Total Matches:** {len(fixtures)}\n\n**Fixture List:**",
            color=0x0066CC
        )

        fixture_text = ""
        for idx, (team1, team2, channel_id, stadium) in enumerate(fixtures, 1):
            flag1 = get_team_flag(team1)
            flag2 = get_team_flag(team2)
            fixture_text += f"**{idx}.** {flag1} {team1} vs {flag2} {team2}\n    🏟️ {stadium}\n\n"

        embed.description += f"\n{fixture_text}"
        embed.set_footer(text="Use dropdown to swap stadiums • Click Confirm when ready")

        # Create swap view
        view = FixtureSwapView(ctx, self.bot, tournament_id, fixtures, next_round)
        view.message = await ctx.send(embed=embed, view=view)

    @commands.command(name="setfpp", help="[ADMIN] Set FPP for a team")
    @commands.has_permissions(administrator=True)
    async def setfpp(self, ctx, team_name: str, fpp_change: int):
        """Manually adjust FPP (Fair Play Points) for a team"""

        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id = tournament[0]

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Update FPP
        c.execute("""UPDATE tournament_teams 
                    SET fpp = fpp + ?
                    WHERE tournament_id = ? AND team_name = ?""",
                 (fpp_change, tournament_id, team_name))

        if c.rowcount == 0:
            await ctx.send(f"❌ Team '{team_name}' not found in the tournament!")
            conn.close()
            return

        conn.commit()

        # Get new FPP value
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
        """Mark a match as reserved (to be played later)"""

        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id = tournament[0]

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Find the fixture
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

        # Mark as reserved
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
        """View all reserved matches in the tournament"""

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
        """Remove reserve status from a match"""

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
        """Delete all data for the current tournament"""

        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, _ = tournament

        # Confirmation
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

            # Delete all related data
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
        """Clear all fixtures for the current tournament"""

        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id = tournament[0]

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("DELETE FROM fixtures WHERE tournament_id = ?", (tournament_id,))
        deleted = c.rowcount

        # Reset current round
        c.execute("UPDATE tournaments SET current_round = 0 WHERE id = ?", (tournament_id,))

        conn.commit()
        conn.close()

        await ctx.send(f"✅ Cleared **{deleted}** fixtures and reset tournament to Round 0!")
        
async def setup(bot):
    await bot.add_cog(Tournament(bot))