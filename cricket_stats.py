import discord
import sqlite3
import re
import io
import aiohttp
from discord.ext import commands
from discord.ui import View, Button
from PIL import Image, ImageDraw, ImageFont, ImageFilter

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
            LIMIT 50
        """)
    elif stat_type == "wickets":
        c.execute("""
            SELECT user_id, SUM(wickets) as total, SUM(balls_bowled) as balls
            FROM match_stats
            GROUP BY user_id
            HAVING total > 0
            ORDER BY total DESC
            LIMIT 50
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
            LIMIT 20
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
            LIMIT 20
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
            LIMIT 20
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
            LIMIT 20
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

def get_player_emoji(player_name, bot):
    """Get emoji format for a player"""
    if not bot:
        return "👤"

    # Create the expected emoji name format
    emoji_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in player_name)[:32]

    # Search for emoji across all emoji servers
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

    for guild_id in EMOJI_SERVERS:
        guild = bot.get_guild(guild_id)
        if guild:
            emoji_obj = discord.utils.get(guild.emojis, name=emoji_name)
            if emoji_obj:
                return str(emoji_obj)

    return "👤"

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

def get_player_data(player_name):
    """Get player data from players.json"""
    import json

    try:
        with open('players.json', 'r', encoding='utf-8') as f:
            teams_data = json.load(f)

        for team_data in teams_data:
            for player in team_data['players']:
                if player['name'] == player_name:
                    return player, team_data['team']
    except:
        pass

    return None, None

async def create_top5_graphic(stat_type, data, guild, bot):
    """Create a beautiful top 5 graphic with player images"""

    # Create canvas (1920x1080 for high quality)
    width, height = 1920, 1080
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))

    # Create gradient background
    gradient = Image.new('RGBA', (width, height), (0, 0, 0, 255))
    draw = ImageDraw.Draw(gradient)

    # Create vertical gradient (dark blue to purple)
    for y in range(height):
        ratio = y / height
        r = int(10 + (80 - 10) * ratio)
        g = int(15 + (50 - 15) * ratio)
        b = int(50 + (120 - 50) * ratio)
        draw.rectangle([(0, y), (width, y+1)], fill=(r, g, b, 255))

    img.paste(gradient, (0, 0))
    draw = ImageDraw.Draw(img)

    # Try to load custom fonts, fallback to default
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
        name_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        username_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
        stats_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    except:
        title_font = ImageFont.load_default()
        name_font = ImageFont.load_default()
        username_font = ImageFont.load_default()
        stats_font = ImageFont.load_default()

    # Draw title
    title_text = "🏏 TOP 5 " + ("RUN SCORERS" if stat_type == "runs" else "WICKET TAKERS")
    title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(((width - title_width) / 2, 50), title_text, fill=(255, 215, 0, 255), font=title_font)

    # Player card settings
    card_width = 320
    card_height = 500
    spacing = 40
    start_y = 200

    # Calculate total width needed
    total_width = (card_width * 5) + (spacing * 4)
    start_x = (width - total_width) / 2

    async with aiohttp.ClientSession() as session:
        for idx, row in enumerate(data[:5]):
            user_id = row[0]
            player_name = get_player_name_by_user_id(user_id)
            member = guild.get_member(user_id)

            if not player_name or not member:
                continue

            # Get player data
            player_data, team_name = get_player_data(player_name)

            # Calculate card position
            card_x = int(start_x + (idx * (card_width + spacing)))
            card_y = start_y

            # Create card background with gradient
            card = Image.new('RGBA', (card_width, card_height), (0, 0, 0, 0))
            card_draw = ImageDraw.Draw(card)

            # Gradient card background
            for y in range(card_height):
                ratio = y / card_height
                alpha = int(200 - (100 * ratio))
                card_draw.rectangle([(0, y), (card_width, y+1)], fill=(255, 255, 255, alpha))

            # Draw card border
            card_draw.rectangle([(0, 0), (card_width-1, card_height-1)], outline=(255, 215, 0, 255), width=4)

            # Rank badge (top-left corner)
            rank_size = 70
            rank_badge = Image.new('RGBA', (rank_size, rank_size), (0, 0, 0, 0))
            rank_draw = ImageDraw.Draw(rank_badge)

            # Medal colors
            medal_colors = [
                (255, 215, 0),   # Gold
                (192, 192, 192), # Silver
                (205, 127, 50),  # Bronze
                (100, 149, 237), # Cornflower blue
                (147, 112, 219)  # Medium purple
            ]

            rank_draw.ellipse([(0, 0), (rank_size, rank_size)], fill=medal_colors[idx] + (255,))
            rank_text = str(idx + 1)
            rank_bbox = rank_draw.textbbox((0, 0), rank_text, font=stats_font)
            rank_text_width = rank_bbox[2] - rank_bbox[0]
            rank_text_height = rank_bbox[3] - rank_bbox[1]
            rank_draw.text(((rank_size - rank_text_width) / 2, (rank_size - rank_text_height) / 2 - 5), 
                          rank_text, fill=(0, 0, 0, 255), font=stats_font)

            card.paste(rank_badge, (10, 10), rank_badge)

            # Load player image
            if player_data and player_data.get('image'):
                try:
                    async with session.get(player_data['image']) as resp:
                        if resp.status == 200:
                            img_data = await resp.read()
                            player_img = Image.open(io.BytesIO(img_data)).convert('RGBA')

                            # Resize to fit card
                            player_img = player_img.resize((280, 280), Image.Resampling.LANCZOS)

                            # Paste player image (no mask, full visibility)
                            card.paste(player_img, (20, 100), player_img)
                except:
                    pass

            # Player name
            name_y = 390
            name_bbox = card_draw.textbbox((0, 0), player_name, font=name_font)
            name_width = name_bbox[2] - name_bbox[0]

            if name_width > card_width - 20:
                # Truncate if too long
                player_name = player_name[:15] + "..."

            name_bbox = card_draw.textbbox((0, 0), player_name, font=name_font)
            name_width = name_bbox[2] - name_bbox[0]
            card_draw.text(((card_width - name_width) / 2, name_y), player_name, fill=(0, 0, 0, 255), font=name_font)

            # Username
            username_text = f"@{member.name}"
            username_y = 435
            username_bbox = card_draw.textbbox((0, 0), username_text, font=username_font)
            username_width = username_bbox[2] - username_bbox[0]
            card_draw.text(((card_width - username_width) / 2, username_y), username_text, fill=(80, 80, 80, 255), font=username_font)

            # Stats
            if stat_type == "runs":
                stat_text = f"{row[1]} runs"
            else:
                stat_text = f"{row[1]} wickets"

            stat_y = 465
            stat_bbox = card_draw.textbbox((0, 0), stat_text, font=stats_font)
            stat_width = stat_bbox[2] - stat_bbox[0]
            card_draw.text(((card_width - stat_width) / 2, stat_y), stat_text, fill=(255, 215, 0, 255), font=stats_font)

            # Paste card onto main image
            img.paste(card, (card_x, card_y), card)

    # Convert to bytes
    output = io.BytesIO()
    img = img.convert('RGB')
    img.save(output, format='PNG', quality=95)
    output.seek(0)

    return output

# Leaderboard View with pagination
class LeaderboardView(View):
    def __init__(self, ctx, stat_type, bot):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.stat_type = stat_type
        self.bot = bot
        self.current_page = 0
        self.message = None
        self.graphic_created = False

    async def create_leaderboard_embed(self, page=0):
        titles = {
            "runs": "🏏 Most Runs",
            "wickets": "🎯 Most Wickets",
            "economy": "💰 Best Economy Rate",
            "strike_rate": "⚡ Best Strike Rate",
            "average": "📊 Best Batting Average",
            "bowling_average": "🎳 Best Bowling Average"
        }

        data = get_leaderboard_data(self.stat_type)

        if not data:
            embed = discord.Embed(
                title=titles[self.stat_type],
                description="No data available yet.",
                color=0x00FF00
            )
            return embed, None

        # For runs/wickets: 10 players per page (page 0 is graphic)
        if self.stat_type in ["runs", "wickets"]:
            if page == 0:
                # Page 0: Show graphic
                embed = discord.Embed(
                    title=titles[self.stat_type],
                    description="🏆 **Top 5 Performers** 🏆",
                    color=0xFFD700
                )
                embed.set_image(url="attachment://leaderboard_top5.png")
                embed.set_footer(text="Page 1 of ? • Visual Leaderboard")

                # Create graphic
                graphic = await create_top5_graphic(self.stat_type, data, self.ctx.guild, self.bot)
                return embed, graphic
            else:
                # Text pages: 10 players per page
                players_per_page = 10
                text_page = page - 1
                start_idx = text_page * players_per_page
                end_idx = start_idx + players_per_page
                page_data = data[start_idx:end_idx]

                embed = discord.Embed(
                    title=titles[self.stat_type],
                    color=0x00FF00
                )

                description = ""
                for idx, row in enumerate(page_data, start=start_idx + 1):
                    user_id = row[0]
                    player_name = get_player_name_by_user_id(user_id)
                    member = self.ctx.guild.get_member(user_id)
                    username = member.name if member else "Unknown"

                    # Get team and emoji
                    team_name = get_user_team(user_id)
                    flag = get_team_flag(team_name) if team_name else ""
                    emoji = get_player_emoji(player_name, self.bot) if player_name else "👤"

                    player_display = f"{flag} {emoji} **{player_name}** (@{username})" if player_name else f"@{username}"

                    if self.stat_type == "runs":
                        line = f"**{idx}.** {player_display}\n    └ {row[1]} runs ({row[2]} balls)\n\n"
                    else:  # wickets
                        line = f"**{idx}.** {player_display}\n    └ {row[1]} wickets ({row[2]} balls)\n\n"

                    description += line

                embed.description = description

                total_pages = ((len(data) - 1) // players_per_page) + 2  # +1 for graphic page, +1 for ceiling
                embed.set_footer(text=f"Page {page + 1} of {total_pages} • Tournament Statistics")
                return embed, None
        else:
            # Other stats: single page (original behavior)
            embed = discord.Embed(
                title=titles[self.stat_type],
                color=0x00FF00
            )

            description = ""
            for idx, row in enumerate(data, 1):
                user_id = row[0]
                player_name = get_player_name_by_user_id(user_id)
                member = self.ctx.guild.get_member(user_id)
                username = member.name if member else "Unknown"

                team_name = get_user_team(user_id)
                flag = get_team_flag(team_name) if team_name else ""
                emoji = get_player_emoji(player_name, self.bot) if player_name else "👤"

                player_display = f"{flag} {emoji} **{player_name}** (@{username})" if player_name else f"@{username}"

                line = ""
                if self.stat_type == "economy":
                    line = f"**{idx}.** {player_display}\n    └ {row[3]:.2f} economy ({row[0]} runs in {row[1]} balls)\n\n"
                elif self.stat_type == "strike_rate":
                    line = f"**{idx}.** {player_display}\n    └ {row[3]:.2f} SR ({row[1]} runs off {row[2]} balls)\n\n"
                elif self.stat_type == "average":
                    line = f"**{idx}.** {player_display}\n    └ {row[3]:.2f} average ({row[1]} runs, {int(row[2])} dismissals)\n\n"
                elif self.stat_type == "bowling_average":
                    line = f"**{idx}.** {player_display}\n    └ {row[3]:.2f} average ({row[1]} runs, {int(row[2])} wickets)\n\n"

                if len(description) + len(line) > 4000:
                    description += "... (truncated)"
                    break
                description += line

            embed.description = description
            embed.set_footer(text="Tournament Statistics")
            return embed, None

    def update_buttons(self):
        data = get_leaderboard_data(self.stat_type)

        if self.stat_type in ["runs", "wickets"]:
            total_pages = ((len(data) - 1) // 10) + 2  # +1 for graphic, +1 for ceiling
        else:
            total_pages = 1

        # Find previous and next buttons
        prev_button = None
        next_button = None

        for child in self.children:
            if isinstance(child, Button):
                if child.label == "◀️ Previous":
                    prev_button = child
                elif child.label == "Next ➡️":
                    next_button = child

        if prev_button:
            prev_button.disabled = self.current_page == 0
        if next_button:
            next_button.disabled = self.current_page >= total_pages - 1

    @discord.ui.button(label="🏏 Runs", style=discord.ButtonStyle.success, row=0)
    async def runs_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.stat_type = "runs"
        self.current_page = 0
        self.graphic_created = False

        embed, graphic = await self.create_leaderboard_embed(0)
        self.update_buttons()

        if graphic:
            file = discord.File(graphic, filename="leaderboard_top5.png")
            await interaction.response.edit_message(embed=embed, attachments=[file], view=self)
        else:
            await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="🎯 Wickets", style=discord.ButtonStyle.success, row=0)
    async def wickets_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.stat_type = "wickets"
        self.current_page = 0
        self.graphic_created = False

        embed, graphic = await self.create_leaderboard_embed(0)
        self.update_buttons()

        if graphic:
            file = discord.File(graphic, filename="leaderboard_top5.png")
            await interaction.response.edit_message(embed=embed, attachments=[file], view=self)
        else:
            await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="💰 Economy", style=discord.ButtonStyle.success, row=0)
    async def economy_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.stat_type = "economy"
        self.current_page = 0

        embed, _ = await self.create_leaderboard_embed(0)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="⚡ Strike Rate", style=discord.ButtonStyle.primary, row=1)
    async def sr_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.stat_type = "strike_rate"
        self.current_page = 0

        embed, _ = await self.create_leaderboard_embed(0)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="📊 Bat Average", style=discord.ButtonStyle.primary, row=1)
    async def avg_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.stat_type = "average"
        self.current_page = 0

        embed, _ = await self.create_leaderboard_embed(0)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="🎳 Bowl Average", style=discord.ButtonStyle.primary, row=1)
    async def bowl_avg_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.stat_type = "bowling_average"
        self.current_page = 0

        embed, _ = await self.create_leaderboard_embed(0)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary, row=2)
    async def prev_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        if self.current_page > 0:
            self.current_page -= 1

        embed, graphic = await self.create_leaderboard_embed(self.current_page)
        self.update_buttons()

        if graphic:
            file = discord.File(graphic, filename="leaderboard_top5.png")
            await interaction.response.edit_message(embed=embed, attachments=[file], view=self)
        else:
            await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.secondary, row=2)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        data = get_leaderboard_data(self.stat_type)

        if self.stat_type in ["runs", "wickets"]:
            total_pages = ((len(data) - 1) // 10) + 2
        else:
            total_pages = 1

        if self.current_page < total_pages - 1:
            self.current_page += 1

        embed, graphic = await self.create_leaderboard_embed(self.current_page)
        self.update_buttons()

        if graphic:
            file = discord.File(graphic, filename="leaderboard_top5.png")
            await interaction.response.edit_message(embed=embed, attachments=[file], view=self)
        else:
            await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except:
                pass

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
            try:
                await self.message.edit(view=self)
            except:
                pass

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
        view = LeaderboardView(ctx, "runs", self.bot)
        embed, graphic = await view.create_leaderboard_embed(0)

        if graphic:
            file = discord.File(graphic, filename="leaderboard_top5.png")
            view.message = await ctx.send(embed=embed, file=file, view=view)
        else:
            view.message = await ctx.send(embed=embed, view=view)

        view.update_buttons()

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