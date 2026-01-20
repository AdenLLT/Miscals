import discord
import sqlite3
import random
from discord.ext import commands
from discord.ui import View, Button, Select
from typing import List, Optional

def init_tournament_db():
    """Initialize tournament database tables"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Tournament table
    c.execute('''CREATE TABLE IF NOT EXISTS tournaments
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT UNIQUE,
                  is_active INTEGER DEFAULT 1,
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

# Available match channels
MATCH_CHANNELS = [
    1463142319770566727,
    1463210854614044784,
    1463211266234519708,
    1463211462011916308,
    1463211835061829704,
    1463233771007512691
]

def get_active_tournament():
    """Get the currently active tournament"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT id, name FROM tournaments WHERE is_active = 1 LIMIT 1")
    result = c.fetchone()
    conn.close()
    return result

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
    """Get role ID for a team (you'll need to add actual role IDs)"""
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
            c.execute("INSERT INTO tournaments (name) VALUES (?)", (self.tournament_name,))
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
            embed.set_footer(text=f"Tournament ID: {tournament_id} • Use -setfixtures to create the fixture schedule")

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

# Fixture Modification View
class FixtureModificationView(View):
    def __init__(self, ctx, tournament_id, fixtures, round_number):
        super().__init__(timeout=600)
        self.ctx = ctx
        self.tournament_id = tournament_id
        self.fixtures = fixtures  # List of (team1, team2, channel_id)
        self.round_number = round_number
        self.message = None

    @discord.ui.button(label="✅ Confirm & Post Fixtures", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        await interaction.response.defer()

        # Save fixtures to database
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        for team1, team2, channel_id in self.fixtures:
            c.execute("""INSERT INTO fixtures 
                       (tournament_id, round_number, team1, team2, channel_id)
                       VALUES (?, ?, ?, ?, ?)""",
                     (self.tournament_id, self.round_number, team1, team2, channel_id))

        conn.commit()
        conn.close()

        # Post fixtures to channels
        await self.post_fixtures()

        # Disable button
        button.disabled = True
        await interaction.message.edit(view=self)

        await interaction.followup.send("✅ Fixtures confirmed and posted to channels!")

    async def post_fixtures(self):
        """Post fixtures to their respective channels"""
        guild = self.ctx.guild

        for team1, team2, channel_id in self.fixtures:
            channel = guild.get_channel(channel_id)
            if not channel:
                continue

            # Create fixture embed
            embed = discord.Embed(
                title=f"🏏 Match Fixture - Round {self.round_number}",
                color=0x0066CC
            )

            flag1 = get_team_flag(team1)
            flag2 = get_team_flag(team2)

            embed.add_field(
                name="Teams",
                value=f"{flag1} **{team1}**\n🆚\n{flag2} **{team2}**",
                inline=False
            )

            embed.add_field(
                name="Venue",
                value=f"{channel.mention}",
                inline=False
            )

            embed.set_footer(text=f"Round {self.round_number} • Tournament Match")
            embed.timestamp = discord.utils.utcnow()

            # Get team roles and ping them
            role1_id = get_team_role_id(team1)
            role2_id = get_team_role_id(team2)

            ping_text = ""
            if role1_id:
                ping_text += f"<@&{role1_id}> "
            if role2_id:
                ping_text += f"<@&{role2_id}> "

            if ping_text:
                await channel.send(content=ping_text, embed=embed)
            else:
                await channel.send(embed=embed)

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

        tournament_id, tournament_name = tournament

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

        # Create table header
        table = "```\n"
        table += "POS  TEAM              PT  M  W  L   NRR    FPP\n"
        table += "═" * 50 + "\n"

        for idx, (team_name, points, matches, wins, losses, nrr, fpp) in enumerate(teams, 1):
            flag = get_team_flag(team_name)
            # Truncate team name if too long
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
        """Generate round-robin fixtures for the tournament"""

        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name = tournament

        # Get all teams
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("SELECT team_name FROM tournament_teams WHERE tournament_id = ?", (tournament_id,))
        teams = [row[0] for row in c.fetchall()]

        # Check if fixtures already exist
        c.execute("SELECT COUNT(*) FROM fixtures WHERE tournament_id = ?", (tournament_id,))
        existing_fixtures = c.fetchone()[0]

        if existing_fixtures > 0:
            await ctx.send("⚠️ Fixtures already exist for this tournament! Use `-clearfixtures` first if you want to regenerate.")
            conn.close()
            return

        conn.close()

        if len(teams) < 2:
            await ctx.send("❌ Need at least 2 teams to generate fixtures!")
            return

        # Generate round-robin fixtures
        fixtures = []
        for i in range(len(teams)):
            for j in range(i + 1, len(teams)):
                fixtures.append((teams[i], teams[j]))

        # Randomly assign channels
        random.shuffle(fixtures)
        channel_assignments = []

        for idx, (team1, team2) in enumerate(fixtures):
            channel_id = MATCH_CHANNELS[idx % len(MATCH_CHANNELS)]
            channel_assignments.append((team1, team2, channel_id))

        # Show fixtures for confirmation
        embed = discord.Embed(
            title=f"🏆 {tournament_name} - Generated Fixtures",
            description=f"**Total Matches:** {len(fixtures)}\n\n**Fixture List:**",
            color=0x0066CC
        )

        fixture_text = ""
        for idx, (team1, team2, channel_id) in enumerate(channel_assignments, 1):
            channel = self.bot.get_channel(channel_id)
            channel_mention = channel.mention if channel else f"<#{channel_id}>"
            flag1 = get_team_flag(team1)
            flag2 = get_team_flag(team2)
            line = f"**{idx}.** {flag1} {team1} vs {flag2} {team2} - {channel_mention}\n"
            if len(embed.description) + len(fixture_text) + len(line) > 4000:
                fixture_text += "... and more matches (list truncated due to size)"
                break
            fixture_text += line

        embed.description += f"\n{fixture_text}"
        embed.set_footer(text="Review and click Confirm to post these fixtures")

        # Create confirmation view
        view = FixtureModificationView(ctx, tournament_id, channel_assignments, round_number=1)
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

        tournament_id, tournament_name = tournament

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
            channel = self.bot.get_channel(channel_id)
            channel_mention = channel.mention if channel else f"<#{channel_id}>"

            embed.add_field(
                name=f"Round {round_num}",
                value=f"{flag1} **{team1}** vs {flag2} **{team2}**\n{channel_mention}",
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

        tournament_id, tournament_name = tournament

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
        conn.commit()
        conn.close()

        await ctx.send(f"✅ Cleared **{deleted}** fixtures!")

async def setup(bot):
    await bot.add_cog(Tournament(bot))