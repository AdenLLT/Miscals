import discord
import sqlite3
import random
import json
from discord.ext import commands
from discord.ui import View, Button, Select
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont
import io
import aiohttp

# ========== HELPER FUNCTIONS (imported from main.py logic) ==========


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
                  is_archived INTEGER DEFAULT 0,
                  winner TEXT,
                  archived_at TIMESTAMP,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS tournaments
     (id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE,
      is_active INTEGER DEFAULT 1,
      current_round INTEGER DEFAULT 0,
      is_archived INTEGER DEFAULT 0,
      winner TEXT,
      archived_at TIMESTAMP,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS player_trophies
     (id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER,
      tournament_id INTEGER,
      tournament_name TEXT,
      team_name TEXT,
      won_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (tournament_id) REFERENCES tournaments(id))''')

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
                  qualified INTEGER DEFAULT 0,
                  FOREIGN KEY (tournament_id) REFERENCES tournaments(id))''')

    # Fixtures (existing)
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

    # Trophy data for players
    c.execute('''CREATE TABLE IF NOT EXISTS player_trophies
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  tournament_id INTEGER,
                  tournament_name TEXT,
                  team_name TEXT,
                  won_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (tournament_id) REFERENCES tournaments(id))''')

    conn.commit()
    conn.close()


def get_player_name_by_user_id(user_id):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(
        "SELECT player_name FROM player_representatives WHERE user_id = ?",
        (user_id, ))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None


def get_user_team(user_id):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(
        "SELECT player_name FROM player_representatives WHERE user_id = ?",
        (user_id, ))
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


def get_player_emoji(player_name, bot):
    """Get emoji format for a player"""
    if not bot:
        return "👤"

    EMOJI_SERVERS = [
        840094596914741248, 829450700764217366, 902537846634733665,
        886642304335609937, 823884737437368340, 877275137009917992,
        848977887209979985, 1159160118018056192
    ]

    # Create the expected emoji name format
    emoji_name = ''.join(c if c.isalnum() or c == '_' else '_'
                         for c in player_name)[:32]

    # Search for emoji across all emoji servers
    for guild_id in EMOJI_SERVERS:
        guild = bot.get_guild(guild_id)
        if guild:
            emoji_obj = discord.utils.get(guild.emojis, name=emoji_name)
            if emoji_obj:
                return str(emoji_obj)

    return "👤"


# Available match channels (stadiums)
MATCH_CHANNELS = {
    1464251938521485403: "Dubai International Cricket Stadium",
    1464648443371978832: "Gaddafi Stadium Lahore",
    1464677627506987202: "National Stadium Karachi",
    1464677685593768047: "Rawalpindi Cricket Stadium",
    1464648571898036469: "Multan Cricket Stadium",
    1464677944222810429: "Arbab Niaz Stadium",
    1471920655955136736: "Abu Dhabi Cricket Stadium"
}

# Channel for posting fixtures
FIXTURES_CHANNEL = 1463219150645231849


class TeamStatsView(View):

    def __init__(self, ctx, team_name, bot):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.team_name = team_name
        self.bot = bot
        self.current_page = 0
        self.current_stat = "overview"
        self.message = None

    async def create_team_stats_embed(self, page=0, stat_type="overview"):
        """Create embed for team stats - overview or specific stat"""
        tournament = get_active_tournament()
        if not tournament:
            return discord.Embed(title="❌ Error",
                                 description="No active tournament found!",
                                 color=0xFF0000), None

        tournament_id, tournament_name, current_round = tournament

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Get team stats
        c.execute(
            """SELECT points, matches_played, wins, losses, nrr, fpp 
                     FROM tournament_teams 
                     WHERE tournament_id = ? AND team_name = ?""",
            (tournament_id, self.team_name))
        stats = c.fetchone()

        if not stats:
            conn.close()
            return discord.Embed(
                title="❌ Error",
                description=f"Team '{self.team_name}' not found in tournament!",
                color=0xFF0000), None

        points, matches_played, wins, losses, nrr, fpp = stats

        if stat_type == "overview":
            # Get all fixtures (played and upcoming)
            c.execute(
                """SELECT team1, team2, round_number, channel_id, is_played, is_reserved, winner
                         FROM fixtures 
                         WHERE tournament_id = ? AND (team1 = ? OR team2 = ?)
                         ORDER BY round_number ASC""",
                (tournament_id, self.team_name, self.team_name))
            fixtures = c.fetchall()
            conn.close()

            # Separate played and upcoming
            played_matches = []
            upcoming_matches = []

            for team1, team2, round_num, channel_id, is_played, is_reserved, winner in fixtures:
                opponent = team2 if team1 == self.team_name else team1
                opponent_flag = get_team_flag(opponent)
                stadium = MATCH_CHANNELS.get(channel_id, "Unknown Stadium")

                match_info = {
                    'opponent': opponent,
                    'opponent_flag': opponent_flag,
                    'round': round_num,
                    'stadium': stadium,
                    'channel_id': channel_id,
                    'is_played': is_played,
                    'is_reserved': is_reserved,
                    'winner': winner,
                    'team1': team1,
                    'team2': team2
                }

                if is_played:
                    played_matches.append(match_info)
                else:
                    upcoming_matches.append(match_info)

            # Calculate pages (5 matches per page)
            matches_per_page = 5
            total_played = len(played_matches)
            total_upcoming = len(upcoming_matches)

            # Determine what to show on this page
            if page == 0:
                # First page: Overview + first batch of played matches
                flag = get_team_flag(self.team_name)
                embed = discord.Embed(
                    title=f"{flag} {self.team_name}",
                    description=
                    f"**{tournament_name}** • Complete Team Overview",
                    color=get_team_color(self.team_name))

                # Overall stats with better formatting (REMOVED Position field)
                stats_text = (f"```yaml\n"
                              f"Points:      {points}\n"
                              f"Matches:     {matches_played}\n"
                              f"Wins:        {wins}\n"
                              f"Losses:      {losses}\n"
                              f"NRR:         {nrr:+.3f}\n"
                              f"FPP:         {fpp:+d}\n"
                              f"```")
                embed.add_field(name="📊 Tournament Statistics",
                                value=stats_text,
                                inline=False)

                # Summary
                summary = f"**Played:** {total_played} | **Upcoming:** {total_upcoming}"
                embed.add_field(name="📅 Match Summary",
                                value=summary,
                                inline=False)

                # Show first batch of played matches
                if played_matches:
                    played_text = ""
                    for match in played_matches[:matches_per_page]:
                        if match['winner'] == self.team_name:
                            result = "✅ Won"
                            color = "🟢"
                        elif match['winner']:
                            result = "❌ Lost"
                            color = "🔴"
                        else:
                            result = "⚪ Played"
                            color = "⚪"

                        played_text += f"{color} **Round {match['round']}** vs {match['opponent_flag']} **{match['opponent']}** • {result}\n"

                    embed.add_field(name="✅ Recent Matches",
                                    value=played_text,
                                    inline=False)

                total_pages = 1 + (
                    (total_played - 1) // matches_per_page + 1) + (
                        (total_upcoming - 1) // matches_per_page +
                        1 if total_upcoming > 0 else 0)
                embed.set_footer(
                    text=
                    f"Page 1 of {total_pages} • {tournament_name} • Use buttons to view stats"
                )

            else:
                # Subsequent pages: More played matches or upcoming matches
                played_pages = (
                    total_played - 1
                ) // matches_per_page + 1 if total_played > matches_per_page else 0

                if page <= played_pages:
                    # Show played matches
                    start_idx = matches_per_page + (page -
                                                    1) * matches_per_page
                    end_idx = start_idx + matches_per_page
                    page_matches = played_matches[start_idx:end_idx]

                    flag = get_team_flag(self.team_name)
                    embed = discord.Embed(
                        title=f"{flag} {self.team_name} • Played Matches",
                        description=f"**{tournament_name}**",
                        color=get_team_color(self.team_name))

                    played_text = ""
                    for match in page_matches:
                        if match['winner'] == self.team_name:
                            result = "✅ Won"
                            color = "🟢"
                        elif match['winner']:
                            result = "❌ Lost"
                            color = "🔴"
                        else:
                            result = "⚪ Played"
                            color = "⚪"

                        played_text += f"{color} **Round {match['round']}** vs {match['opponent_flag']} **{match['opponent']}** • {result}\n"

                    embed.add_field(name="Match Results",
                                    value=played_text,
                                    inline=False)

                else:
                    # Show upcoming matches
                    upcoming_page = page - played_pages - 1
                    start_idx = upcoming_page * matches_per_page
                    end_idx = start_idx + matches_per_page
                    page_matches = upcoming_matches[start_idx:end_idx]

                    flag = get_team_flag(self.team_name)
                    embed = discord.Embed(
                        title=f"{flag} {self.team_name} • Upcoming Matches",
                        description=f"**{tournament_name}**",
                        color=get_team_color(self.team_name))

                    upcoming_text = ""
                    for match in page_matches:
                        status = "📌 Reserved" if match[
                            'is_reserved'] else "🏏 Scheduled"
                        upcoming_text += f"{status} **Round {match['round']}** vs {match['opponent_flag']} **{match['opponent']}**\n🏟️ <#{match['channel_id']}>\n\n"

                    embed.add_field(name="Scheduled Fixtures",
                                    value=upcoming_text,
                                    inline=False)

                total_pages = 1 + played_pages + (
                    (total_upcoming - 1) // matches_per_page +
                    1 if total_upcoming > 0 else 0)
                embed.set_footer(
                    text=f"Page {page + 1} of {total_pages} • {tournament_name}"
                )

            return embed, None

        else:
            # Team-specific stats (runs, wickets, etc.)
            return await self.create_team_leaderboard_embed(stat_type, page)

    async def create_team_leaderboard_embed(self, stat_type, page=0):
        """Create leaderboard embed for team-specific stats"""

        titles = {
            "runs": "🏏 Top Run Scorers",
            "wickets": "🎯 Top Wicket Takers",
            "economy": "💰 Best Economy",
            "strike_rate": "⚡ Best Strike Rate",
            "average": "📊 Best Batting Average",
            "impact_points": "⭐ Most Impact Points"
        }

        # Get team players
        try:
            with open('players.json', 'r', encoding='utf-8') as f:
                teams_data = json.load(f)
        except:
            return discord.Embed(title="❌ Error",
                                 description="Could not load player data!",
                                 color=0xFF0000), None

        team_players = []
        for team_data in teams_data:
            if team_data['team'] == self.team_name:
                team_players = team_data['players']
                break

        if not team_players:
            return discord.Embed(title="❌ Error",
                                 description="No players found for this team!",
                                 color=0xFF0000), None

        # Get user IDs for team players
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        player_user_ids = []
        for player in team_players:
            c.execute(
                "SELECT user_id FROM player_representatives WHERE player_name = ?",
                (player['name'], ))
            result = c.fetchone()
            if result:
                player_user_ids.append(result[0])

        if not player_user_ids:
            conn.close()
            return discord.Embed(
                title="❌ Error",
                description="No claimed players in this team!",
                color=0xFF0000), None

        # Build query based on stat type
        placeholders = ','.join('?' * len(player_user_ids))

        if stat_type == "runs":
            c.execute(
                f"""
                SELECT user_id, SUM(runs) as total, SUM(balls_faced) as balls
                FROM match_stats
                WHERE user_id IN ({placeholders})
                GROUP BY user_id
                HAVING total > 0
                ORDER BY total DESC
            """, player_user_ids)
        elif stat_type == "wickets":
            c.execute(
                f"""
                SELECT user_id, SUM(wickets) as total, SUM(balls_bowled) as balls
                FROM match_stats
                WHERE user_id IN ({placeholders})
                GROUP BY user_id
                HAVING total > 0
                ORDER BY total DESC
            """, player_user_ids)
        elif stat_type == "economy":
            c.execute(
                f"""
                SELECT user_id, 
                       SUM(runs_conceded) as runs, 
                       SUM(balls_bowled) as balls,
                       CAST(SUM(runs_conceded) AS FLOAT) / (CAST(SUM(balls_bowled) AS FLOAT) / 6.0) as economy
                FROM match_stats
                WHERE user_id IN ({placeholders}) AND balls_bowled > 0
                GROUP BY user_id
                HAVING balls >= 6
                ORDER BY economy ASC
            """, player_user_ids)
        elif stat_type == "strike_rate":
            c.execute(
                f"""
                SELECT user_id,
                       SUM(runs) as runs,
                       SUM(balls_faced) as balls,
                       (CAST(SUM(runs) AS FLOAT) / CAST(SUM(balls_faced) AS FLOAT)) * 100 as sr
                FROM match_stats
                WHERE user_id IN ({placeholders}) AND balls_faced > 0
                GROUP BY user_id
                HAVING balls >= 10
                ORDER BY sr DESC
            """, player_user_ids)
        elif stat_type == "average":
            c.execute(
                f"""
                SELECT user_id,
                       SUM(runs) as runs,
                       COUNT(*) - SUM(not_out) as dismissals,
                       CAST(SUM(runs) AS FLOAT) / CAST(COUNT(*) - SUM(not_out) AS FLOAT) as avg
                FROM match_stats
                WHERE user_id IN ({placeholders}) AND balls_faced > 0
                GROUP BY user_id
                HAVING dismissals > 0
                ORDER BY avg DESC
            """, player_user_ids)
        elif stat_type == "impact_points":
            c.execute(
                f"""
                SELECT user_id, 
                       SUM(runs + (wickets * 20)) as total_impact
                FROM match_stats
                WHERE user_id IN ({placeholders})
                GROUP BY user_id
                ORDER BY total_impact DESC
            """, player_user_ids)

        data = c.fetchall()
        conn.close()

        if not data:
            return discord.Embed(
                title=titles[stat_type],
                description="No data available for this statistic.",
                color=get_team_color(self.team_name)), None

        # Pagination (10 per page)
        players_per_page = 10
        start_idx = page * players_per_page
        end_idx = start_idx + players_per_page
        page_data = data[start_idx:end_idx]

        flag = get_team_flag(self.team_name)
        embed = discord.Embed(
            title=f"{flag} {self.team_name} • {titles[stat_type]}",
            color=get_team_color(self.team_name))

        description = ""
        for idx, row in enumerate(page_data, start=start_idx + 1):
            user_id = row[0]
            player_name = get_player_name_by_user_id(user_id)
            member = self.ctx.guild.get_member(user_id)
            username = member.name if member else "Unknown"

            emoji = get_player_emoji(player_name,
                                     self.bot) if player_name else "👤"
            player_display = f"{emoji} **{player_name}** (@{username})" if player_name else f"@{username}"

            line = ""
            if stat_type == "runs":
                balls = int(row[2])
                overs = balls // 6
                remaining_balls = balls % 6
                overs_str = f"{overs}.{remaining_balls}" if remaining_balls > 0 else str(
                    overs)
                line = f"**{idx}.** {player_display}\n    └ {row[1]} runs ({overs_str} overs)\n\n"
            elif stat_type == "wickets":
                balls = int(row[2])
                overs = balls // 6
                remaining_balls = balls % 6
                overs_str = f"{overs}.{remaining_balls}" if remaining_balls > 0 else str(
                    overs)
                line = f"**{idx}.** {player_display}\n    └ {row[1]} wickets ({overs_str} overs)\n\n"
            elif stat_type == "economy":
                balls = int(row[2])
                overs = balls // 6
                remaining_balls = balls % 6
                overs_str = f"{overs}.{remaining_balls}" if remaining_balls > 0 else str(
                    overs)
                line = f"**{idx}.** {player_display}\n    └ {row[3]:.2f} economy ({int(row[1])} runs in {overs_str} overs)\n\n"
            elif stat_type == "strike_rate":
                balls = int(row[2])
                overs = balls // 6
                remaining_balls = balls % 6
                overs_str = f"{overs}.{remaining_balls}" if remaining_balls > 0 else str(
                    overs)
                line = f"**{idx}.** {player_display}\n    └ {row[3]:.2f} SR ({int(row[1])} runs off {overs_str} overs)\n\n"
            elif stat_type == "average":
                line = f"**{idx}.** {player_display}\n    └ {row[3]:.2f} average ({int(row[1])} runs, {int(row[2])} dismissals)\n\n"
            elif stat_type == "impact_points":
                line = f"**{idx}.** {player_display}\n    └ {int(row[1])} impact points\n\n"

            description += line

        embed.description = description

        total_pages = ((len(data) - 1) // players_per_page) + 1
        embed.set_footer(
            text=f"Page {page + 1} of {total_pages} • Team Statistics")

        return embed, None

    def update_buttons(self):
        """Update button states based on current page and mode"""
        if self.current_stat == "overview":
            # Get total pages for overview
            tournament = get_active_tournament()
            if not tournament:
                return

            tournament_id = tournament[0]
            conn = sqlite3.connect('players.db')
            c = conn.cursor()
            c.execute(
                """SELECT COUNT(*) FROM fixtures 
                         WHERE tournament_id = ? AND (team1 = ? OR team2 = ?) AND is_played = 1""",
                (tournament_id, self.team_name, self.team_name))
            played_count = c.fetchone()[0]

            c.execute(
                """SELECT COUNT(*) FROM fixtures 
                         WHERE tournament_id = ? AND (team1 = ? OR team2 = ?) AND is_played = 0""",
                (tournament_id, self.team_name, self.team_name))
            upcoming_count = c.fetchone()[0]
            conn.close()

            matches_per_page = 5
            played_pages = (
                played_count - 1
            ) // matches_per_page + 1 if played_count > matches_per_page else 0
            upcoming_pages = (
                upcoming_count -
                1) // matches_per_page + 1 if upcoming_count > 0 else 0
            total_pages = 1 + played_pages + upcoming_pages
        else:
            # Get total pages for stat view
            try:
                with open('players.json', 'r', encoding='utf-8') as f:
                    teams_data = json.load(f)

                team_players = []
                for team_data in teams_data:
                    if team_data['team'] == self.team_name:
                        team_players = team_data['players']
                        break

                conn = sqlite3.connect('players.db')
                c = conn.cursor()
                player_user_ids = []
                for player in team_players:
                    c.execute(
                        "SELECT user_id FROM player_representatives WHERE player_name = ?",
                        (player['name'], ))
                    result = c.fetchone()
                    if result:
                        player_user_ids.append(result[0])

                placeholders = ','.join('?' * len(player_user_ids))
                c.execute(
                    f"SELECT COUNT(DISTINCT user_id) FROM match_stats WHERE user_id IN ({placeholders})",
                    player_user_ids)
                player_count = c.fetchone()[0]
                conn.close()

                total_pages = ((player_count - 1) // 10) + 1
            except:
                total_pages = 1

        # Find and update navigation buttons
        for child in self.children:
            if isinstance(child, Button):
                if child.label == "◀️ Previous":
                    child.disabled = self.current_page == 0
                elif child.label == "Next ➡️":
                    child.disabled = self.current_page >= total_pages - 1

    # Stat buttons (Row 0-1)
    @discord.ui.button(label="📋 Overview",
                       style=discord.ButtonStyle.primary,
                       row=0)
    async def overview_button(self, interaction: discord.Interaction,
                              button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!",
                                                    ephemeral=True)
            return

        self.current_stat = "overview"
        self.current_page = 0
        embed, _ = await self.create_team_stats_embed(0, "overview")
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🏏 Runs",
                       style=discord.ButtonStyle.success,
                       row=0)
    async def runs_button(self, interaction: discord.Interaction,
                          button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!",
                                                    ephemeral=True)
            return

        self.current_stat = "runs"
        self.current_page = 0
        embed, _ = await self.create_team_stats_embed(0, "runs")
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🎯 Wickets",
                       style=discord.ButtonStyle.success,
                       row=0)
    async def wickets_button(self, interaction: discord.Interaction,
                             button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!",
                                                    ephemeral=True)
            return

        self.current_stat = "wickets"
        self.current_page = 0
        embed, _ = await self.create_team_stats_embed(0, "wickets")
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="💰 Economy",
                       style=discord.ButtonStyle.success,
                       row=0)
    async def economy_button(self, interaction: discord.Interaction,
                             button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!",
                                                    ephemeral=True)
            return

        self.current_stat = "economy"
        self.current_page = 0
        embed, _ = await self.create_team_stats_embed(0, "economy")
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⚡ Strike Rate",
                       style=discord.ButtonStyle.primary,
                       row=1)
    async def sr_button(self, interaction: discord.Interaction,
                        button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!",
                                                    ephemeral=True)
            return

        self.current_stat = "strike_rate"
        self.current_page = 0
        embed, _ = await self.create_team_stats_embed(0, "strike_rate")
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="📊 Average",
                       style=discord.ButtonStyle.primary,
                       row=1)
    async def avg_button(self, interaction: discord.Interaction,
                         button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!",
                                                    ephemeral=True)
            return

        self.current_stat = "average"
        self.current_page = 0
        embed, _ = await self.create_team_stats_embed(0, "average")
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⭐ Impact",
                       style=discord.ButtonStyle.primary,
                       row=1)
    async def impact_button(self, interaction: discord.Interaction,
                            button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!",
                                                    ephemeral=True)
            return

        self.current_stat = "impact_points"
        self.current_page = 0
        embed, _ = await self.create_team_stats_embed(0, "impact_points")
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    # Navigation buttons (Row 2)
    @discord.ui.button(label="◀️ Previous",
                       style=discord.ButtonStyle.secondary,
                       row=2)
    async def prev_button(self, interaction: discord.Interaction,
                          button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!",
                                                    ephemeral=True)
            return

        if self.current_page > 0:
            self.current_page -= 1

        embed, _ = await self.create_team_stats_embed(self.current_page,
                                                      self.current_stat)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next ➡️",
                       style=discord.ButtonStyle.secondary,
                       row=2)
    async def next_button(self, interaction: discord.Interaction,
                          button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!",
                                                    ephemeral=True)
            return

        self.current_page += 1

        embed, _ = await self.create_team_stats_embed(self.current_page,
                                                      self.current_stat)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except:
                pass


async def create_round_fixture_embed(team1,
                                     team2,
                                     channel_id,
                                     tournament_name,
                                     round_number,
                                     user_team,
                                     guild,
                                     is_user_match=False):
    """Create embed for a round fixture with stats and predictions"""

    # Get team stats
    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    tournament = get_active_tournament()
    tournament_id = tournament[0] if tournament else None

    c.execute(
        """SELECT points, matches_played, wins, losses, nrr 
                 FROM tournament_teams 
                 WHERE tournament_id = ? AND team_name = ?""",
        (tournament_id, team1))
    team1_stats = c.fetchone()

    c.execute(
        """SELECT points, matches_played, wins, losses, nrr 
                 FROM tournament_teams 
                 WHERE tournament_id = ? AND team_name = ?""",
        (tournament_id, team2))
    team2_stats = c.fetchone()

    conn.close()

    # Calculate win probability based on points, wins, and NRR
    if team1_stats and team2_stats:
        team1_points, team1_matches, team1_wins, team1_losses, team1_nrr = team1_stats
        team2_points, team2_matches, team2_wins, team2_losses, team2_nrr = team2_stats

        # Simple win probability calculation
        if team1_matches == 0 and team2_matches == 0:
            team1_win_prob = 50.0
        else:
            # Base probability on points
            total_points = max(team1_points + team2_points, 1)
            team1_base = (team1_points / total_points) * 100

            # Adjust for NRR (±10% max)
            nrr_diff = team1_nrr - team2_nrr
            nrr_adjustment = min(max(nrr_diff * 5, -10), 10)

            team1_win_prob = min(max(team1_base + nrr_adjustment, 10), 90)

        team2_win_prob = 100 - team1_win_prob
    else:
        team1_win_prob = 50.0
        team2_win_prob = 50.0

    # Create VS image
    stadium = MATCH_CHANNELS.get(channel_id, "Unknown Stadium")
    vs_image = await create_vs_image(team1, team2, stadium)

    # Create embed
    flag1 = get_team_flag(team1)
    flag2 = get_team_flag(team2)

    title = f"🏏 Your Match - Round {round_number}" if is_user_match else f"🏏 Round {round_number} Fixture"

    embed = discord.Embed(title=title,
                          description=f"**{tournament_name}**",
                          color=0x0066CC)

    # Teams
    embed.add_field(
        name="Match",
        value=f"{flag1} **{team1}** vs {flag2} **{team2}**\n🏟️ <#{channel_id}>",
        inline=False)

    # Win Probability with visual bar using different characters for each team
    bar_length = 20
    team1_bars = int((team1_win_prob / 100) * bar_length)
    team2_bars = bar_length - team1_bars

    # Use different characters: ▓ for team1, ░ for team2
    prob_bar = f"`[{'▓' * team1_bars}{'░' * team2_bars}]`"

    embed.add_field(
        name="📊 Win Probability",
        value=
        f"{flag1} **{team1_win_prob:.1f}%** {prob_bar} **{team2_win_prob:.1f}%** {flag2}",
        inline=False)

    # Top 3 players from each team
    team1_top3 = await get_top_players(team1, guild)
    team2_top3 = await get_top_players(team2, guild)

    # Add spacing and "Players To Watch Out For" header
    embed.add_field(
        name="\u200b",  # Invisible character for spacing
        value="",
        inline=False)

    embed.add_field(name="👀 Players To Watch Out For",
                    value="━━━━━━━━━━━━━━━━━━━━━",
                    inline=False)

    # Team 1 Players
    if team1_top3:
        team1_text = "\n".join([
            f"{role_emoji} **{full_name}** (@{username})"
            for role_emoji, full_name, username in team1_top3
        ])
    else:
        team1_text = "*No players with stats*"

    embed.add_field(name=f"{flag1} {team1}", value=team1_text, inline=True)

    # Team 2 Players
    if team2_top3:
        team2_text = "\n".join([
            f"{role_emoji} **{full_name}** (@{username})"
            for role_emoji, full_name, username in team2_top3
        ])
    else:
        team2_text = "*No players with stats*"

    embed.add_field(name=f"{flag2} {team2}", value=team2_text, inline=True)

    embed.set_footer(text=f"{tournament_name} • Round {round_number}")

    return embed, vs_image


async def get_top_players(team_name, guild):
    """Get top 3 performing players from a team based on impact points"""

    print(f"🔍 DEBUG: get_top_players called for {team_name}")

    # Load players from JSON
    try:
        with open('players.json', 'r', encoding='utf-8') as f:
            teams_data = json.load(f)
    except Exception as e:
        print(f"❌ DEBUG: Error loading players.json: {e}")
        return []

    team_players = []

    for team_data in teams_data:
        if team_data['team'] == team_name:
            team_players = team_data['players']
            break

    if not team_players:
        print(f"❌ DEBUG: No players found for team {team_name}")
        return []

    print(f"✅ DEBUG: Found {len(team_players)} total players for {team_name}")

    # Get impact points for each claimed player
    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    player_stats = []

    for player in team_players:
        # Check if player is claimed
        c.execute(
            "SELECT user_id FROM player_representatives WHERE player_name = ?",
            (player['name'], ))
        result = c.fetchone()

        if not result:
            continue

        user_id = result[0]
        print(f"   ✓ {player['name']} is claimed (user_id: {user_id})")

        # Get impact points (runs + wickets * 20)
        c.execute(
            """SELECT 
                        SUM(runs + (wickets * 20)) as total_impact
                     FROM match_stats 
                     WHERE user_id = ?""", (user_id, ))
        stats = c.fetchone()

        impact_points = stats[0] if stats[0] else 0

        print(f"      Impact Points: {impact_points}")

        # Get member for username
        member = guild.get_member(user_id)
        username = member.name if member else "Unknown"

        # Get role emoji
        if "Wicketkeeper" in player['role']:
            role_emoji = "<:wicketkeeper:1451994159668920330>"
        elif "Batsman" in player['role']:
            role_emoji = "<:bat:1451967322146213980>"
        elif "Bowler" in player['role']:
            role_emoji = "<:ball:1451974295793172547>"
        elif "All-Rounder" in player['role'] or "All-rounder" in player['role']:
            role_emoji = "<:allrounder:1451978476033671279>"
        else:
            role_emoji = ""

        if impact_points > 0:  # Only add players with stats
            player_stats.append({
                'role_emoji': role_emoji,
                'full_name': player['name'],
                'username': username,
                'impact_points': impact_points
            })
            print(f"      → Added to player_stats (impact: {impact_points})")

    conn.close()

    print(f"📊 DEBUG: {team_name} - {len(player_stats)} players with stats")

    # Sort by impact points and get top 3
    player_stats.sort(key=lambda x: x['impact_points'], reverse=True)
    top_3 = player_stats[:3]

    result = [(p['role_emoji'], p['full_name'], p['username']) for p in top_3]
    print(
        f"✅ DEBUG: Final top 3 for {team_name}: {[(name,) for _, name, _ in result]}"
    )
    return result


class RoundFixturesView(View):

    def __init__(self, ctx, tournament_id, round_number, fixtures, user_team,
                 user_fixture):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.tournament_id = tournament_id
        self.round_number = round_number
        self.fixtures = fixtures
        self.user_team = user_team
        self.user_fixture = user_fixture
        self.message = None

        # Add fixture dropdown
        self.add_fixture_dropdown()

    def add_fixture_dropdown(self):
        # Create dropdown options for ALL fixtures (including user's own)
        fixture_options = []

        for idx, (team1, team2, channel_id,
                  is_played) in enumerate(self.fixtures[:25]):
            flag1 = get_team_flag(team1)
            flag2 = get_team_flag(team2)

            # Mark user's own match
            is_user_match = self.user_team in [team1, team2]
            label = f"{'⭐ ' if is_user_match else ''}{team1} vs {team2}"

            fixture_options.append(
                discord.SelectOption(
                    label=label,
                    value=str(idx),
                    emoji="🏏",
                    description=
                    f"{'Your match' if is_user_match else 'Round fixture'}"))

        if fixture_options:
            fixture_select = discord.ui.Select(
                placeholder="🏏 Select a fixture to view",
                options=fixture_options,
                custom_id="fixture_select")
            fixture_select.callback = self.fixture_callback
            self.add_item(fixture_select)

    async def fixture_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!",
                                                    ephemeral=True)
            return

        await interaction.response.defer()

        fixture_idx = int(interaction.data['values'][0])

        # Get fixture data
        team1, team2, channel_id, is_played = self.fixtures[fixture_idx]

        tournament = get_active_tournament()
        tournament_name = tournament[1] if tournament else "Tournament"

        # Check if this is user's match
        is_user_match = self.user_team in [team1, team2]

        # Create embed for this fixture
        embed, image = await create_round_fixture_embed(
            team1,
            team2,
            channel_id,
            tournament_name,
            self.round_number,
            self.user_team,
            self.ctx.guild,
            is_user_match=is_user_match)

        if image:
            file = discord.File(image, filename="fixture.png")
            embed.set_image(url="attachment://fixture.png")
            await self.message.edit(embed=embed, attachments=[file], view=self)
        else:
            await self.message.edit(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except:
                pass


def get_active_tournament():
    """Get the currently active tournament (not archived)"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(
        "SELECT id, name, current_round FROM tournaments WHERE is_active = 1 AND is_archived = 0 LIMIT 1"
    )
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
    c.execute(
        "SELECT player_name FROM player_representatives WHERE user_id = ?",
        (user_id, ))
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
                draw.point((x, y), fill=color1 + (alpha, ))

        # Right side gradient (team2 color)
        for x in range(width // 2, width):
            progress = (x - width // 2) / (width // 2)
            alpha = int(150 * progress)  # Increased from 80

            for y in range(height):
                draw.point((x, y), fill=color2 + (alpha, ))

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
                            flag1 = Image.open(
                                io.BytesIO(flag_data)).convert('RGBA')
                            flag1 = flag1.resize((flag_size, flag_size),
                                                 Image.Resampling.LANCZOS)

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
                            flag2 = Image.open(
                                io.BytesIO(flag_data)).convert('RGBA')
                            flag2 = flag2.resize((flag_size, flag_size),
                                                 Image.Resampling.LANCZOS)

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
                                    stadium_name,
                                    font=font,
                                    fill=(0, 0, 0, 255))
        draw_final.text((text_x, text_y),
                        stadium_name,
                        font=font,
                        fill=(255, 255, 255, 255))

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


async def create_international_points_table(teams_data):
    """International points table - blue themed, no FPP column"""
    try:
        width = 1400
        header_height = 80
        row_height = 90
        top_padding = 40
        total_height = top_padding + header_height + (len(teams_data) * row_height) + 80

        img = Image.new('RGB', (width, total_height), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Blue gradient background
        for y in range(total_height):
            ratio = y / total_height
            r = int(5 + (20 - 5) * ratio)
            g = int(30 + (60 - 30) * ratio)
            b = int(100 + (160 - 100) * ratio)
            draw.rectangle([(0, y), (width, y+1)], fill=(r, g, b))

        try:
            title_font = ImageFont.truetype("nor.otf", 70)
            header_font = ImageFont.truetype("nor.otf", 42)
            cell_font = ImageFont.truetype("nor.otf", 40)
            footer_font = ImageFont.truetype("nor.otf", 38)
        except:
            title_font = ImageFont.load_default()
            header_font = title_font
            cell_font = title_font
            footer_font = title_font

        # Title
        title_text = "International Rankings"
        title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        draw.text(((width - title_width) // 2, 10), title_text, fill=(255, 255, 255), font=title_font)

        cols = {
            'pos': 50,
            'flag': 120,
            'team': 200,
            'wins': 680,
            'pts': 800,
            'matches': 920,
            'losses': 1040,
            'nrr': 1160,
        }

        # Header row - white on dark blue
        header_y = top_padding + 70
        header_bg = Image.new('RGB', (width, 60), (0, 50, 120))
        header_draw = ImageDraw.Draw(header_bg)
        for x in range(width):
            progress = x / width
            r = int(0 + (30 - 0) * progress)
            g = int(80 + (120 - 80) * progress)
            b = int(200 + (255 - 200) * progress)
            header_draw.line([(x, 0), (x, 60)], fill=(r, g, b))
        img.paste(header_bg, (0, header_y))

        headers = {
            'pos': 'POS', 'team': 'TEAM', 'wins': 'W',
            'pts': 'PTS', 'matches': 'M', 'losses': 'L', 'nrr': 'NRR'
        }
        for key, text in headers.items():
            draw.text((cols[key], header_y + 12), text, fill=(255, 255, 255), font=header_font)

        # Download flags
        flag_cache = {}
        async with aiohttp.ClientSession() as session:
            for team_data in teams_data:
                team_name = team_data[0]
                flag_url = get_team_flag_url(team_name)
                if flag_url and team_name not in flag_cache:
                    try:
                        async with session.get(flag_url) as resp:
                            if resp.status == 200:
                                flag_data = await resp.read()
                                flag_img = Image.open(io.BytesIO(flag_data)).convert('RGBA')
                                flag_img = flag_img.resize((55, 55), Image.Resampling.LANCZOS)
                                flag_cache[team_name] = flag_img
                    except:
                        pass

        for idx, (team_name, points, matches, wins, losses, nrr, _) in enumerate(teams_data):
            row_y = header_y + 60 + (idx * row_height)

            # Alternating row - light blue tones
            if idx % 2 == 0:
                draw.rectangle([(0, row_y), (width, row_y + row_height)], fill=(20, 60, 140))
            else:
                draw.rectangle([(0, row_y), (width, row_y + row_height)], fill=(10, 40, 110))

            # Team color left accent bar
            team_color = get_team_color_rgb(team_name)
            for x in range(12):
                progress = x / 12
                for y in range(row_height):
                    r = int(team_color[0] * (1 - progress * 0.3))
                    g = int(team_color[1] * (1 - progress * 0.3))
                    b = int(team_color[2] * (1 - progress * 0.3))
                    draw.point((x, row_y + y), fill=(r, g, b))

            # Top 3 gold/silver/bronze highlight
            if idx == 0:
                highlight = (255, 215, 0, 40)
            elif idx == 1:
                highlight = (192, 192, 192, 30)
            elif idx == 2:
                highlight = (205, 127, 50, 30)
            else:
                highlight = None

            if highlight:
                hl = Image.new('RGBA', (width, row_height), highlight)
                img_rgba = img.convert('RGBA')
                img_rgba.paste(hl, (0, row_y), hl)
                img = img_rgba.convert('RGB')
                draw = ImageDraw.Draw(img)

            # Position
            pos_color = (255, 215, 0) if idx == 0 else (200, 200, 200) if idx == 1 else (205, 127, 50) if idx == 2 else (255, 255, 255)
            draw.text((cols['pos'], row_y + 25), str(idx + 1), fill=pos_color, font=cell_font)

            # Flag
            if team_name in flag_cache:
                img.paste(flag_cache[team_name], (cols['flag'], row_y + 18), flag_cache[team_name])

            # Team name
            draw.text((cols['team'], row_y + 25), team_name, fill=(255, 255, 255), font=cell_font)

            # Wins - green
            draw.text((cols['wins'], row_y + 25), str(wins), fill=(100, 255, 100), font=cell_font)

            # Points - yellow
            draw.text((cols['pts'], row_y + 25), str(points), fill=(255, 215, 0), font=cell_font)

            # Matches
            draw.text((cols['matches'], row_y + 25), str(matches), fill=(255, 255, 255), font=cell_font)

            # Losses - red
            draw.text((cols['losses'], row_y + 25), str(losses), fill=(255, 100, 100), font=cell_font)

            # NRR
            nrr_color = (100, 255, 100) if nrr >= 0 else (255, 100, 100)
            draw.text((cols['nrr'], row_y + 25), f"{nrr:+.3f}", fill=nrr_color, font=cell_font)

            # Divider
            draw.line([(0, row_y + row_height - 1), (width, row_y + row_height - 1)], fill=(50, 80, 180), width=1)

        output = io.BytesIO()
        img.save(output, format='PNG', quality=95)
        output.seek(0)
        return output

    except Exception as e:
        print(f"Error creating international points table: {e}")
        import traceback
        traceback.print_exc()
        return None

async def create_points_table_image(tournament_name, teams_data):
    """Create a beautiful points table image with team gradients and dividers"""
    try:
        # Image dimensions
        width = 1400
        header_height = 80  # Reduced from 120
        row_height = 90  # Increased from 80
        top_padding = 40  # Reduced from default
        total_height = top_padding + header_height + (len(teams_data) *
                                                      row_height) + 80

        # Create white background
        img = Image.new('RGB', (width, total_height), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Load fonts - ALL using nor.otf with BIGGER sizes
        try:
            title_font = ImageFont.truetype("nor.otf", 70)  # Increased from 60
            header_font = ImageFont.truetype("nor.otf",
                                             42)  # Increased from 36
            cell_font = ImageFont.truetype("nor.otf", 40)  # Increased from 32
            footer_font = ImageFont.truetype("nor.otf", 38)  # New
        except:
            title_font = ImageFont.load_default()
            header_font = ImageFont.load_default()
            cell_font = ImageFont.load_default()
            footer_font = ImageFont.load_default()

        # Draw title
        title_text = "Points Table"
        title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        draw.text(((width - title_width) // 2, 10),
                  title_text,
                  fill=(0, 0, 0),
                  font=title_font)

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
            draw.text((cols[key], header_y + 12),
                      text,
                      fill=(255, 255, 255),
                      font=header_font)

        # Download and cache flags
        flag_cache = {}
        async with aiohttp.ClientSession() as session:
            for team_data in teams_data:
                # Unpack with support for both 7 and 8 values
                if len(team_data) == 8:
                    team_name = team_data[0]
                else:
                    team_name = team_data[0]
                flag_url = get_team_flag_url(team_name)
                if flag_url and team_name not in flag_cache:
                    try:
                        async with session.get(flag_url) as resp:
                            if resp.status == 200:
                                flag_data = await resp.read()
                                flag_img = Image.open(
                                    io.BytesIO(flag_data)).convert('RGBA')
                                flag_img = flag_img.resize(
                                    (55, 55), Image.Resampling.LANCZOS
                                )  # Slightly bigger
                                flag_cache[team_name] = flag_img
                    except:
                        pass

        # Draw team rows
        for idx, team_data in enumerate(teams_data):
                # Unpack with support for both 7 and 8 values (with/without qualified)
            if len(team_data) == 8:
                team_name, points, matches, wins, losses, nrr, fpp, qualified = team_data
            else:
                team_name, points, matches, wins, losses, nrr, fpp = team_data
                qualified = 0
            row_y = header_y + 60 + (idx * row_height)

            # Alternate row colors
            if idx % 2 == 0:
                draw.rectangle([(0, row_y), (width, row_y + row_height)],
                               fill=(248, 248, 248))

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
            draw.text((cols['pos'], row_y + 25),
                      str(idx + 1),
                      fill=(0, 0, 0),
                      font=cell_font)

            # Flag
            if team_name in flag_cache:
                img.paste(flag_cache[team_name], (cols['flag'], row_y + 18),
                          flag_cache[team_name])

            # Team name with (Q) prefix if qualified
            display_name = f"(Q) {team_name}" if qualified else team_name
            draw.text((cols['team'], row_y + 25),
                      display_name,
                      fill=(0, 128, 0) if qualified else (0, 0, 0),
                      font=cell_font)

            # Stats (rest remains the same)
            draw.text((cols['pts'], row_y + 25),
                      str(points),
                      fill=(0, 128, 0),
                      font=cell_font)
            draw.text((cols['matches'], row_y + 25),
                      str(matches),
                      fill=(0, 0, 0),
                      font=cell_font)
            draw.text((cols['wins'], row_y + 25),
                      str(wins),
                      fill=(0, 0, 0),
                      font=cell_font)
            draw.text((cols['losses'], row_y + 25),
                      str(losses),
                      fill=(0, 0, 0),
                      font=cell_font)

            # NRR with color
            nrr_color = (0, 128, 0) if nrr >= 0 else (255, 0, 0)
            draw.text((cols['nrr'], row_y + 25),
                      f"{nrr:+.3f}",
                      fill=nrr_color,
                      font=cell_font)

            # FPP
            fpp_color = (0, 128, 0) if fpp >= 0 else (255, 128, 0)
            draw.text((cols['fpp'], row_y + 25),
                      f"{fpp:+d}",
                      fill=fpp_color,
                      font=cell_font)

            # Draw divider line
            draw.line([(0, row_y + row_height - 1),
                       (width, row_y + row_height - 1)],
                      fill=(200, 200, 200),
                      width=2)

        # Footer
        footer_y = header_y + 60 + (len(teams_data) * row_height) + 15
        footer_text = " "
        footer_bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
        footer_width = footer_bbox[2] - footer_bbox[0]
        draw.text(((width - footer_width) // 2, footer_y),
                  footer_text,
                  fill=(100, 100, 100),
                  font=footer_font)

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
    """Get all matchups that have already been scheduled (including reserved and played)"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(
        """SELECT team1, team2 FROM fixtures 
                WHERE tournament_id = ?""", (tournament_id, ))
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
                discord.SelectOption(label=label,
                                     value=team,
                                     emoji=flag,
                                     description="Selected"
                                     if is_selected else "Click to select"))

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
            await interaction.response.send_message("❌ This is not your menu!",
                                                    ephemeral=True)
            return

        selected_values = interaction.data['values']
        self.selected_teams = selected_values

        self.add_team_select()

        embed = discord.Embed(
            title=f"🏆 Creating Tournament: {self.tournament_name}",
            description=f"**Selected Teams ({len(self.selected_teams)}):**\n" +
            "\n".join([f"{get_team_flag(t)} {t}" for t in self.selected_teams])
            if self.selected_teams else "No teams selected yet.",
            color=0x00FF00)
        embed.set_footer(
            text="Select teams from the dropdown • Click Confirm when done")

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="✅ Confirm Selection",
                       style=discord.ButtonStyle.success,
                       custom_id="confirm")
    async def confirm_button(self, interaction: discord.Interaction,
                             button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!",
                                                    ephemeral=True)
            return

        if len(self.selected_teams) < 2:
            await interaction.response.send_message(
                "❌ You need at least 2 teams for a tournament!",
                ephemeral=True)
            return

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        try:
            c.execute("UPDATE tournaments SET is_active = 0")
            c.execute(
                "INSERT INTO tournaments (name, current_round) VALUES (?, 0)",
                (self.tournament_name, ))
            tournament_id = c.lastrowid

            for team in self.selected_teams:
                c.execute(
                    """INSERT INTO tournament_teams 
                           (tournament_id, team_name) VALUES (?, ?)""",
                    (tournament_id, team))

            conn.commit()

            embed = discord.Embed(
                title="✅ Tournament Created!",
                description=
                f"**{self.tournament_name}**\n\n**Participating Teams:**\n" +
                "\n".join(
                    [f"{get_team_flag(t)} {t}" for t in self.selected_teams]),
                color=0x00FF00)
            embed.set_footer(
                text=
                f"Tournament ID: {tournament_id} • Use -setfixtures to create Round 1 fixtures"
            )

            for item in self.children:
                item.disabled = True

            await interaction.response.edit_message(embed=embed, view=self)

        except sqlite3.IntegrityError:
            await interaction.response.send_message(
                f"❌ A tournament named '{self.tournament_name}' already exists!",
                ephemeral=True)
        finally:
            conn.close()


# Fixture Editing View
class FixtureEditView(View):

    def __init__(self, ctx, bot, tournament_id, fixtures, round_number,
                 available_teams):
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
        for idx, (team1, team2, channel_id,
                  stadium) in enumerate(self.fixtures):
            flag1 = get_team_flag(team1)
            flag2 = get_team_flag(team2)
            fixture_options.append(
                discord.SelectOption(label=f"{team1} vs {team2}",
                                     value=str(idx),
                                     emoji="🔄"))

        if fixture_options:
            fixture_select = Select(placeholder="🔄 Select fixture to edit",
                                    options=fixture_options,
                                    custom_id="fixture_select")
            fixture_select.callback = self.fixture_callback
            self.add_item(fixture_select)

        self.add_item(self.confirm_button)

    async def fixture_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!",
                                                    ephemeral=True)
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
            if matchup not in played_matchups or team == self.fixtures[
                    fixture_idx][0]:
                team1_options.append(
                    discord.SelectOption(label=team,
                                         value=team,
                                         emoji=get_team_flag(team)))

        if team1_options:
            team1_select = Select(placeholder="Select Team 1",
                                  options=team1_options[:25],
                                  custom_id="team1_select")

            async def team1_callback(inter: discord.Interaction):
                if inter.user.id != self.ctx.author.id:
                    await inter.response.send_message(
                        "❌ This is not your menu!", ephemeral=True)
                    return

                new_team1 = inter.data['values'][0]
                self.fixtures[fixture_idx][0] = new_team1

                # Defer the ephemeral response
                await inter.response.defer(ephemeral=True)

                # Update the main view
                self.add_controls()
                embed = await self.create_fixture_embed()
                await self.message.edit(embed=embed, view=self)

                # Send confirmation
                await inter.followup.send(f"✅ Team 1 changed to {new_team1}",
                                          ephemeral=True)

                try:
                    await interaction.delete_original_response()
                except:
                    pass

            team1_select.callback = team1_callback
            edit_view.add_item(team1_select)

        # Team 2 selection
        team2_options = []
        current_team1 = self.fixtures[fixture_idx][0]

        for team in self.available_teams:
            matchup = frozenset([current_team1, team])
            if matchup not in played_matchups or team == self.fixtures[
                    fixture_idx][1]:
                team2_options.append(
                    discord.SelectOption(label=team,
                                         value=team,
                                         emoji=get_team_flag(team)))

        if team2_options:
            team2_select = Select(placeholder="Select Team 2",
                                  options=team2_options[:25],
                                  custom_id="team2_select")

            async def team2_callback(inter: discord.Interaction):
                if inter.user.id != self.ctx.author.id:
                    await inter.response.send_message(
                        "❌ This is not your menu!", ephemeral=True)
                    return

                new_team2 = inter.data['values'][0]
                self.fixtures[fixture_idx][1] = new_team2

                # Defer the ephemeral response
                await inter.response.defer(ephemeral=True)

                # Update the main view
                self.add_controls()
                embed = await self.create_fixture_embed()
                await self.message.edit(embed=embed, view=self)

                # Send confirmation
                await inter.followup.send(f"✅ Team 2 changed to {new_team2}",
                                          ephemeral=True)

                try:
                    await interaction.delete_original_response()
                except:
                    pass

            team2_select.callback = team2_callback
            edit_view.add_item(team2_select)

        # Stadium selection
        stadium_options = []
        for channel_id, stadium_name in MATCH_CHANNELS.items():
            stadium_options.append(
                discord.SelectOption(label=stadium_name,
                                     value=str(channel_id),
                                     emoji="🏟️"))

        stadium_select = Select(placeholder="Select Stadium",
                                options=stadium_options,
                                custom_id="stadium_select")

        async def stadium_callback(inter: discord.Interaction):
            if inter.user.id != self.ctx.author.id:
                await inter.response.send_message("❌ This is not your menu!",
                                                  ephemeral=True)
                return

            new_channel_id = int(inter.data['values'][0])
            new_stadium = MATCH_CHANNELS[new_channel_id]
            self.fixtures[fixture_idx][2] = new_channel_id
            self.fixtures[fixture_idx][3] = new_stadium

            # Defer the ephemeral response
            await inter.response.defer(ephemeral=True)

            # Update the main view
            self.add_controls()
            embed = await self.create_fixture_embed()
            await self.message.edit(embed=embed, view=self)

            # Send confirmation
            await inter.followup.send(f"✅ Stadium changed to {new_stadium}",
                                      ephemeral=True)

            try:
                await interaction.delete_original_response()
            except:
                pass

        stadium_select.callback = stadium_callback
        edit_view.add_item(stadium_select)

        await interaction.response.send_message(
            f"Editing fixture {fixture_idx + 1}:",
            view=edit_view,
            ephemeral=True)

    async def create_fixture_embed(self):
        tournament = get_active_tournament()
        tournament_name = tournament[1] if tournament else "Tournament"

        embed = discord.Embed(
            title=f"🏆 {tournament_name} - Round {self.round_number} Fixtures",
            description=
            f"**Total Matches:** {len(self.fixtures)}\n\n**Fixture List:**",
            color=0x0066CC)

        fixture_text = ""
        for idx, (team1, team2, channel_id,
                  stadium) in enumerate(self.fixtures, 1):
            flag1 = get_team_flag(team1)
            flag2 = get_team_flag(team2)
            fixture_text += f"**{idx}.** {flag1} {team1} vs {flag2} {team2}\n    🏟️ {stadium}\n\n"

        embed.description += f"\n{fixture_text}"
        embed.set_footer(
            text=
            "Select fixture to edit teams/stadium • Click Confirm when ready")

        return embed

    @discord.ui.button(label="✅ Confirm & Post Fixtures",
                       style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction,
                             button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!",
                                                    ephemeral=True)
            return

        await interaction.response.defer()

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        for team1, team2, channel_id, stadium in self.fixtures:
            c.execute(
                """INSERT INTO fixtures 
                       (tournament_id, round_number, team1, team2, channel_id)
                       VALUES (?, ?, ?, ?, ?)""",
                (self.tournament_id, self.round_number, team1, team2,
                 channel_id))

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
                title=f"{tournament_name} - Round {self.round_number}",
                color=0x00FF00)

            flag1 = get_team_flag(team1)
            flag2 = get_team_flag(team2)

            embed.add_field(
                name="Match",
                value=f"{flag1} **{team1}** vs {flag2} **{team2}**",
                inline=False)

            # Link to the stadium channel
            embed.add_field(name="Stadium",
                            value=f"🏟️ <#{channel_id}>",
                            inline=False)

            embed.set_footer(text="TourneyFanHub")

            role1_id = get_team_role_id(team1)
            role2_id = get_team_role_id(team2)

            ping_text = ""
            if role1_id:
                ping_text += f"<@&{role1_id}> "
            if role2_id:
                ping_text += f"<@&{role2_id}> "

            if vs_image:
                file = discord.File(vs_image,
                                    filename=f"{team1}_vs_{team2}.png")
                embed.set_image(url=f"attachment://{team1}_vs_{team2}.png")

                if ping_text:
                    await fixtures_channel.send(content=ping_text,
                                                embed=embed,
                                                file=file)
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

    @commands.command(name="createtournament",
                      aliases=["ct"],
                      help="[ADMIN] Create a new tournament")
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
            description=
            "Select the teams that will participate in this tournament.",
            color=0x0066CC)
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

        # Check if qualified column exists
        c.execute("PRAGMA table_info(tournament_teams)")
        columns = [column[1] for column in c.fetchall()]

        if 'qualified' in columns:
            c.execute(
                """SELECT team_name, points, matches_played, wins, losses, nrr, fpp, qualified
                    FROM tournament_teams 
                    WHERE tournament_id = ?
                    ORDER BY points DESC, nrr DESC""", (tournament_id, ))
        else:
            c.execute(
                """SELECT team_name, points, matches_played, wins, losses, nrr, fpp, 0 as qualified
                    FROM tournament_teams 
                    WHERE tournament_id = ?
                    ORDER BY points DESC, nrr DESC""", (tournament_id, ))

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

        embed = discord.Embed(title=f"🏆 {tournament_name}", color=0xFFD700)
        embed.set_image(url="attachment://points_table.png")
        embed.set_footer(text="TOP 8 QUALIFY")

        await ctx.send(embed=embed, file=file)

    @commands.command(name="createspecialround", aliases=["csr"], help="[ADMIN] Create a special round (e.g., Quarter Finals)")
    @commands.has_permissions(administrator=True)
    async def createspecialround(self, ctx, *, round_name: str):
        """Create a special named round for playoffs/knockouts"""
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, _ = tournament

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Check if this special round already exists
        c.execute("""SELECT COUNT(*) FROM fixtures 
                    WHERE tournament_id = ? AND round_number = -1 
                    AND winner = ?""",
                  (tournament_id, round_name))

        exists = c.fetchone()[0] > 0

        if exists:
            await ctx.send(f"❌ Special round '{round_name}' already exists!")
            conn.close()
            return

        conn.close()

        embed = discord.Embed(
            title="✅ Special Round Created",
            description=f"**{round_name}** has been created for {tournament_name}\n\n"
                        f"Use `-fm <team1> <team2> {round_name}` to add fixtures to this round.",
            color=0x00FF00
        )

        await ctx.send(embed=embed)

    @commands.command(name="fixturemake", aliases=["fm"], help="[ADMIN] Manually create a single fixture")
    @commands.has_permissions(administrator=True)
    async def fixturemake(self, ctx, team1: str, team2: str, *, special_round: str = None):
        """Manually create a fixture between two teams for the next round or a special round"""
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, current_round = tournament

        # Determine round info
        if special_round:
            # Using special round (e.g., "Quarter Finals")
            round_number = -1  # Special marker for named rounds
            round_display = special_round
            is_special = True
        else:
            # Regular numbered round
            round_number = current_round + 1
            round_display = f"Round {round_number}"
            is_special = False

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
        if is_special:
            c.execute("""SELECT id, is_reserved FROM fixtures 
                        WHERE tournament_id = ? AND round_number = -1 AND winner = ?
                        AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))""",
                      (tournament_id, special_round, team1, team2, team2, team1))
        else:
            c.execute("""SELECT id, round_number, is_reserved FROM fixtures 
                        WHERE tournament_id = ? 
                        AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))""",
                      (tournament_id, team1, team2, team2, team1))

        existing = c.fetchone()

        is_reserve = False
        if existing:
            # If fixture exists, mark it as reserved
            fixture_id = existing[0]
            c.execute("UPDATE fixtures SET is_reserved = 1 WHERE id = ?", (fixture_id,))
            conn.commit()
            is_reserve = True
            await ctx.send(f"ℹ️ Fixture already exists - marking as **Reserve Match**. Select a stadium below:")

        conn.close()

        # Create stadium selection view
        class StadiumSelectView(View):
            def __init__(self):
                super().__init__(timeout=60)
                self.selected_channel_id = None
                self.add_stadium_select()

            def add_stadium_select(self):
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
                    placeholder="🏟️ Select Stadium",
                    options=stadium_options,
                    custom_id="stadium_select"
                )
                stadium_select.callback = self.stadium_callback
                self.add_item(stadium_select)

            async def stadium_callback(self, interaction: discord.Interaction):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
                    return

                self.selected_channel_id = int(interaction.data['values'][0])
                stadium = MATCH_CHANNELS[self.selected_channel_id]

                await interaction.response.defer()

                conn = sqlite3.connect('players.db')
                c = conn.cursor()

                # If it's a new fixture (not reserve), create it
                if not is_reserve:
                    if is_special:
                        # Store special round name in the winner column (temporary storage)
                        c.execute("""INSERT INTO fixtures 
                                   (tournament_id, round_number, team1, team2, channel_id, winner)
                                   VALUES (?, -1, ?, ?, ?, ?)""",
                                  (tournament_id, team1, team2, self.selected_channel_id, special_round))
                    else:
                        c.execute("""INSERT INTO fixtures 
                                   (tournament_id, round_number, team1, team2, channel_id)
                                   VALUES (?, ?, ?, ?, ?)""",
                                  (tournament_id, round_number, team1, team2, self.selected_channel_id))
                else:
                    # Update the channel for the existing reserved fixture
                    c.execute("""UPDATE fixtures 
                               SET channel_id = ?
                               WHERE tournament_id = ? 
                               AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))""",
                              (self.selected_channel_id, tournament_id, team1, team2, team2, team1))

                conn.commit()
                conn.close()

                # Create and post the fixture
                vs_image = await create_vs_image(team1, team2, stadium)

                # Use special round name if applicable
                if is_special:
                    embed_title = f"🏆 {tournament_name} - {special_round}"
                elif is_reserve:
                    embed_title = f"📌 {tournament_name} - Reserve Match"
                else:
                    embed_title = f"🏏 {tournament_name} - Round {round_number}"

                embed = discord.Embed(
                    title=embed_title,
                    color=0xFFD700 if is_special else (0xFFA500 if is_reserve else 0x00FF00)
                )

                flag1 = get_team_flag(team1)
                flag2 = get_team_flag(team2)

                embed.add_field(
                    name="Match",
                    value=f"[ {flag1} ] **{team1}** vs [ {flag2} ] **{team2}**",
                    inline=False
                )

                embed.add_field(
                    name="Stadium",
                    value=f"🏟️ : <#{self.selected_channel_id}>",
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

                # Disable the view
                for item in self.children:
                    item.disabled = True

                success_msg = f"✅ Fixture created: **{team1}** vs **{team2}** ({round_display}) at {stadium}"
                if is_reserve:
                    success_msg = f"✅ Reserve match updated: **{team1}** vs **{team2}** at {stadium}"

                await interaction.message.edit(content=success_msg, view=self)

        # Send stadium selection
        flag1 = get_team_flag(team1)
        flag2 = get_team_flag(team2)

        select_embed = discord.Embed(
            title="🏟️ Select Stadium",
            description=f"**Match:** {flag1} {team1} vs {flag2} {team2}\n"
                        f"**Type:** {round_display}\n\n"
                        f"Select a stadium for this fixture:",
            color=0xFFD700 if is_special else (0xFFA500 if is_reserve else 0x0066CC)
        )

        view = StadiumSelectView()
        await ctx.send(embed=select_embed, view=view)

    @commands.command(name="setfixtures",
                      aliases=["sf"],
                      help="[ADMIN] Generate tournament fixtures")
    @commands.has_permissions(administrator=True)
    async def setfixtures(self, ctx):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, current_round = tournament

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Determine the target round based on unplayed matches
        c.execute(
            "SELECT MAX(round_number) FROM fixtures WHERE tournament_id = ?",
            (tournament_id, ))
        max_round_row = c.fetchone()
        max_round = max_round_row[0] if max_round_row[0] is not None else 0

        if max_round > 0:
            c.execute(
                "SELECT COUNT(*) FROM fixtures WHERE tournament_id = ? AND round_number = ? AND is_played = 0 AND is_reserved = 0",
                (tournament_id, max_round))
            unplayed_in_max = c.fetchone()[0]

            if unplayed_in_max > 0:
                target_round = max_round
            else:
                target_round = max_round + 1
        else:
            target_round = 1

        # Update current_round if needed
        if current_round != target_round:
            c.execute("UPDATE tournaments SET current_round = ? WHERE id = ?",
                      (target_round, tournament_id))
            current_round = target_round

        c.execute(
            "SELECT team_name FROM tournament_teams WHERE tournament_id = ?",
            (tournament_id, ))
        all_teams = [row[0] for row in c.fetchall()]

        # Get teams that already have fixtures in this target round
        c.execute(
            """SELECT DISTINCT team1, team2 FROM fixtures 
                    WHERE tournament_id = ? AND round_number = ?""",
            (tournament_id, target_round))
        existing_fixtures = c.fetchall()

        teams_with_fixtures = set()
        for t1, t2 in existing_fixtures:
            teams_with_fixtures.add(t1)
            teams_with_fixtures.add(t2)

        if len(teams_with_fixtures) < len(all_teams):
            available_teams = [
                t for t in all_teams if t not in teams_with_fixtures
            ]

            if len(available_teams) < 2:
                await ctx.send(
                    f"✅ All teams already have fixtures for Round {target_round}!"
                )
                conn.close()
                return

            # Get matchups that have been scheduled in ANY round
            c.execute(
                """SELECT team1, team2 FROM fixtures 
                        WHERE tournament_id = ?""", (tournament_id, ))
            all_scheduled_matchups = c.fetchall()
            conn.close()

            played_matchups = {
                frozenset([t1, t2])
                for t1, t2 in all_scheduled_matchups
            }

            # Build adjacency graph
            graph = {team: [] for team in available_teams}
            for team in available_teams:
                for other in available_teams:
                    if team != other and frozenset([team, other
                                                    ]) not in played_matchups:
                        graph[team].append(other)

            # Greedy matching with backtracking
            def find_perfect_matching(teams_left, matches_so_far, depth=0):
                if not teams_left:
                    return matches_so_far

                if len(teams_left) == 1:
                    return None  # Odd number, can't match

                # Pick team with fewest options (most constrained first)
                team_constraints = []
                for team in teams_left:
                    available_opponents = [
                        opp for opp in graph[team] if opp in teams_left
                    ]
                    team_constraints.append(
                        (len(available_opponents), team, available_opponents))

                team_constraints.sort(
                )  # Sort by number of options (ascending)

                if team_constraints[0][0] == 0:
                    # Dead end - a team has no valid opponents
                    return None

                num_options, first_team, opponents = team_constraints[0]

                # Try each possible opponent for this team
                for opponent in opponents:
                    # Create new state
                    new_teams_left = [
                        t for t in teams_left
                        if t != first_team and t != opponent
                    ]
                    new_matches = matches_so_far + [(first_team, opponent)]

                    # Recurse
                    result = find_perfect_matching(new_teams_left, new_matches,
                                                   depth + 1)
                    if result is not None:
                        return result

                # No valid solution from this state
                return None

            # Try to find matching
            matching_result = None

            # Try multiple times with different random orderings
            for attempt in range(20):
                shuffled = available_teams.copy()
                random.shuffle(shuffled)
                matching_result = find_perfect_matching(shuffled, [])
                if matching_result:
                    break

            if not matching_result:
                debug_info = "**Debug Info:**\n"
                for team in available_teams:
                    opponents = graph[team]
                    debug_info += f"`{team}` can play: {', '.join(opponents) if opponents else 'NONE'}\n"

                await ctx.send(
                    f"❌ Could not find a valid set of matches for Round {target_round}!\n"
                    f"**Teams needing fixtures:** {', '.join(available_teams)}\n\n"
                    f"{debug_info}\n"
                    f"Try using `-fixturemake <team1> <team2>` to manually create fixtures."
                )
                return

            fixtures = []
            for t1, t2 in matching_result:
                channel_id = random.choice(list(MATCH_CHANNELS.keys()))
                stadium = MATCH_CHANNELS[channel_id]
                fixtures.append([t1, t2, channel_id, stadium])

            embed = await FixtureEditView(ctx, self.bot, tournament_id,
                                          fixtures, target_round,
                                          all_teams).create_fixture_embed()
            view = FixtureEditView(ctx, self.bot, tournament_id, fixtures,
                                   target_round, all_teams)
            view.message = await ctx.send(embed=embed, view=view)
        else:
            await ctx.send(
                f"✅ All teams already have fixtures for Round {target_round}!")

    @commands.command(
        name="reserveall",
        help="[ADMIN] Reserve all unplayed matches in the current round")
    @commands.has_permissions(administrator=True)
    async def reserveall(self, ctx):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, current_round = tournament

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        c.execute(
            """UPDATE fixtures 
                    SET is_reserved = 1 
                    WHERE tournament_id = ? AND round_number = ? AND is_played = 0""",
            (tournament_id, current_round))

        count = c.rowcount
        conn.commit()
        conn.close()

        if count == 0:
            await ctx.send(
                f"❌ No unplayed fixtures found in Round {current_round} to reserve!"
            )
        else:
            await ctx.send(
                f"✅ Successfully reserved **{count}** matches in Round {current_round}!"
            )

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

        c.execute(
            """UPDATE tournament_teams 
                    SET fpp = fpp + ?
                    WHERE tournament_id = ? AND team_name = ?""",
            (fpp_change, tournament_id, team_name))

        if c.rowcount == 0:
            await ctx.send(f"❌ Team '{team_name}' not found in the tournament!"
                           )
            conn.close()
            return

        conn.commit()

        c.execute(
            "SELECT fpp FROM tournament_teams WHERE tournament_id = ? AND team_name = ?",
            (tournament_id, team_name))
        new_fpp = c.fetchone()[0]
        conn.close()

        flag = get_team_flag(team_name)
        embed = discord.Embed(
            title="✅ FPP Updated",
            description=
            f"{flag} **{team_name}**\n\nFPP Change: **{fpp_change:+d}**\nNew FPP: **{new_fpp:+d}**",
            color=get_team_color(team_name))

        await ctx.send(embed=embed)

    @commands.command(name="reservematch", aliases=["rm"], help="[ADMIN] Mark a match as reserved")
    @commands.has_permissions(administrator=True)
    async def reservematch(self, ctx, team1: str, team2: str):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, current_round = tournament

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

        # Find ANY fixture between these teams, regardless of status
        c.execute("""SELECT id, is_played, is_reserved FROM fixtures 
                    WHERE tournament_id = ? 
                    AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))
                    ORDER BY round_number DESC
                    LIMIT 1""",
                  (tournament_id, team1, team2, team2, team1))

        fixture = c.fetchone()

        status_msg = ""

        if not fixture:
            # Create a new fixture as reserved
            next_round = current_round + 1
            channel_id = random.choice(list(MATCH_CHANNELS.keys()))

            c.execute("""INSERT INTO fixtures 
                       (tournament_id, round_number, team1, team2, channel_id, is_reserved)
                       VALUES (?, ?, ?, ?, ?, 1)""",
                      (tournament_id, next_round, team1, team2, channel_id))

            conn.commit()
            status_msg = f"\n✅ New reserved fixture created for Round {next_round}."
        else:
            fixture_id, is_played, is_reserved = fixture

            # Force reserve regardless of current status
            c.execute("UPDATE fixtures SET is_reserved = 1 WHERE id = ?", (fixture_id,))
            conn.commit()

            if is_played:
                status_msg = "\n⚠️ This match was already played but has been reserved anyway."
            elif is_reserved:
                status_msg = "\nℹ️ This match was already reserved."

        conn.close()

        flag1 = get_team_flag(team1)
        flag2 = get_team_flag(team2)

        embed = discord.Embed(
            title="📌 Match Reserved",
            description=f"{flag1} **{team1}** vs {flag2} **{team2}**\n\nThis match will be played later.{status_msg}",
            color=0xFFA500
        )

        await ctx.send(embed=embed)

    @commands.command(name="unreserve",
                      help="[ADMIN] Remove reserve status from a match")
    @commands.has_permissions(administrator=True)
    async def unreserve(self, ctx, team1: str, team2: str):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id = tournament[0]

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        c.execute(
            """UPDATE fixtures SET is_reserved = 0
                    WHERE tournament_id = ? 
                    AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))
                    AND is_reserved = 1""",
            (tournament_id, team1, team2, team2, team1))

        if c.rowcount == 0:
            await ctx.send(
                f"❌ No reserved match found between {team1} and {team2}!")
            conn.close()
            return

        conn.commit()
        conn.close()

        await ctx.send(
            f"✅ Match between **{team1}** and **{team2}** is no longer reserved!"
        )

    @commands.command(name="deletetournament",
                      aliases=["dt"],
                      help="[ADMIN] Delete the current tournament")
    @commands.has_permissions(administrator=True)
    async def deletetournament(self, ctx):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, _ = tournament

        embed = discord.Embed(
            title="⚠️ Delete Tournament?",
            description=
            f"Are you sure you want to delete **{tournament_name}**?\n\n"
            "This will delete:\n"
            "• All team data\n"
            "• All fixtures\n"
            "• All points and statistics\n\n"
            "**This action cannot be undone!**",
            color=0xFF0000)

        view = View(timeout=60)

        async def confirm_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "❌ Only the command author can confirm!", ephemeral=True)
                return

            conn = sqlite3.connect('players.db')
            c = conn.cursor()

            c.execute("DELETE FROM fixtures WHERE tournament_id = ?",
                      (tournament_id, ))
            c.execute("DELETE FROM tournament_teams WHERE tournament_id = ?",
                      (tournament_id, ))
            c.execute("DELETE FROM tournaments WHERE id = ?",
                      (tournament_id, ))

            conn.commit()
            conn.close()

            await interaction.response.edit_message(
                content=f"✅ Tournament **{tournament_name}** has been deleted!",
                embed=None,
                view=None)

        async def cancel_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "❌ Only the command author can cancel!", ephemeral=True)
                return

            await interaction.response.edit_message(
                content="❌ Tournament deletion cancelled.",
                embed=None,
                view=None)

        confirm_btn = Button(label="✅ Confirm Delete",
                             style=discord.ButtonStyle.danger)
        cancel_btn = Button(label="❌ Cancel",
                            style=discord.ButtonStyle.secondary)

        confirm_btn.callback = confirm_callback
        cancel_btn.callback = cancel_callback

        view.add_item(confirm_btn)
        view.add_item(cancel_btn)

        await ctx.send(embed=embed, view=view)

    @commands.command(name="clearfixtures",
                      aliases=["clearf"],
                      help="[ADMIN] Clear all fixtures")
    @commands.has_permissions(administrator=True)
    async def clearfixtures(self, ctx):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id = tournament[0]

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("DELETE FROM fixtures WHERE tournament_id = ?",
                  (tournament_id, ))
        deleted = c.rowcount

        c.execute("UPDATE tournaments SET current_round = 0 WHERE id = ?",
                  (tournament_id, ))

        conn.commit()
        conn.close()

        await ctx.send(
            f"✅ Cleared **{deleted}** fixtures and reset tournament to Round 0!"
        )

    @commands.command(name="setnrr", help="[ADMIN] Set NRR for a team")
    @commands.has_permissions(administrator=True)
    async def setnrr(self, ctx, team_name: str, nrr: float):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id = tournament[0]

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Get old NRR before updating
        c.execute(
            """SELECT nrr FROM tournament_teams 
                    WHERE tournament_id = ? AND team_name = ?""",
            (tournament_id, team_name))

        result = c.fetchone()

        if not result:
            await ctx.send(f"❌ Team '{team_name}' not found in the tournament!"
                           )
            conn.close()
            return

        old_nrr = result[0]

        # Update NRR
        c.execute(
            """UPDATE tournament_teams 
                    SET nrr = ?
                    WHERE tournament_id = ? AND team_name = ?""",
            (nrr, tournament_id, team_name))

        conn.commit()
        conn.close()

        flag = get_team_flag(team_name)
        embed = discord.Embed(
            title="✅ NRR Updated",
            description=
            f"{flag} **{team_name}**\n\nOld NRR: **{old_nrr:+.3f}**\nNew NRR: **{nrr:+.3f}**",
            color=get_team_color(team_name))

        await ctx.send(embed=embed)

    @commands.command(name="resetleaderboard",
                      aliases=["resetlb"],
                      help="[ADMIN] Reset the tournament leaderboard")
    @commands.has_permissions(administrator=True)
    async def resetleaderboard(self, ctx):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, _ = tournament

        embed = discord.Embed(
            title="⚠️ Reset Leaderboard?",
            description=
            f"Are you sure you want to reset the leaderboard for **{tournament_name}**?\n\n"
            "This will reset:\n"
            "• All points to 0\n"
            "• All matches played to 0\n"
            "• All wins/losses to 0\n"
            "• All NRR to 0.0\n"
            "• All FPP to 0\n\n"
            "**Teams will remain in the tournament, but all stats will be cleared!**",
            color=0xFF0000)

        view = View(timeout=60)

        async def confirm_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "❌ Only the command author can confirm!", ephemeral=True)
                return

            conn = sqlite3.connect('players.db')
            c = conn.cursor()

            # Reset all team stats
            c.execute(
                """UPDATE tournament_teams 
                        SET points = 0, 
                            matches_played = 0, 
                            wins = 0, 
                            losses = 0, 
                            nrr = 0.0, 
                            fpp = 0
                        WHERE tournament_id = ?""", (tournament_id, ))

            teams_reset = c.rowcount

            conn.commit()
            conn.close()

            success_embed = discord.Embed(
                title="✅ Leaderboard Reset Complete",
                description=f"**{tournament_name}**\n\n"
                f"Reset stats for **{teams_reset}** teams.\n"
                "All points, matches, wins, losses, NRR, and FPP have been set to 0.",
                color=0x00FF00)

            await interaction.response.edit_message(embed=success_embed,
                                                    view=None)

        async def cancel_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "❌ Only the command author can cancel!", ephemeral=True)
                return

            await interaction.response.edit_message(
                content="❌ Leaderboard reset cancelled.",
                embed=None,
                view=None)

        confirm_btn = Button(label="✅ Confirm Reset",
                             style=discord.ButtonStyle.danger)
        cancel_btn = Button(label="❌ Cancel",
                            style=discord.ButtonStyle.secondary)

        confirm_btn.callback = confirm_callback
        cancel_btn.callback = cancel_callback

        view.add_item(confirm_btn)
        view.add_item(cancel_btn)

        await ctx.send(embed=embed, view=view)

    @commands.command(name="round",
          aliases=["r"],
          help="View current round fixtures and stats")
    async def round_command(self, ctx):
        """Show latest posted fixtures with team stats and predictions"""

        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, current_round = tournament

        # Get user's team
        user_team = get_user_team(ctx.author.id)

        if not user_team:
            await ctx.send(
                "❌ You need to claim a player first to use this command!")
            return

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Find the latest unplayed match for user's team (including reserves)
        c.execute(
        """SELECT team1, team2, channel_id, is_played, round_number, is_reserved
             FROM fixtures 
             WHERE tournament_id = ? 
             AND (team1 = ? OR team2 = ?) 
             AND is_played = 0
             ORDER BY id DESC
             LIMIT 1""", (tournament_id, user_team, user_team))

        user_fixture_data = c.fetchone()

        if not user_fixture_data:
            await ctx.send(
                f"❌ Your team ({user_team}) doesn't have any upcoming fixtures!")
            conn.close()
            return

        user_team1, user_team2, user_channel_id, user_is_played, user_round, user_is_reserved = user_fixture_data
        user_fixture = (user_team1, user_team2, user_channel_id, user_is_played)

        # Get all unplayed fixtures (including reserves) for the dropdown
        c.execute(
            """SELECT team1, team2, channel_id, is_played 
                 FROM fixtures 
                 WHERE tournament_id = ? 
                 AND is_played = 0
                 ORDER BY id DESC""", (tournament_id,))
        fixtures = c.fetchall()

        conn.close()

        if not fixtures:
            fixtures = [user_fixture]

        # Create view with buttons for all fixtures
        view = RoundFixturesView(ctx, tournament_id, user_round, fixtures,
                         user_team, user_fixture)

        # Generate initial embed for user's fixture
        embed, image = await create_round_fixture_embed(user_fixture[0],
                                                user_fixture[1],
                                                user_fixture[2],
                                                tournament_name,
                                                user_round,
                                                user_team,
                                                ctx.guild,
                                                is_user_match=True)

        # Update title if it's a reserve match
        if user_is_reserved:
            embed.title = "📌 Your Reserve Match"

        if image:
            file = discord.File(image, filename="fixture.png")
            embed.set_image(url="attachment://fixture.png")
            view.message = await ctx.send(embed=embed, file=file, view=view)
        else:
            view.message = await ctx.send(embed=embed, view=view)

    @commands.command(
        name="remind",
        help="[ADMIN] Send match reminder DMs to players of two teams")
    @commands.has_permissions(administrator=True)
    async def remind(self, ctx, team1: str, team2: str):
        """Send DM reminders to all players of two teams about their match"""

        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, current_round = tournament

        # Verify both teams are in the tournament
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        c.execute(
            "SELECT team_name FROM tournament_teams WHERE tournament_id = ? AND team_name IN (?, ?)",
            (tournament_id, team1, team2))
        found_teams = [row[0] for row in c.fetchall()]

        if len(found_teams) != 2:
            missing = [t for t in [team1, team2] if t not in found_teams]
            await ctx.send(
                f"❌ Team(s) not found in tournament: {', '.join(missing)}")
            conn.close()
            return

        # Find the fixture between these teams
        c.execute(
            """SELECT round_number, channel_id, is_played 
                     FROM fixtures 
                     WHERE tournament_id = ? 
                     AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))
                     ORDER BY round_number DESC
                     LIMIT 1""", (tournament_id, team1, team2, team2, team1))

        fixture = c.fetchone()

        if not fixture:
            await ctx.send(f"❌ No fixture found between {team1} and {team2}!")
            conn.close()
            return

        round_number, channel_id, is_played = fixture

        # Get all players from both teams
        import json
        try:
            with open('players.json', 'r', encoding='utf-8') as f:
                teams_data = json.load(f)
        except Exception as e:
            await ctx.send(f"❌ Error loading players.json: {e}")
            conn.close()
            return

        team1_players = []
        team2_players = []

        for team_data in teams_data:
            if team_data['team'] == team1:
                team1_players = team_data['players']
            elif team_data['team'] == team2:
                team2_players = team_data['players']

        # Get claimed players' user IDs
        all_players = team1_players + team2_players
        player_user_ids = []

        for player in all_players:
            c.execute(
                "SELECT user_id FROM player_representatives WHERE player_name = ?",
                (player['name'], ))
            result = c.fetchone()
            if result:
                player_user_ids.append(result[0])

        conn.close()

        if not player_user_ids:
            await ctx.send(
                f"❌ No claimed players found for {team1} or {team2}!")
            return

        # Create the reminder embed with fixture image
        stadium = MATCH_CHANNELS.get(channel_id, "Unknown Stadium")
        vs_image = await create_vs_image(team1, team2, stadium)

        flag1 = get_team_flag(team1)
        flag2 = get_team_flag(team2)

        # Get the stadium channel from the guild
        stadium_channel = ctx.guild.get_channel(channel_id)

        if not stadium_channel:
            await ctx.send(f"❌ Stadium channel not found!")
            return

        embed = discord.Embed(
            title="⏰ Match Time!",
            description=f"**{tournament_name} - Round {round_number}**",
            color=0xFF0000)

        embed.add_field(name="Match",
                        value=f"{flag1} **{team1}** vs {flag2} **{team2}**",
                        inline=False)

        embed.add_field(name="Stadium",
                        value=f"🏟️ {stadium_channel.mention}",
                        inline=False)

        embed.add_field(
            name="📍 Action Required",
            value=
            f"Please head to {stadium_channel.mention} now for your match!",
            inline=False)

        embed.set_footer(
            text=f"{tournament_name} • Your presence is required!")

        # Get channel link - using the STADIUM channel, not where command was used
        channel_link = f"https://discord.com/channels/{ctx.guild.id}/{channel_id}"

        # Send DMs
        for user_id in player_user_ids:
            try:
                user = await self.bot.fetch_user(user_id)

                if vs_image:
                    # Reset the image buffer position
                    vs_image.seek(0)
                    file = discord.File(vs_image,
                                        filename="match_reminder.png")
                    embed.set_image(url="attachment://match_reminder.png")
                    await user.send(embed=embed, file=file)
                else:
                    await user.send(embed=embed)

                # Send plain text channel link - STADIUM channel link
                await user.send(f"**Match Channel:** {channel_link}")

            except:
                pass  # Silently ignore DM failures

    @commands.command(name="overview",
                      help="View all matches and stats for a team")
    async def status(self, ctx, *, team_name: str = None):
        """View all matches (played and scheduled) and statistics for a specific team"""

        if not team_name:
            # Try to get user's team
            team_name = get_user_team(ctx.author.id)
            if not team_name:
                await ctx.send(
                    "❌ Please specify a team name or claim a player first!\nUsage: `-status <team name>`"
                )
                return

        # Normalize team name - find best match
        all_teams = [
            "India", "Pakistan", "Australia", "England", "New Zealand",
            "South Africa", "West Indies", "Sri Lanka", "Bangladesh",
            "Afghanistan", "Netherlands", "Scotland", "Ireland", "Zimbabwe",
            "UAE", "Canada", "USA"
        ]

        # Case-insensitive matching
        team_name_lower = team_name.lower()
        matched_team = None

        # Try exact match first
        for team in all_teams:
            if team.lower() == team_name_lower:
                matched_team = team
                break

        # Try partial match
        if not matched_team:
            for team in all_teams:
                if team_name_lower in team.lower():
                    matched_team = team
                    break

        if not matched_team:
            await ctx.send(
                f"❌ Team '{team_name}' not found! Please check the spelling.")
            return

        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id = tournament[0]

        # Verify team is in tournament
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute(
            "SELECT team_name FROM tournament_teams WHERE tournament_id = ? AND team_name = ?",
            (tournament_id, matched_team))
        team_exists = c.fetchone()
        conn.close()

        if not team_exists:
            await ctx.send(
                f"❌ Team '{matched_team}' is not participating in the current tournament!"
            )
            return

        # Create view and show
        view = TeamStatsView(ctx, matched_team, self.bot)
        embed, _ = await view.create_team_stats_embed(0, "overview")
        view.update_buttons()
        view.message = await ctx.send(embed=embed, view=view)

    @commands.command(name="resetround",
                      aliases=["rr"],
                      help="[ADMIN] Reset the latest round's fixtures")
    @commands.has_permissions(administrator=True)
    async def resetround(self, ctx):
        """Delete all fixtures from the latest round so they can be regenerated"""
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, current_round = tournament

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Find the latest round with fixtures
        c.execute(
            """SELECT MAX(round_number) FROM fixtures 
                     WHERE tournament_id = ?""", (tournament_id, ))
        max_round_row = c.fetchone()
        max_round = max_round_row[0] if max_round_row[0] is not None else 0

        if max_round == 0:
            await ctx.send("❌ No fixtures found to reset!")
            conn.close()
            return

        # Get fixtures in that round for preview
        c.execute(
            """SELECT team1, team2, is_played FROM fixtures 
                     WHERE tournament_id = ? AND round_number = ?""",
            (tournament_id, max_round))
        fixtures = c.fetchall()
        conn.close()

        if not fixtures:
            await ctx.send("❌ No fixtures found to reset!")
            return

        # Check if any matches have been played
        played_count = sum(1 for _, _, is_played in fixtures if is_played)

        # Create confirmation embed
        embed = discord.Embed(
            title="⚠️ Reset Round Fixtures?",
            description=f"**{tournament_name} - Round {max_round}**\n\n"
            f"This will delete **{len(fixtures)}** fixture(s) from Round {max_round}.\n\n"
            f"**Fixtures to be deleted:**",
            color=0xFF0000)

        fixture_text = ""
        for team1, team2, is_played in fixtures:
            flag1 = get_team_flag(team1)
            flag2 = get_team_flag(team2)
            status = "✅ Played" if is_played else "📅 Scheduled"
            fixture_text += f"{status} {flag1} {team1} vs {flag2} {team2}\n"

        embed.add_field(name="Fixtures", value=fixture_text, inline=False)

        if played_count > 0:
            embed.add_field(
                name="⚠️ Warning",
                value=f"**{played_count}** match(es) have already been played!\n"
                "Deleting these fixtures will NOT reset match statistics or points.",
                inline=False)

        embed.set_footer(text="This action cannot be undone!")

        view = View(timeout=60)

        async def confirm_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "❌ Only the command author can confirm!", ephemeral=True)
                return

            conn = sqlite3.connect('players.db')
            c = conn.cursor()

            # Delete fixtures from the round
            c.execute(
                """DELETE FROM fixtures 
                         WHERE tournament_id = ? AND round_number = ?""",
                (tournament_id, max_round))

            deleted_count = c.rowcount

            # Update current_round if needed
            c.execute(
                """SELECT MAX(round_number) FROM fixtures 
                         WHERE tournament_id = ?""", (tournament_id, ))
            new_max = c.fetchone()[0]
            new_current = new_max if new_max else 0

            c.execute("UPDATE tournaments SET current_round = ? WHERE id = ?",
                      (new_current, tournament_id))

            conn.commit()
            conn.close()

            success_embed = discord.Embed(
                title="✅ Round Reset Complete",
                description=f"**{tournament_name}**\n\n"
                f"Deleted **{deleted_count}** fixture(s) from Round {max_round}.\n"
                f"Current round set to: **{new_current}**\n\n"
                f"You can now use `-setfixtures` or `-fixturemake` to create new fixtures.",
                color=0x00FF00)

            await interaction.response.edit_message(embed=success_embed,
                                                    view=None)

        async def cancel_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "❌ Only the command author can cancel!", ephemeral=True)
                return

            await interaction.response.edit_message(
                content="❌ Round reset cancelled.", embed=None, view=None)

        confirm_btn = Button(label="✅ Confirm Reset",
                             style=discord.ButtonStyle.danger)
        cancel_btn = Button(label="❌ Cancel",
                            style=discord.ButtonStyle.secondary)

        confirm_btn.callback = confirm_callback
        cancel_btn.callback = cancel_callback

        view.add_item(confirm_btn)
        view.add_item(cancel_btn)

        await ctx.send(embed=embed, view=view)

    @commands.command(
        name="done",
        help=
        "[ADMIN] Mark a match as completed with optional winner (1 = team1, 2 = team2)"
    )
    @commands.has_permissions(administrator=True)
    async def done(self, ctx, team1: str, team2: str, winner: int = 0):
        """Mark a match between two teams as completed (forces if already played)

        Args:
            winner: 1 for team1 win, 2 for team2 win, 0 for no winner recorded (default)
        """
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, current_round = tournament

        # Validate winner parameter
        if winner not in [0, 1, 2]:
            await ctx.send(
                "❌ Winner must be 1 (first team), 2 (second team), or 0 (no winner)!"
            )
            return

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Find ANY fixture between these two teams (including already played ones)
        c.execute(
            """SELECT id, round_number, channel_id, is_reserved, is_played, team1, team2
                     FROM fixtures 
                     WHERE tournament_id = ? 
                     AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))
                     ORDER BY round_number DESC
                     LIMIT 1""", (tournament_id, team1, team2, team2, team1))

        fixture = c.fetchone()

        if not fixture:
            await ctx.send(
                f"❌ No fixture exists between **{team1}** and **{team2}**!")
            conn.close()
            return

        fixture_id, round_number, channel_id, is_reserved, is_played, fixture_team1, fixture_team2 = fixture

        already_played = is_played == 1

        # Determine winner based on actual fixture teams
        winner_team = None
        if winner == 1:
            winner_team = fixture_team1
        elif winner == 2:
            winner_team = fixture_team2

        # Mark the fixture as played and set winner
        c.execute(
            "UPDATE fixtures SET is_played = 1, is_reserved = 0, winner = ? WHERE id = ?",
            (winner_team, fixture_id))

        # Update matches_played for both teams (only if not already counted)
        if not already_played:
            c.execute(
                """UPDATE tournament_teams 
                         SET matches_played = matches_played + 1 
                         WHERE tournament_id = ? AND team_name IN (?, ?)""",
                (tournament_id, team1, team2))

        conn.commit()
        conn.close()

        # Create success embed
        flag1 = get_team_flag(team1)
        flag2 = get_team_flag(team2)
        stadium = MATCH_CHANNELS.get(channel_id, "Unknown Stadium")

        embed = discord.Embed(
            title="✅ Match Marked as Completed",
            description=f"**{tournament_name} - Round {round_number}**",
            color=0x00FF00)

        match_text = f"{flag1} **{team1}** vs {flag2} **{team2}**"
        if winner_team:
            winner_flag = get_team_flag(winner_team)
            match_text += f"\n\n🏆 Winner: {winner_flag} **{winner_team}**"

        embed.add_field(name="Match", value=match_text, inline=False)

        embed.add_field(name="Stadium", value=f"🏟️ {stadium}", inline=False)

        status_text = "Match has been marked as played."
        if winner_team:
            status_text += f"\n✅ Winner recorded as **{winner_team}** (for display in -overview only)."
        if already_played:
            status_text += "\n⚠️ This match was already marked as played - forced update."
        else:
            status_text += "\nBoth teams' match counters have been updated."

        embed.add_field(name="Status", value=status_text, inline=False)

        if is_reserved and not already_played:
            embed.add_field(
                name="ℹ️ Note",
                value=
                "This match was previously reserved and is now completed.",
                inline=False)

        embed.set_footer(
            text=
            "⚠️ Winner is for display only - update points/NRR/wins/losses manually"
        )

        await ctx.send(embed=embed)

    @commands.command(name="setmp",
                      help="[ADMIN] Set matches played for a team")
    @commands.has_permissions(administrator=True)
    async def setmp(self, ctx, team_name: str, matches: int):
        """Set the number of matches played for a team"""
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id = tournament[0]

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        c.execute(
            """UPDATE tournament_teams 
                    SET matches_played = ?
                    WHERE tournament_id = ? AND team_name = ?""",
            (matches, tournament_id, team_name))

        if c.rowcount == 0:
            await ctx.send(f"❌ Team '{team_name}' not found in the tournament!"
                           )
            conn.close()
            return

        conn.commit()
        conn.close()

        flag = get_team_flag(team_name)
        embed = discord.Embed(
            title="✅ Matches Played Updated",
            description=
            f"{flag} **{team_name}**\n\nMatches Played: **{matches}**",
            color=get_team_color(team_name))

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
        c.execute(
            """SELECT team1, team2, round_number, channel_id
                    FROM fixtures 
                    WHERE tournament_id = ? AND is_reserved = 1 AND is_played = 0""",
            (tournament_id, ))
        reserved = c.fetchall()
        conn.close()

        if not reserved:
            await ctx.send("✅ No reserved matches!")
            return

        embed = discord.Embed(title=f"📌 {tournament_name} - Reserved Matches",
                              color=0xFFA500)

        for team1, team2, round_num, channel_id in reserved:
            flag1 = get_team_flag(team1)
            flag2 = get_team_flag(team2)
            stadium = MATCH_CHANNELS.get(channel_id, "Unknown Stadium")

            embed.add_field(
                name=f"Round {round_num}",
                value=
                f"{flag1} **{team1}** vs {flag2} **{team2}**\n🏟️ {stadium}",
                inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="qualify", help="[ADMIN] Mark a team as qualified")
    @commands.has_permissions(administrator=True)
    async def qualify(self, ctx, *, team_name: str):
        """Mark a team as qualified - adds (Q) prefix in points table"""
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id = tournament[0]

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Check if qualified column exists, if not add it
        c.execute("PRAGMA table_info(tournament_teams)")
        columns = [column[1] for column in c.fetchall()]
        if 'qualified' not in columns:
            c.execute("ALTER TABLE tournament_teams ADD COLUMN qualified INTEGER DEFAULT 0")

        # Toggle qualification status
        c.execute("""SELECT qualified FROM tournament_teams 
                    WHERE tournament_id = ? AND team_name = ?""",
                  (tournament_id, team_name))

        result = c.fetchone()

        if not result:
            await ctx.send(f"❌ Team '{team_name}' not found in the tournament!")
            conn.close()
            return

        current_status = result[0]
        new_status = 0 if current_status else 1

        c.execute("""UPDATE tournament_teams 
                    SET qualified = ?
                    WHERE tournament_id = ? AND team_name = ?""",
                  (new_status, tournament_id, team_name))

        conn.commit()
        conn.close()

        flag = get_team_flag(team_name)
        status_text = "qualified ✅" if new_status else "unqualified ❌"

        embed = discord.Embed(
            title=f"{'✅' if new_status else '❌'} Qualification Status Updated",
            description=f"{flag} **{team_name}** has been marked as **{status_text}**",
            color=0x00FF00 if new_status else 0xFF0000
        )

        await ctx.send(embed=embed)


    @commands.command(name="givefreewin", aliases=["gfw"], help="[ADMIN] Give a team a free win against another team")
    @commands.has_permissions(administrator=True)
    async def givefreewin(self, ctx, team1: str, team2: str, winner: int):
        """Give a free win to one team against another

        Args:
            team1: First team name
            team2: Second team name
            winner: 1 for team1 win, 2 for team2 win
        """
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, _ = tournament

        # Validate winner parameter
        if winner not in [1, 2]:
            await ctx.send("❌ Winner must be 1 (first team) or 2 (second team)!")
            return

        # Determine winner and loser
        winner_team = team1 if winner == 1 else team2
        loser_team = team2 if winner == 1 else team1

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Verify both teams exist in tournament
        c.execute(
            "SELECT team_name FROM tournament_teams WHERE tournament_id = ? AND team_name IN (?, ?)",
            (tournament_id, team1, team2))
        found_teams = [row[0] for row in c.fetchall()]

        if len(found_teams) != 2:
            missing = [t for t in [team1, team2] if t not in found_teams]
            await ctx.send(f"❌ Team(s) not found in tournament: {', '.join(missing)}")
            conn.close()
            return

        # Update winner stats: +2 points, +1 win, +1 match played
        c.execute("""UPDATE tournament_teams 
                    SET points = points + 2,
                        wins = wins + 1,
                        matches_played = matches_played + 1
                    WHERE tournament_id = ? AND team_name = ?""",
                  (tournament_id, winner_team))

        # Update loser stats: +1 loss, +1 match played (no points)
        c.execute("""UPDATE tournament_teams 
                    SET losses = losses + 1,
                        matches_played = matches_played + 1
                    WHERE tournament_id = ? AND team_name = ?""",
                  (tournament_id, loser_team))

        conn.commit()

        # Get updated stats for both teams
        c.execute("""SELECT points, matches_played, wins, losses, nrr
                    FROM tournament_teams 
                    WHERE tournament_id = ? AND team_name = ?""",
                  (tournament_id, winner_team))
        winner_stats = c.fetchone()

        c.execute("""SELECT points, matches_played, wins, losses, nrr
                    FROM tournament_teams 
                    WHERE tournament_id = ? AND team_name = ?""",
                  (tournament_id, loser_team))
        loser_stats = c.fetchone()

        conn.close()

        # Create success embed
        flag1 = get_team_flag(team1)
        flag2 = get_team_flag(team2)
        winner_flag = get_team_flag(winner_team)
        loser_flag = get_team_flag(loser_team)

        embed = discord.Embed(
            title="✅ Free Win Awarded",
            description=f"**{tournament_name}**\n\n{flag1} **{team1}** vs {flag2} **{team2}**",
            color=0x00FF00
        )

        # Winner stats
        w_pts, w_mp, w_wins, w_losses, w_nrr = winner_stats
        embed.add_field(
            name=f"🏆 Winner: {winner_flag} {winner_team}",
            value=f"```yaml\n"
                  f"Points:      {w_pts} (+2)\n"
                  f"Matches:     {w_mp} (+1)\n"
                  f"Wins:        {w_wins} (+1)\n"
                  f"Losses:      {w_losses}\n"
                  f"NRR:         {w_nrr:+.3f} (unchanged)\n"
                  f"```",
            inline=False
        )

        # Loser stats
        l_pts, l_mp, l_wins, l_losses, l_nrr = loser_stats
        embed.add_field(
            name=f"❌ Loser: {loser_flag} {loser_team}",
            value=f"```yaml\n"
                  f"Points:      {l_pts} (unchanged)\n"
                  f"Matches:     {l_mp} (+1)\n"
                  f"Wins:        {l_wins}\n"
                  f"Losses:      {l_losses} (+1)\n"
                  f"NRR:         {l_nrr:+.3f} (unchanged)\n"
                  f"```",
            inline=False
        )

        embed.set_footer(text=f"{tournament_name} • Free Win Awarded")

        await ctx.send(embed=embed)

    @commands.command(name="archivetournament", aliases=["at"], help="[ADMIN] Archive the current tournament")
    @commands.has_permissions(administrator=True)
    async def archivetournament(self, ctx):
        """Archive the current tournament and award trophies to winning team"""
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, current_round = tournament

        # Get all teams
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute(
            "SELECT team_name FROM tournament_teams WHERE tournament_id = ? ORDER BY team_name",
            (tournament_id,))
        all_teams = [row[0] for row in c.fetchall()]
        conn.close()

        if not all_teams:
            await ctx.send("❌ No teams found in tournament!")
            return

        # Create team selection view
        class WinnerSelectionView(View):
            def __init__(self):
                super().__init__(timeout=120)
                self.selected_winner = None
                self.add_team_select()

            def add_team_select(self):
                team_options = []
                for team in all_teams[:25]:
                    flag = get_team_flag(team)
                    team_options.append(
                        discord.SelectOption(
                            label=team,
                            value=team,
                            emoji=flag
                        )
                    )

                select = Select(
                    placeholder="🏆 Select Tournament Winner",
                    options=team_options,
                    custom_id="winner_select"
                )
                select.callback = self.winner_callback
                self.add_item(select)

            async def winner_callback(self, interaction: discord.Interaction):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
                    return

                self.selected_winner = interaction.data['values'][0]

                # Confirm selection
                flag = get_team_flag(self.selected_winner)
                confirm_embed = discord.Embed(
                    title="🏆 Confirm Tournament Winner",
                    description=f"{flag} **{self.selected_winner}**\n\nThis will:\n"
                                f"• Award trophies to all players of {self.selected_winner}\n"
                                f"• Archive the tournament\n"
                                f"• Make it viewable in -oldtournaments\n\n"
                                f"**Continue?**",
                    color=get_team_color(self.selected_winner)
                )

                confirm_view = View(timeout=60)

                async def confirm_final(inter: discord.Interaction):
                    if inter.user.id != ctx.author.id:
                        await inter.response.send_message("❌ Only the command author can confirm!", ephemeral=True)
                        return

                    await inter.response.defer()

                    # Archive the tournament
                    conn = sqlite3.connect('players.db')
                    c = conn.cursor()

                    # Mark tournament as archived
                    c.execute("""UPDATE tournaments 
                                SET is_active = 0, is_archived = 1, winner = ?, archived_at = CURRENT_TIMESTAMP
                                WHERE id = ?""",
                              (self.selected_winner, tournament_id))

                    # Get all players from winning team
                    import json
                    try:
                        with open('players.json', 'r', encoding='utf-8') as f:
                            teams_data = json.load(f)

                        winning_players = []
                        for team_data in teams_data:
                            if team_data['team'] == self.selected_winner:
                                winning_players = team_data['players']
                                break

                        # Award trophies to claimed players
                        trophy_count = 0
                        for player in winning_players:
                            c.execute(
                                "SELECT user_id FROM player_representatives WHERE player_name = ?",
                                (player['name'],))
                            result = c.fetchone()
                            if result:
                                user_id = result[0]
                                c.execute("""INSERT INTO player_trophies 
                                           (user_id, tournament_id, tournament_name, team_name)
                                           VALUES (?, ?, ?, ?)""",
                                          (user_id, tournament_id, tournament_name, self.selected_winner))
                                trophy_count += 1

                        conn.commit()
                        conn.close()

                        # Success message
                        success_embed = discord.Embed(
                            title="✅ Tournament Archived",
                            description=f"**{tournament_name}**\n\n"
                                        f"🏆 Winner: {flag} **{self.selected_winner}**\n"
                                        f"🎖️ Trophies awarded: **{trophy_count}** players\n\n"
                                        f"The tournament has been archived and can be viewed with `-oldtournaments`.",
                            color=0xFFD700
                        )

                        for item in confirm_view.children:
                            item.disabled = True

                        await inter.message.edit(embed=success_embed, view=None)

                    except Exception as e:
                        await inter.followup.send(f"❌ Error archiving tournament: {e}", ephemeral=True)

                async def cancel_final(inter: discord.Interaction):
                    if inter.user.id != ctx.author.id:
                        await inter.response.send_message("❌ Only the command author can cancel!", ephemeral=True)
                        return

                    await inter.response.edit_message(content="❌ Archiving cancelled.", embed=None, view=None)

                confirm_btn = Button(label="✅ Confirm Archive", style=discord.ButtonStyle.success)
                cancel_btn = Button(label="❌ Cancel", style=discord.ButtonStyle.secondary)

                confirm_btn.callback = confirm_final
                cancel_btn.callback = cancel_final

                confirm_view.add_item(confirm_btn)
                confirm_view.add_item(cancel_btn)

                await interaction.response.edit_message(embed=confirm_embed, view=confirm_view)

        # Send initial selection
        embed = discord.Embed(
            title="🏆 Archive Tournament",
            description=f"**{tournament_name}**\n\nSelect the winning team:",
            color=0xFFD700
        )

        view = WinnerSelectionView()
        await ctx.send(embed=embed, view=view)

    @commands.command(name="oldtournaments", aliases=["ot"], help="View archived tournaments")
    async def oldtournaments(self, ctx):
        """View all archived tournaments"""
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("""SELECT id, name, winner, archived_at 
                    FROM tournaments 
                    WHERE is_archived = 1 
                    ORDER BY archived_at DESC""")
        tournaments = c.fetchall()
        conn.close()

        if not tournaments:
            await ctx.send("📚 No archived tournaments found!")
            return

        class TournamentSelectView(View):
            def __init__(self):
                super().__init__(timeout=180)
                self.add_tournament_select()

            def add_tournament_select(self):
                tournament_options = []
                for tid, name, winner, archived_at in tournaments[:25]:
                    flag = get_team_flag(winner) if winner else "🏆"
                    tournament_options.append(
                        discord.SelectOption(
                            label=name,
                            value=str(tid),
                            description=f"Winner: {winner}" if winner else "No winner recorded",
                            emoji=flag
                        )
                    )

                select = Select(
                    placeholder="📚 Select a tournament to view",
                    options=tournament_options,
                    custom_id="tournament_select"
                )
                select.callback = self.tournament_callback
                self.add_item(select)

            async def tournament_callback(self, interaction: discord.Interaction):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
                    return

                await interaction.response.defer()

                selected_tid = int(interaction.data['values'][0])

                # Get tournament data
                conn = sqlite3.connect('players.db')
                c = conn.cursor()

                c.execute("SELECT name, winner, archived_at FROM tournaments WHERE id = ?", (selected_tid,))
                t_data = c.fetchone()
                t_name, t_winner, t_archived = t_data

                # Get team standings
                c.execute("""SELECT team_name, points, matches_played, wins, losses, nrr, fpp
                            FROM tournament_teams 
                            WHERE tournament_id = ?
                            ORDER BY points DESC, nrr DESC""", (selected_tid,))
                teams = c.fetchall()
                conn.close()

                # Create points table image
                table_image = await create_points_table_image(t_name, teams)

                if table_image:
                    file = discord.File(table_image, filename="archived_points_table.png")
                    embed = discord.Embed(
                        title=f"📚 {t_name} (Archived)",
                        description=f"🏆 Winner: {get_team_flag(t_winner)} **{t_winner}**" if t_winner else "No winner recorded",
                        color=0xFFD700
                    )
                    embed.set_image(url="attachment://archived_points_table.png")
                    embed.set_footer(text=f"Archived on {t_archived.split()[0] if t_archived else 'Unknown'}")

                    await interaction.followup.send(embed=embed, file=file)
                else:
                    await interaction.followup.send("❌ Failed to create points table!", ephemeral=True)

        # Send tournament list
        embed = discord.Embed(
            title="📚 Archived Tournaments",
            description=f"**{len(tournaments)}** archived tournament(s)\n\nSelect a tournament to view its final standings:",
            color=0x0066CC
        )

        view = TournamentSelectView()
        await ctx.send(embed=embed, view=view)

    @commands.command(name="ptsi", help="View international points table for Series matches")
    async def ptsi_command(self, ctx, *, series_name: str = None):
        """International points table from series data - all-time or filtered by series name"""
        import json

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        if series_name:
            c.execute("SELECT id FROM series WHERE LOWER(name) LIKE ?",
                      (f"%{series_name.lower()}%",))
            matching_ids = [row[0] for row in c.fetchall()]

            if not matching_ids:
                await ctx.send(f"❌ No series found matching **{series_name}**!")
                conn.close()
                return

            placeholders = ','.join('?' * len(matching_ids))
            c.execute(f"""
                SELECT team_name,
                       SUM(wins) as w,
                       SUM(losses) as l,
                       SUM(matches_played) as mp,
                       SUM(nrr) as n
                FROM series_teams
                WHERE series_id IN ({placeholders})
                GROUP BY team_name
                HAVING mp > 0
                ORDER BY w DESC, n DESC
            """, matching_ids)
            title_text = f"Series: {series_name}"
        else:
            c.execute("""
                SELECT team_name,
                       SUM(wins) as w,
                       SUM(losses) as l,
                       SUM(matches_played) as mp,
                       SUM(nrr) as n
                FROM series_teams
                GROUP BY team_name
                HAVING mp > 0
                ORDER BY w DESC, n DESC
            """)
            title_text = "All-Time Series"

        data = c.fetchall()
        conn.close()

        if not data:
            msg = f"❌ No series data found for **{series_name}**!" if series_name else "❌ No series match data found!"
            await ctx.send(msg)
            return

        # Convert to format expected by create_international_points_table
        # (team_name, pts, mp, wins, losses, nrr, fpp_placeholder)
        teams_stats = [
            (team, w * 2, mp, w, l, nrr, 0)
            for team, w, l, mp, nrr in data
        ]

        from tournament import create_international_points_table
        table_image = await create_international_points_table(teams_stats)

        if not table_image:
            await ctx.send("❌ Failed to create points table!")
            return

        file = discord.File(table_image, filename="series_international_pts.png")
        embed = discord.Embed(
            title=f"🌍 International Cricket — {title_text}",
            color=0x1E90FF
        )
        embed.set_image(url="attachment://series_international_pts.png")
        embed.set_footer(text=f"{title_text} • International Matches")
        await ctx.send(embed=embed, file=file)

    
async def setup(bot):
    await bot.add_cog(Tournament(bot))