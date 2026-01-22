import discord
import sqlite3
import re
import io
import aiohttp
from discord.ext import commands
from discord.ui import View, Button
from PIL import Image, ImageDraw, ImageFont

# Stats calculation functions
def get_user_stats(user_id):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("""
        SELECT 
            SUM(runs) as total_runs,
            SUM(balls_faced) as total_balls_faced,
            SUM(runs_conceded) as total_runs_conceded,
            SUM(balls_bowled) as total_balls_bowled,
            SUM(wickets) as total_wickets,
            SUM(not_out) as times_not_out,
            COUNT(*) as matches_played
        FROM match_stats
        WHERE user_id = ?
    """, (user_id,))
    result = c.fetchone()
    conn.close()
    return result

def get_leaderboard_data(stat_type):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    if stat_type == "runs":
        c.execute("""
            SELECT user_id, SUM(runs) as total, SUM(balls_faced) as balls
            FROM match_stats
            GROUP BY user_id
            HAVING total > 0
            ORDER BY total DESC
        """)
    elif stat_type == "wickets":
        c.execute("""
            SELECT user_id, SUM(wickets) as total, SUM(balls_bowled) as balls
            FROM match_stats
            GROUP BY user_id
            HAVING total > 0
            ORDER BY total DESC
        """)
    elif stat_type == "economy":
        c.execute("""
            SELECT user_id, 
                   SUM(runs_conceded) as runs, 
                   SUM(balls_bowled) as balls,
                   CAST(SUM(runs_conceded) AS FLOAT) / (CAST(SUM(balls_bowled) AS FLOAT) / 6.0) as economy
            FROM match_stats
            WHERE balls_bowled > 0
            GROUP BY user_id
            HAVING balls >= 6
            ORDER BY economy ASC
        """)
    elif stat_type == "strike_rate":
        c.execute("""
            SELECT user_id,
                   SUM(runs) as runs,
                   SUM(balls_faced) as balls,
                   (CAST(SUM(runs) AS FLOAT) / CAST(SUM(balls_faced) AS FLOAT)) * 100 as sr
            FROM match_stats
            WHERE balls_faced > 0
            GROUP BY user_id
            HAVING balls >= 10
            ORDER BY sr DESC
        """)
    elif stat_type == "average":
        c.execute("""
            SELECT user_id,
                   SUM(runs) as runs,
                   COUNT(*) - SUM(not_out) as dismissals,
                   CAST(SUM(runs) AS FLOAT) / CAST(COUNT(*) - SUM(not_out) AS FLOAT) as avg
            FROM match_stats
            WHERE balls_faced > 0
            GROUP BY user_id
            HAVING dismissals > 0
            ORDER BY avg DESC
        """)
    elif stat_type == "bowling_average":
        c.execute("""
            SELECT user_id,
                   SUM(runs_conceded) as runs,
                   SUM(wickets) as wickets,
                   CAST(SUM(runs_conceded) AS FLOAT) / CAST(SUM(wickets) AS FLOAT) as avg
            FROM match_stats
            WHERE wickets > 0
            GROUP BY user_id
            ORDER BY avg ASC
        """)

    results = c.fetchall()
    conn.close()
    return results

def get_player_name_by_user_id(user_id):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def get_player_image_by_name(player_name):
    """Get player image URL from players.json"""
    import json
    try:
        with open('players.json', 'r', encoding='utf-8') as f:
            teams_data = json.load(f)

        for team_data in teams_data:
            for player in team_data['players']:
                if player['name'] == player_name:
                    return player['image']
    except:
        pass
    return None

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

def get_active_tournament():
    """Get the currently active tournament"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT id, name, current_round FROM tournaments WHERE is_active = 1 LIMIT 1")
    result = c.fetchone()
    conn.close()
    return result

def update_tournament_stats(team1, team2, winner, team1_runs, team1_balls, team2_runs, team2_balls):
    """Update tournament points table based on match result"""
    tournament = get_active_tournament()
    if not tournament:
        return

    tournament_id = tournament[0]

    # Calculate Net Run Rate
    team1_rr = (team1_runs / team1_balls) * 6 if team1_balls > 0 else 0
    team2_rr = (team2_runs / team2_balls) * 6 if team2_balls > 0 else 0

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    # Update winner
    if winner == team1:
        # Team1 wins
        c.execute("""UPDATE tournament_teams 
                    SET points = points + 2,
                        matches_played = matches_played + 1,
                        wins = wins + 1,
                        nrr = nrr + ?
                    WHERE tournament_id = ? AND team_name = ?""",
                 (team1_rr - team2_rr, tournament_id, team1))

        # Team2 loses
        c.execute("""UPDATE tournament_teams 
                    SET matches_played = matches_played + 1,
                        losses = losses + 1,
                        nrr = nrr + ?
                    WHERE tournament_id = ? AND team_name = ?""",
                 (team2_rr - team1_rr, tournament_id, team2))
    else:
        # Team2 wins
        c.execute("""UPDATE tournament_teams 
                    SET points = points + 2,
                        matches_played = matches_played + 1,
                        wins = wins + 1,
                        nrr = nrr + ?
                    WHERE tournament_id = ? AND team_name = ?""",
                 (team2_rr - team1_rr, tournament_id, team2))

        # Team1 loses
        c.execute("""UPDATE tournament_teams 
                    SET matches_played = matches_played + 1,
                        losses = losses + 1,
                        nrr = nrr + ?
                    WHERE tournament_id = ? AND team_name = ?""",
                 (team1_rr - team2_rr, tournament_id, team1))

    # Mark fixture as played
    c.execute("""UPDATE fixtures 
                SET is_played = 1, winner = ?
                WHERE tournament_id = ? 
                AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))
                AND is_played = 0""",
             (winner, tournament_id, team1, team2, team2, team1))

    conn.commit()
    conn.close()

async def create_stats_leaderboard_image(stat_type, data, page=0):
    """Create stats leaderboard image based on stats.webp template"""
    try:
        # Load the background template
        img = Image.open("stats.webp").convert('RGBA')
        width, height = img.size

        # Load font
        try:
            name_font = ImageFont.truetype("nor.otf", 50)
            stat_font = ImageFont.truetype("nor.otf", 55)
        except:
            name_font = ImageFont.load_default()
            stat_font = ImageFont.load_default()

        # Define positions (based on your image layout)
        # Purple circles on left, yellow bars on right
        entries_per_page = 5
        start_idx = page * entries_per_page
        end_idx = min(start_idx + entries_per_page, len(data))

        # Vertical positions for each row (adjust based on your stats.webp)
        # 1st player has specific coordinates and size
        first_player_circle_pos = (100, 100)  # (x, y) center
        first_player_size = 120
        first_player_text_pos = (350, 105) # (x, y) for name/username
        first_player_stat_pos = (width - 150, 100) # (x, y) for stat

        row_positions = [
            130,   # Row 1 (center)
            260,   # Row 2
            390,   # Row 3
            520,   # Row 4
            650    # Row 5
        ]

        purple_circle_x = 140  # X position for center of purple circle
        yellow_bar_x = 350  # X position for start of yellow bar (player name)
        yellow_bar_stat_x = width - 150  # X position for stat value (right side)

        draw = ImageDraw.Draw(img)

        async with aiohttp.ClientSession() as session:
            for idx, row_data in enumerate(data[start_idx:end_idx]):
                row_idx = idx
                user_id = row_data[0]

                # Get player info
                player_name = get_player_name_by_user_id(user_id)
                if not player_name:
                    continue

                player_image_url = get_player_image_by_name(player_name)

                # Download and paste player headshot
                if player_image_url and player_image_url.strip():
                    try:
                        async with session.get(player_image_url) as resp:
                            if resp.status == 200:
                                img_data = await resp.read()
                                player_img = Image.open(io.BytesIO(img_data)).convert('RGBA')

                                # Set size based on rank
                                size = first_player_size if row_idx == 0 and page == 0 else 100
                                player_img = player_img.resize((size, size), Image.Resampling.LANCZOS)
                                
                                # Set 99% opacity (252/255)
                                if player_img.mode != 'RGBA':
                                    player_img = player_img.convert('RGBA')
                                alpha = player_img.getchannel('A')
                                alpha = alpha.point(lambda i: min(i, 252))
                                player_img.putalpha(alpha)
                                
                                # Position based on rank
                                if row_idx == 0 and page == 0:
                                    circle_x = first_player_circle_pos[0] - (size // 2)
                                    circle_y = first_player_circle_pos[1] - (size // 2)
                                else:
                                    y_pos = row_positions[row_idx]
                                    circle_x = purple_circle_x - (size // 2)
                                    circle_y = y_pos - (size // 2)

                                img.paste(player_img, (circle_x, circle_y), player_img)
                    except Exception as e:
                        print(f"Error loading player image: {e}")

                # Draw player name and username
                username = f"(@{user_id})"
                name_text = f"{player_name} {username}"
                
                # Draw stat value
                if stat_type == "runs":
                    stat_text = f"{row_data[1]} runs"
                elif stat_type == "wickets":
                    stat_text = f"{row_data[1]} wickets"

                if row_idx == 0 and page == 0:
                    draw.text(first_player_text_pos, name_text, fill=(0, 0, 0), font=name_font)
                    draw.text(first_player_stat_pos, stat_text, fill=(0, 0, 0), font=stat_font)
                else:
                    y_pos = row_positions[row_idx]
                    draw.text((yellow_bar_x, y_pos - 35), name_text, fill=(0, 0, 0), font=name_font)
                    draw.text((yellow_bar_stat_x, y_pos - 30), stat_text, fill=(0, 0, 0), font=stat_font)

        # Convert to bytes
        output = io.BytesIO()
        img = img.convert('RGB')
        img.save(output, format='PNG', quality=95)
        output.seek(0)

        return output
    except Exception as e:
        print(f"Error creating stats leaderboard image: {e}")
        import traceback
        traceback.print_exc()
        return None

# Stats Image View with pagination
class StatsImageView(View):
    def __init__(self, ctx, stat_type, data):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.stat_type = stat_type
        self.data = data
        self.current_page = 0
        self.total_pages = (len(data) + 4) // 5  # 5 per page
        self.message = None

        self.update_buttons()

    def update_buttons(self):
        # Disable/enable buttons based on current page
        self.children[0].disabled = self.current_page == 0
        self.children[1].disabled = self.current_page >= self.total_pages - 1

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.current_page -= 1
        self.update_buttons()

        # Create new image for this page
        img = await create_stats_leaderboard_image(self.stat_type, self.data, self.current_page)
        if img:
            file = discord.File(img, filename=f"{self.stat_type}_page_{self.current_page+1}.png")

            embed = discord.Embed(
                title=f"{'🏏 Most Runs' if self.stat_type == 'runs' else '🎯 Most Wickets'}",
                color=0x00FF00
            )
            embed.set_image(url=f"attachment://{self.stat_type}_page_{self.current_page+1}.png")
            embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages}")

            await interaction.response.edit_message(embed=embed, attachments=[file], view=self)
        else:
            await interaction.response.send_message("❌ Failed to create stats image!", ephemeral=True)

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.current_page += 1
        self.update_buttons()

        # Create new image for this page
        img = await create_stats_leaderboard_image(self.stat_type, self.data, self.current_page)
        if img:
            file = discord.File(img, filename=f"{self.stat_type}_page_{self.current_page+1}.png")

            embed = discord.Embed(
                title=f"{'🏏 Most Runs' if self.stat_type == 'runs' else '🎯 Most Wickets'}",
                color=0x00FF00
            )
            embed.set_image(url=f"attachment://{self.stat_type}_page_{self.current_page+1}.png")
            embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages}")

            await interaction.response.edit_message(embed=embed, attachments=[file], view=self)
        else:
            await interaction.response.send_message("❌ Failed to create stats image!", ephemeral=True)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            await self.message.edit(view=self)

# Leaderboard View with category buttons and dual image/text display
class LeaderboardView(View):
    def __init__(self, ctx):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.message = None
        self.current_stat_type = None
        self.current_page = 0
        self.is_image_mode = True
        self.data = None

    async def create_leaderboard_embed(self, stat_type, page=0):
        titles = {
            "runs": "🏏 Most Runs",
            "wickets": "🎯 Most Wickets",
            "economy": "💰 Best Economy Rate",
            "strike_rate": "⚡ Best Strike Rate",
            "average": "📊 Best Batting Average",
            "bowling_average": "🎳 Best Bowling Average"
        }

        embed = discord.Embed(
            title=titles[stat_type],
            color=0x00FF00
        )

        data = get_leaderboard_data(stat_type)

        if not data:
            embed.description = "No data available yet."
            return embed, 0

        # Pagination: 20 entries per text page
        entries_per_page = 20
        start_idx = page * entries_per_page
        end_idx = min(start_idx + entries_per_page, len(data))
        total_pages = (len(data) + entries_per_page - 1) // entries_per_page

        description = ""
        for idx, row in enumerate(data[start_idx:end_idx], start_idx + 1):
            user_id = row[0]
            player_name = get_player_name_by_user_id(user_id)
            member = self.ctx.guild.get_member(user_id)
            username = member.name if member else "Unknown"

            # Get team for emoji
            team = get_user_team(user_id)
            team_emoji = get_team_flag(team) if team else ""

            player_display = f"{team_emoji} **{player_name}** (@{username})" if player_name else f"@{username}"

            line = ""
            if stat_type == "runs":
                line = f"**{idx}.** {player_display}\n    └ {row[1]} runs ({row[2]} balls)\n\n"
            elif stat_type == "wickets":
                line = f"**{idx}.** {player_display}\n    └ {row[1]} wickets ({row[2]} balls)\n\n"
            elif stat_type == "economy":
                line = f"**{idx}.** {player_display}\n    └ {row[3]:.2f} economy ({row[1]} runs in {row[2]} balls)\n\n"
            elif stat_type == "strike_rate":
                line = f"**{idx}.** {player_display}\n    └ {row[3]:.2f} SR ({row[1]} runs off {row[2]} balls)\n\n"
            elif stat_type == "average":
                line = f"**{idx}.** {player_display}\n    └ {row[3]:.2f} average ({row[1]} runs, {int(row[2])} dismissals)\n\n"
            elif stat_type == "bowling_average":
                line = f"**{idx}.** {player_display}\n    └ {row[3]:.2f} average ({row[1]} runs, {int(row[2])} wickets)\n\n"

            if len(description) + len(line) > 4000:
                description += "... (truncated)"
                break
            description += line

        embed.description = description
        embed.set_footer(text=f"Page {page + 1}/{total_pages} | Tournament Statistics")
        return embed, total_pages

    def update_buttons(self):
        """Update button states based on current state"""
        # Category buttons (always enabled)
        for button in self.children:
            if button.label in ["🏏 Runs", "🎯 Wickets", "💰 Economy", "⚡ Strike Rate", "📊 Bat Average", "🎳 Bowl Average"]:
                button.disabled = False
        
        # Navigation buttons
        if self.is_image_mode:
            # Show next button only
            for button in self.children:
                if button.label == "Next ➡️":
                    button.disabled = False
                elif button.label == "◀️ Previous":
                    button.disabled = True
        else:
            # Show previous/next based on page
            for button in self.children:
                if button.label == "◀️ Previous":
                    button.disabled = self.current_page == 0
                elif button.label == "Next ➡️":
                    button.disabled = self.current_page >= (len(self.data) + 19) // 20 - 1

    @discord.ui.button(label="🏏 Runs", style=discord.ButtonStyle.success, row=0)
    async def runs_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        self.current_stat_type = "runs"
        self.current_page = 0
        self.is_image_mode = True
        self.data = get_leaderboard_data("runs")
        await self.show_current_page(interaction)

    @discord.ui.button(label="🎯 Wickets", style=discord.ButtonStyle.success, row=0)
    async def wickets_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        self.current_stat_type = "wickets"
        self.current_page = 0
        self.is_image_mode = True
        self.data = get_leaderboard_data("wickets")
        await self.show_current_page(interaction)

    @discord.ui.button(label="💰 Economy", style=discord.ButtonStyle.success, row=0)
    async def economy_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        self.current_stat_type = "economy"
        self.current_page = 0
        self.is_image_mode = True
        self.data = get_leaderboard_data("economy")
        await self.show_current_page(interaction)

    @discord.ui.button(label="⚡ Strike Rate", style=discord.ButtonStyle.primary, row=1)
    async def sr_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        self.current_stat_type = "strike_rate"
        self.current_page = 0
        self.is_image_mode = True
        self.data = get_leaderboard_data("strike_rate")
        await self.show_current_page(interaction)

    @discord.ui.button(label="📊 Bat Average", style=discord.ButtonStyle.primary, row=1)
    async def avg_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        self.current_stat_type = "average"
        self.current_page = 0
        self.is_image_mode = True
        self.data = get_leaderboard_data("average")
        await self.show_current_page(interaction)

    @discord.ui.button(label="🎳 Bowl Average", style=discord.ButtonStyle.primary, row=1)
    async def bowl_avg_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        self.current_stat_type = "bowling_average"
        self.current_page = 0
        self.is_image_mode = True
        self.data = get_leaderboard_data("bowling_average")
        await self.show_current_page(interaction)

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.primary, row=2)
    async def previous_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        
        if self.is_image_mode:
            # Can't go back from image mode
            await interaction.response.defer()
            return
        
        self.current_page -= 1
        self.update_buttons()
        await self.show_current_page(interaction)

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.primary, row=2)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        
        if self.is_image_mode:
            # Transition from image to text mode
            self.is_image_mode = False
            self.current_page = 0
        else:
            # Next text page
            self.current_page += 1
        
        self.update_buttons()
        await self.show_current_page(interaction)

    async def show_current_page(self, interaction: discord.Interaction):
        """Display the current page (image or text)"""
        if self.is_image_mode:
            # Show image version
            img = await create_stats_leaderboard_image(self.current_stat_type, self.data, 0)
            if img:
                file = discord.File(img, filename=f"{self.current_stat_type}_page_1.png")
                embed = discord.Embed(
                    title=self.get_title(self.current_stat_type),
                    color=0x00FF00
                )
                embed.set_image(url=f"attachment://{self.current_stat_type}_page_1.png")
                embed.set_footer(text="Page 1/2 (Image) | Click Next to see all stats")
                self.update_buttons()
                await interaction.response.edit_message(embed=embed, attachments=[file], view=self)
            else:
                await interaction.response.defer()
        else:
            # Show text version
            embed, total_pages = await self.create_leaderboard_embed(self.current_stat_type, self.current_page)
            self.update_buttons()
            await interaction.response.edit_message(embed=embed, view=self)

    async def show_current_page_initial(self, ctx):
        """Display the initial page (for command startup)"""
        if self.is_image_mode:
            # Show image version
            img = await create_stats_leaderboard_image(self.current_stat_type, self.data, 0)
            if img:
                file = discord.File(img, filename=f"{self.current_stat_type}_page_1.png")
                embed = discord.Embed(
                    title=self.get_title(self.current_stat_type),
                    color=0x00FF00
                )
                embed.set_image(url=f"attachment://{self.current_stat_type}_page_1.png")
                embed.set_footer(text="Page 1/2 (Image) | Click Next to see all stats")
                self.update_buttons()
                self.message = await ctx.send(embed=embed, file=file, view=self)
            else:
                await ctx.send("❌ Failed to create leaderboard image!")
        else:
            # Show text version
            embed, total_pages = await self.create_leaderboard_embed(self.current_stat_type, self.current_page)
            self.update_buttons()
            self.message = await ctx.send(embed=embed, view=self)

    def get_title(self, stat_type):
        """Get title for stat type"""
        titles = {
            "runs": "🏏 Most Runs",
            "wickets": "🎯 Most Wickets",
            "economy": "💰 Best Economy Rate",
            "strike_rate": "⚡ Best Strike Rate",
            "average": "📊 Best Batting Average",
            "bowling_average": "🎳 Best Bowling Average"
        }
        return titles.get(stat_type, "Leaderboard")

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            await self.message.edit(view=self)

# Personal Stats View
class PersonalStatsView(View):
    def __init__(self, ctx, user_id):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.user_id = user_id
        self.message = None

    async def create_stats_embed(self, stat_type):
        stats = get_user_stats(self.user_id)

        if not stats or stats[0] is None:
            embed = discord.Embed(
                title="📊 Your Statistics",
                description="You haven't played any matches yet!",
                color=0xFF0000
            )
            return embed

        total_runs, total_balls_faced, total_runs_conceded, total_balls_bowled, total_wickets, times_not_out, matches_played = stats

        member = self.ctx.guild.get_member(self.user_id)
        player_name = get_player_name_by_user_id(self.user_id)

        if stat_type == "overview":
            embed = discord.Embed(
                title=f"📊 Career Statistics - {player_name if player_name else member.name}",
                color=0x0066CC
            )

            batting_avg = total_runs / (matches_played - times_not_out) if (matches_played - times_not_out) > 0 else total_runs
            strike_rate = (total_runs / total_balls_faced * 100) if total_balls_faced > 0 else 0

            embed.add_field(
                name="🏏 Batting",
                value=f"**Runs:** {total_runs or 0}\n"
                      f"**Balls Faced:** {total_balls_faced or 0}\n"
                      f"**Average:** {batting_avg:.2f}\n"
                      f"**Strike Rate:** {strike_rate:.2f}\n"
                      f"**Not Outs:** {times_not_out or 0}",
                inline=True
            )

            economy = (total_runs_conceded / (total_balls_bowled / 6)) if total_balls_bowled > 0 else 0
            bowl_avg = (total_runs_conceded / total_wickets) if total_wickets > 0 else 0

            bowl_avg_str = f"{bowl_avg:.2f}" if total_wickets > 0 else "N/A"
            embed.add_field(
                name="🎳 Bowling",
                value=f"**Wickets:** {total_wickets or 0}\n"
                      f"**Runs Conceded:** {total_runs_conceded or 0}\n"
                      f"**Balls Bowled:** {total_balls_bowled or 0}\n"
                      f"**Economy:** {economy:.2f}\n"
                      f"**Average:** {bowl_avg_str}",
                inline=True
            )

            embed.add_field(
                name="📈 Overall",
                value=f"**Matches Played:** {matches_played}",
                inline=False
            )

        elif stat_type == "batting":
            embed = discord.Embed(
                title=f"🏏 Batting Statistics - {player_name if player_name else member.name}",
                color=0x00FF00
            )

            batting_avg = total_runs / (matches_played - times_not_out) if (matches_played - times_not_out) > 0 else total_runs
            strike_rate = (total_runs / total_balls_faced * 100) if total_balls_faced > 0 else 0

            embed.description = (
                f"**Total Runs:** {total_runs or 0}\n"
                f"**Balls Faced:** {total_balls_faced or 0}\n"
                f"**Batting Average:** {batting_avg:.2f}\n"
                f"**Strike Rate:** {strike_rate:.2f}\n"
                f"**Times Not Out:** {times_not_out or 0}\n"
                f"**Innings:** {matches_played}"
            )

        elif stat_type == "bowling":
            embed = discord.Embed(
                title=f"🎳 Bowling Statistics - {player_name if player_name else member.name}",
                color=0xFF6B00
            )

            economy = (total_runs_conceded / (total_balls_bowled / 6)) if total_balls_bowled > 0 else 0
            bowl_avg = (total_runs_conceded / total_wickets) if total_wickets > 0 else 0

            bowl_avg_str = f"{bowl_avg:.2f}" if total_wickets > 0 else "N/A"
            embed.description = (
                f"**Total Wickets:** {total_wickets or 0}\n"
                f"**Runs Conceded:** {total_runs_conceded or 0}\n"
                f"**Balls Bowled:** {total_balls_bowled or 0}\n"
                f"**Economy Rate:** {economy:.2f}\n"
                f"**Bowling Average:** {bowl_avg_str}\n"
                f"**Overs:** {(total_balls_bowled // 6)}.{(total_balls_bowled % 6)}"
            )

        if member and member.avatar:
            embed.set_thumbnail(url=member.avatar.url)

        embed.set_footer(text=f"Matches Played: {matches_played}")
        return embed

    @discord.ui.button(label="📊 Overview", style=discord.ButtonStyle.primary)
    async def overview_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        embed = await self.create_stats_embed("overview")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🏏 Batting", style=discord.ButtonStyle.success)
    async def batting_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        embed = await self.create_stats_embed("batting")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🎳 Bowling", style=discord.ButtonStyle.success)
    async def bowling_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        embed = await self.create_stats_embed("bowling")
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            await self.message.edit(view=self)

# Cricket Stats Cog
class CricketStats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="addstats", aliases=["as"], help="[ADMIN] Add match stats from bot message")
    @commands.has_permissions(administrator=True)
    async def addstats_command(self, ctx):
        if not ctx.message.reference:
            await ctx.send("❌ Please reply to a message containing match statistics!")
            return

        replied_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        content = replied_msg.content

        # Extract stats (format: user_id, runs, balls, runs_conceded, balls_bowled, wickets, not_out)
        pattern = r'(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)'
        matches = re.findall(pattern, content)

        if not matches:
            await ctx.send("❌ No valid statistics found in the replied message!")
            return

        # Collect team stats
        team_stats = {}
        user_teams = {}

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        for match in matches:
            user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out = map(int, match)

            c.execute("""
                INSERT INTO match_stats (user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out))

            # Get user's team
            team = get_user_team(user_id)
            if team:
                user_teams[user_id] = team
                if team not in team_stats:
                    team_stats[team] = {'runs': 0, 'balls': 0}
                team_stats[team]['runs'] += runs
                team_stats[team]['balls'] += balls_faced

        conn.commit()
        conn.close()

        # Determine which teams played
        teams_involved = list(team_stats.keys())

        if len(teams_involved) == 2:
            team1, team2 = teams_involved
            team1_runs = team_stats[team1]['runs']
            team1_balls = team_stats[team1]['balls']
            team2_runs = team_stats[team2]['runs']
            team2_balls = team_stats[team2]['balls']

            # Determine winner
            winner = team1 if team1_runs > team2_runs else team2

            # Update tournament stats
            update_tournament_stats(team1, team2, winner, team1_runs, team1_balls, team2_runs, team2_balls)

            await ctx.send(
                f"✅ Successfully added statistics for **{len(matches)}** players!\n\n"
                f"**Match Result:**\n"
                f"{team1}: {team1_runs}/{team1_balls} balls\n"
                f"{team2}: {team2_runs}/{team2_balls} balls\n\n"
                f"**Winner:** {winner} 🏆"
            )
        else:
            await ctx.send(f"✅ Successfully added statistics for **{len(matches)}** players!")

    @commands.command(name="stats", aliases=["s"], help="View your cricket statistics")
    async def stats_command(self, ctx, member: discord.Member = None):
        target = member or ctx.author

        stats = get_user_stats(target.id)

        if not stats or stats[0] is None:
            message = "You haven't" if target == ctx.author else f"{target.name} hasn't"
            await ctx.send(f"❌ {message} played any matches yet!")
            return

        view = PersonalStatsView(ctx, target.id)
        embed = await view.create_stats_embed("overview")
        view.message = await ctx.send(embed=embed, view=view)

    @commands.command(name="leaderboard", aliases=["lb"], help="View tournament leaderboards")
    async def leaderboard_command(self, ctx):
        view = LeaderboardView(ctx)
        view.current_stat_type = "runs"
        view.data = get_leaderboard_data("runs")
        view.is_image_mode = True
        await view.show_current_page_initial(ctx)

    @commands.command(name="resetstats", help="[ADMIN] Reset all match stats")
    @commands.has_permissions(administrator=True)
    async def resetstats_command(self, ctx):
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("DELETE FROM match_stats")
        conn.commit()
        conn.close()
        await ctx.send("✅ All match statistics have been reset!")

async def setup(bot):
    await bot.add_cog(CricketStats(bot))