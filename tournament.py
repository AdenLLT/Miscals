import discord
import sqlite3
import random
import json
from discord.ext import commands
from discord.ui import View, Button, Select, Modal, TextInput
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

    c.execute('''CREATE TABLE IF NOT EXISTS tournament_round_info
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tournament_id INTEGER,
                  round_number INTEGER,
                  round_type TEXT,
                  round_display_name TEXT,
                  rest_team TEXT DEFAULT NULL,
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

    # Migrate existing tournament_teams table if group_name column missing
    c.execute("PRAGMA table_info(tournament_teams)")
    tt_cols = [row[1] for row in c.fetchall()]
    if 'group_name' not in tt_cols:
        c.execute("ALTER TABLE tournament_teams ADD COLUMN group_name TEXT DEFAULT NULL")

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


# Available tournament match channels (stadiums)
MATCH_CHANNELS = {
    1511817436792361080: "Perth Stadium",
    1483896802603172013: "Adelaide Oval",
    1511820266433544344: "McLean Park",
    1511820228013592626: "Basin Reserve",
    1511817976817389821: "Hagley Oval",
    1511820174922350812: "Eden Park",
    1483767491132915793: "Melbourne Cricket Ground",
    1534819463029850174: "Sydney Cricket Ground",
    1534819524380196864: "The Gabba",
    1534819620828086404: "Bellerive Oval",
    1534819692374523964: "Manuka Oval",
    1534819853775667311: "Brisbane Cricket Ground",
    1534820064946028644: "Great Barrier Reef",
    1534820172580392991: "Cazalys Stadium",
    1534820357331095653: "Bay Oval",
    1534820441552719942: "Seddon Park",
    1534820594317656094: "McLean Park",
    1534820753575514172: "University Oval",
    1534820885645627412: "Saxton Oval",
    1534821113337741322: "Marrara Stadium",
    1534821195655155793: "Carrara Oval",
    1534821412685090816: "Docklands Stadium",
    1534821626409910353: "Newcastle International",
    1534821730412003348: "Penrith Stadium",
}

# Channel for posting fixtures
FIXTURES_CHANNEL = 1463219150645231849
PRESEEDED_FIXTURES_FILE = "tournament_fixtures.json"


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

                # ── Active series fixtures for this team ──────────────────
                try:
                    sc = sqlite3.connect('players.db')
                    sc2 = sc.cursor()
                    sc2.execute("SELECT id, name, teams FROM series WHERE is_active = 1 ORDER BY id DESC")
                    for sid, sname, steams_json in sc2.fetchall():
                        try:
                            steams = json.loads(steams_json) if steams_json else []
                        except Exception:
                            steams = []
                        if self.team_name not in steams:
                            continue
                        sc2.execute(
                            """SELECT match_number, team1, team2, channel_id, is_played, winner
                               FROM series_fixtures
                               WHERE series_id = ? AND (team1 = ? OR team2 = ?)
                               ORDER BY match_number ASC""",
                            (sid, self.team_name, self.team_name))
                        sfixtures = sc2.fetchall()
                        if not sfixtures:
                            continue
                        series_text = ""
                        for match_num, t1, t2, ch_id, is_played, winner in sfixtures:
                            opp = t2 if t1 == self.team_name else t1
                            opp_flag = get_team_flag(opp)
                            if is_played:
                                if winner == self.team_name:
                                    series_text += f"🟢 Match {match_num} vs {opp_flag} **{opp}** • ✅ Won\n"
                                elif winner:
                                    series_text += f"🔴 Match {match_num} vs {opp_flag} **{opp}** • ❌ Lost\n"
                                else:
                                    series_text += f"⚪ Match {match_num} vs {opp_flag} **{opp}** • Played\n"
                            else:
                                series_text += f"🏏 Match {match_num} vs {opp_flag} **{opp}** • <#{ch_id}>\n"
                        embed.add_field(name=f"📋 Series: {sname}", value=series_text, inline=False)
                    sc.close()
                except Exception:
                    pass

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
        "USA": (8, 0, 38),
        "Italy": (0, 146, 70),
        "Nepal": (220, 20, 60),
        "Namibia": (0, 53, 128),
        "Hong Kong": (222, 41, 16),
        "Oman": (0, 154, 68),
        "Papua New Guinea": (191, 10, 48),
        "Uganda": (252, 220, 4),
        "Malaysia": (204, 0, 1),
        "Spain": (170, 21, 27),
        "Germany": (221, 0, 0),
        "Japan": (188, 0, 45),
        "Portugal": (26, 122, 60),
        "Denmark": (198, 12, 48)
    }
    return colors.get(team_name, (128, 128, 128))


def _safe_rgb(color, fallback=(128, 128, 128)):
    """Return a Pillow-safe three-channel RGB tuple."""
    try:
        if isinstance(color, int):
            values = (
                (color >> 16) & 0xFF,
                (color >> 8) & 0xFF,
                color & 0xFF,
            )
        else:
            values = tuple(color)
            if len(values) < 3:
                raise ValueError("RGB color must have at least three channels")
            values = values[:3]
        return tuple(max(0, min(255, int(value))) for value in values)
    except (TypeError, ValueError, OverflowError):
        return fallback


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
        "USA": 0x080026,
        "Italy": 0x009246,
        "Nepal": 0xDC143C,
        "Namibia": 0x003580,
        "Hong Kong": 0xDE2910,
        "Oman": 0x009A44,
        "Papua New Guinea": 0xBF0A30,
        "Uganda": 0xFCDC04,
        "Malaysia": 0xCC0001,
        "Spain": 0xAA151B,
        "Germany": 0xDD0000,
        "Japan": 0xBC002D,
        "Portugal": 0x1A7A3C,
        "Denmark": 0xC60C30
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
        "USA": "🇺🇸",
        "Italy": "🇮🇹",
        "Nepal": "🇳🇵",
        "Namibia": "🇳🇦",
        "Hong Kong": "🇭🇰",
        "Oman": "🇴🇲",
        "Papua New Guinea": "🇵🇬",
        "Uganda": "🇺🇬",
        "Malaysia": "🇲🇾",
        "Spain": "🇪🇸",
        "Germany": "🇩🇪",
        "Japan": "🇯🇵",
        "Portugal": "🇵🇹",
        "Denmark": "🇩🇰"
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
        "USA": 1460376156250570824,
        "Italy": 1513096652842467328,
        "Nepal": 1513096680835125398,
        "Namibia": 1513096608063950878,
        "Hong Kong": 1513236745527889951,
        "Oman": 1513236895595757768,
        "Papua New Guinea": 1513237053935194262,
        "Uganda": 1513237221560287312,
        "Malaysia": 1513238128482320454,
        "Spain": 1513238260502233198,
        "Germany": 1513238268777595073,
        "Japan": 1513238484075282432,
        "Portugal": 1513238487707549958,
        "Denmark": 1513238490723385466
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
        color1 = _safe_rgb(get_team_color_rgb(team1))
        color2 = _safe_rgb(get_team_color_rgb(team2))

        # Create smooth fading gradients with HIGHER alpha (150 instead of 80)
        # Left side gradient (team1 color)
        for x in range(width // 2):
            progress = x / (width // 2)
            alpha = int(150 * (1 - progress))  # Increased from 80

            for y in range(height):
                draw.point((x, y), fill=(*color1, max(0, min(255, alpha))))

        # Right side gradient (team2 color)
        for x in range(width // 2, width):
            progress = (x - width // 2) / (width // 2)
            alpha = int(150 * progress)  # Increased from 80

            for y in range(height):
                draw.point((x, y), fill=(*color2, max(0, min(255, alpha))))

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
            # Keep the stadium label subtle and well inside the right side of
            # the image so it does not crowd the edge.
            font = ImageFont.truetype("nor.otf", 38)
        except:
            font = ImageFont.load_default()

        bbox = draw_final.textbbox((0, 0), stadium_name, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Place the label much farther left than the original edge-aligned
        # position, while keeping it near the bottom.
        text_x = width - text_width - 280
        text_y = height - text_height - 105

        # Draw text with outline
        outline_size = 1
        for offset_x in [-outline_size, 0, outline_size]:
            for offset_y in [-outline_size, 0, outline_size]:
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
        "West Indies": "1f3dd",
        "Sri Lanka": "1f1f1-1f1f0",
        "Bangladesh": "1f1e7-1f1e9",
        "Afghanistan": "1f1e6-1f1eb",
        "Netherlands": "1f1f3-1f1f1",
        "Scotland": "1f3f4-e0067-e0062-e0073-e0063-e0074-e007f",
        "Ireland": "1f1ee-1f1ea",
        "Zimbabwe": "1f1ff-1f1fc",
        "UAE": "1f1e6-1f1ea",
        "Canada": "1f1e8-1f1e6",
        "USA": "1f1fa-1f1f8",
        "Italy": "1f1ee-1f1f9",
        "Nepal": "1f1f3-1f1f5",
        "Namibia": "1f1f3-1f1e6",
        "Hong Kong": "1f1ed-1f1f0",
        "Oman": "1f1f4-1f1f2",
        "Papua New Guinea": "1f1f5-1f1ec",
        "Uganda": "1f1fa-1f1ec",
        "Malaysia": "1f1f2-1f1fe",
        "Spain": "1f1ea-1f1f8",
        "Germany": "1f1e9-1f1ea",
        "Japan": "1f1ef-1f1f5",
        "Portugal": "1f1f5-1f1f9",
        "Denmark": "1f1e9-1f1f0"
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

async def create_points_table_image(tournament_name, teams_data, title_text="Points Table"):
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

        # Draw title (title_text is now a parameter)
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


def get_group_standings(tournament_id, group_name):
    """Return teams in a group ordered by pts DESC, nrr DESC"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("""
        SELECT team_name, points, matches_played, wins, losses, nrr, fpp,
               COALESCE(qualified, 0)
        FROM tournament_teams
        WHERE tournament_id = ? AND UPPER(group_name) = UPPER(?)
        ORDER BY points DESC, nrr DESC
    """, (tournament_id, group_name))
    rows = c.fetchall()
    conn.close()
    return rows


def get_preseeded_group_round(tournament_name, group, group_round_number,
                              group_teams):
    """Load and validate a preseeded intra-group round from the JSON schedule."""
    try:
        with open(PRESEEDED_FIXTURES_FILE, "r", encoding="utf-8") as file:
            schedule = json.load(file)
    except FileNotFoundError:
        return None, (
            f"❌ Preseeded fixture file `{PRESEEDED_FIXTURES_FILE}` was not found."
        )
    except json.JSONDecodeError as error:
        return None, (
            f"❌ Could not read `{PRESEEDED_FIXTURES_FILE}`: invalid JSON "
            f"({error.msg})."
        )
    except OSError as error:
        return None, f"❌ Could not read `{PRESEEDED_FIXTURES_FILE}`: {error}."

    tournament_schedule = schedule.get("tournaments", {}).get(tournament_name)
    if not isinstance(tournament_schedule, dict):
        return None, (
            f"❌ No preseeded fixture schedule was found for "
            f"**{tournament_name}**."
        )

    group_schedule = tournament_schedule.get("groups", {}).get(group)
    if not isinstance(group_schedule, dict):
        return None, (
            f"❌ No preseeded fixture schedule was found for Group {group} "
            f"in **{tournament_name}**."
        )

    round_schedule = group_schedule.get("rounds", {}).get(
        str(group_round_number)
    )
    if not isinstance(round_schedule, dict):
        return None, (
            f"❌ No preseeded fixtures were found for Group {group} "
            f"Round {group_round_number}."
        )

    raw_fixtures = round_schedule.get("fixtures")
    rest_team = round_schedule.get("rest_team")
    if not isinstance(raw_fixtures, list):
        return None, (
            f"❌ Group {group} Round {group_round_number} in "
            f"`{PRESEEDED_FIXTURES_FILE}` must contain a `fixtures` list."
        )

    official_teams = set(group_teams)
    if rest_team is not None and rest_team not in official_teams:
        return None, (
            f"❌ Preseeded Group {group} Round {group_round_number} has an "
            f"unknown rest team: **{rest_team}**."
        )

    matches = []
    seen_teams = set()
    seen_matchups = set()
    for index, fixture in enumerate(raw_fixtures, 1):
        if not isinstance(fixture, dict):
            return None, (
                f"❌ Preseeded Group {group} Round {group_round_number} "
                f"fixture {index} must be an object."
            )

        team1 = fixture.get("team1")
        team2 = fixture.get("team2")
        if not isinstance(team1, str) or not isinstance(team2, str):
            return None, (
                f"❌ Preseeded Group {group} Round {group_round_number} "
                f"fixture {index} must have string `team1` and `team2`."
            )
        if team1 == team2:
            return None, (
                f"❌ Preseeded Group {group} Round {group_round_number} "
                f"fixture {index} has the same team on both sides."
            )
        unknown_teams = {team1, team2} - official_teams
        if unknown_teams:
            return None, (
                f"❌ Preseeded Group {group} Round {group_round_number} "
                f"contains team(s) not in the group: "
                f"{', '.join(sorted(unknown_teams))}."
            )

        matchup = frozenset((team1, team2))
        if matchup in seen_matchups:
            return None, (
                f"❌ Preseeded Group {group} Round {group_round_number} "
                f"repeats **{team1} vs {team2}**."
            )
        if seen_teams.intersection((team1, team2)):
            return None, (
                f"❌ Preseeded Group {group} Round {group_round_number} "
                "assigns a team to more than one fixture."
            )

        seen_matchups.add(matchup)
        seen_teams.update((team1, team2))
        matches.append((team1, team2))

    expected_rest = official_teams - seen_teams
    if len(expected_rest) > 1 or (
        expected_rest and rest_team != next(iter(expected_rest))
    ):
        return None, (
            f"❌ Preseeded Group {group} Round {group_round_number} must "
            "include every group team exactly once, with the correct rest team."
        )
    if not expected_rest and rest_team is not None:
        return None, (
            f"❌ Preseeded Group {group} Round {group_round_number} has a "
            "rest team even though every team is playing."
        )

    expected_matches = (len(official_teams) - len(expected_rest)) // 2
    if len(matches) != expected_matches:
        return None, (
            f"❌ Preseeded Group {group} Round {group_round_number} has "
            f"{len(matches)} fixture(s); expected {expected_matches}."
        )

    return (matches, rest_team), None


def get_next_tournament_round(tournament_id):
    """Return the next available round number for the tournament"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT MAX(round_number) FROM fixtures WHERE tournament_id = ?",
              (tournament_id,))
    row = c.fetchone()
    max_round = row[0] if row[0] is not None else 0
    if max_round > 0:
        c.execute("""SELECT COUNT(*) FROM fixtures
                     WHERE tournament_id = ? AND round_number = ?
                     AND is_played = 0 AND is_reserved = 0""",
                  (tournament_id, max_round))
        unplayed = c.fetchone()[0]
        target = max_round if unplayed > 0 else max_round + 1
    else:
        target = 1
    conn.close()
    return target


def get_unfinished_regular_round(tournament_id):
    """Return (round_number, unfinished_count) for the latest regular round."""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(
        """SELECT MAX(round_number) FROM fixtures
           WHERE tournament_id = ? AND round_number > 0""",
        (tournament_id,),
    )
    row = c.fetchone()
    latest_round = row[0] if row and row[0] is not None else None
    if latest_round is None:
        conn.close()
        return None

    c.execute(
        """SELECT COUNT(*) FROM fixtures
           WHERE tournament_id = ? AND round_number = ?
             AND is_played = 0 AND is_reserved = 0""",
        (tournament_id, latest_round),
    )
    unfinished = c.fetchone()[0]
    conn.close()
    return latest_round, unfinished


def unfinished_round_message(tournament_id):
    """Return the user-facing block message, or None if a new round is allowed."""
    status = get_unfinished_regular_round(tournament_id)
    if status and status[1] > 0:
        round_number, unfinished = status
        return (
            f"❌ Round **{round_number}** still has **{unfinished}** uncompleted "
            "fixture(s). Complete those games or use `-reserveall` before "
            "creating a new round."
        )
    return None


def unfinished_group_round_message(tournament_id, group):
    """Return a block message for the latest generated round of one group."""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(
        """SELECT round_number, round_display_name
           FROM tournament_round_info
           WHERE tournament_id = ? AND round_type = ?
           ORDER BY round_number DESC
           LIMIT 1""",
        (tournament_id, f"group_{group}"),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        return None

    round_number, round_display_name = row
    c.execute(
        """SELECT COUNT(*) FROM fixtures
           WHERE tournament_id = ? AND round_number = ?
             AND is_played = 0 AND is_reserved = 0""",
        (tournament_id, round_number),
    )
    unfinished = c.fetchone()[0]
    conn.close()
    if unfinished:
        return (
            f"❌ **{round_display_name or f'Round {round_number}'}** still has "
            f"**{unfinished}** uncompleted fixture(s). Complete those games "
            "or use `-reserveall` before creating a new round."
        )
    return None


async def post_fixture_rows(bot, guild, fixture_rows, title):
    """Post saved fixture rows to the configured fixtures channel."""
    fixtures_channel = guild.get_channel(FIXTURES_CHANNEL)
    if not fixtures_channel:
        print(f"❌ Fixtures channel {FIXTURES_CHANNEL} not found!")
        return False

    for team1, team2, channel_id, stored_stadium in fixture_rows:
        stadium = MATCH_CHANNELS.get(channel_id, stored_stadium or "Unknown Stadium")
        vs_image = await create_vs_image(team1, team2, stadium)

        embed = discord.Embed(title=title, color=0x00FF00)
        embed.add_field(
            name="Match",
            value=f"{get_team_flag(team1)} **{team1}** vs "
                  f"{get_team_flag(team2)} **{team2}**",
            inline=False,
        )
        embed.add_field(
            name="Stadium",
            value=f"🏟️ <#{channel_id}>",
            inline=False,
        )
        embed.set_footer(text="TourneyFanHub")

        role_ids = [get_team_role_id(team1), get_team_role_id(team2)]
        ping_text = " ".join(f"<@&{role_id}>" for role_id in role_ids if role_id)

        if vs_image:
            file = discord.File(vs_image, filename=f"{team1}_vs_{team2}.png")
            embed.set_image(url=f"attachment://{team1}_vs_{team2}.png")
            await fixtures_channel.send(
                content=ping_text or None,
                embed=embed,
                file=file,
            )
        else:
            await fixtures_channel.send(
                content=ping_text or None,
                embed=embed,
            )
    return True


class SameFixturesRepostView(View):
    """Admin menu for reposting saved fixtures, optionally changing stadiums."""

    def __init__(
        self,
        ctx,
        tournament_id,
        tournament_name,
        group,
        round_number,
        round_display_name,
        fixtures,
    ):
        super().__init__(timeout=300)
        self.ctx = ctx
        self.tournament_id = tournament_id
        self.tournament_name = tournament_name
        self.group = group
        self.round_number = round_number
        self.round_display_name = round_display_name
        self.fixtures = [
            [team1, team2, channel_id, MATCH_CHANNELS.get(channel_id, stadium)]
            for team1, team2, channel_id, stadium in fixtures
        ]
        self.selected_fixture_index = None
        self.message = None
        self._add_controls()

    def summary(self):
        lines = [
            f"📌 **Saved fixtures: {self.round_display_name or f'Group {self.group}'}**",
            "Choose **Post Exact Fixtures** to repost unchanged, or select a "
            "fixture and stadium before choosing **Post With Stadium Changes**.",
            "",
        ]
        for index, (team1, team2, _, stadium) in enumerate(self.fixtures, 1):
            lines.append(f"**{index}.** {team1} vs {team2} — 🏟️ {stadium}")
        return "\n".join(lines)[:1900]

    def _add_controls(self):
        self.clear_items()

        fixture_options = [
            discord.SelectOption(
                label=f"{team1} vs {team2}"[:100],
                description=f"Current stadium: {stadium}"[:100],
                value=str(index),
            )
            for index, (team1, team2, _, stadium) in enumerate(self.fixtures)
        ]
        fixture_select = Select(
            placeholder="1️⃣ Select a fixture to change its stadium",
            options=fixture_options,
            custom_id="repost_fixture_select",
        )

        async def fixture_callback(interaction: discord.Interaction):
            if interaction.user.id != self.ctx.author.id:
                return await interaction.response.send_message(
                    "❌ This is not your menu!", ephemeral=True
                )
            self.selected_fixture_index = int(interaction.data["values"][0])
            team1, team2, _, stadium = self.fixtures[self.selected_fixture_index]
            await interaction.response.send_message(
                f"✅ Selected **{team1} vs {team2}**. "
                f"Now choose a stadium from the second menu.",
                ephemeral=True,
            )

        fixture_select.callback = fixture_callback
        self.add_item(fixture_select)

        stadium_options = [
            discord.SelectOption(
                label=stadium_name,
                value=str(channel_id),
                emoji="🏟️",
            )
            for channel_id, stadium_name in MATCH_CHANNELS.items()
        ]
        stadium_select = Select(
            placeholder="2️⃣ Choose a replacement stadium",
            options=stadium_options,
            custom_id="repost_stadium_select",
        )

        async def stadium_callback(interaction: discord.Interaction):
            if interaction.user.id != self.ctx.author.id:
                return await interaction.response.send_message(
                    "❌ This is not your menu!", ephemeral=True
                )
            if self.selected_fixture_index is None:
                return await interaction.response.send_message(
                    "❌ Select a fixture from the first menu before choosing "
                    "a stadium.",
                    ephemeral=True,
                )

            new_channel_id = int(interaction.data["values"][0])
            old_channel_id = self.fixtures[self.selected_fixture_index][2]
            team1, team2 = self.fixtures[self.selected_fixture_index][:2]

            if new_channel_id != old_channel_id:
                # Keep the same uniqueness rules used during fixture creation.
                if any(
                    index != self.selected_fixture_index
                    and fixture[2] == new_channel_id
                    for index, fixture in enumerate(self.fixtures)
                ):
                    return await interaction.response.send_message(
                        "❌ That stadium is already assigned to another fixture "
                        "in this repost. Choose a different stadium.",
                        ephemeral=True,
                    )

                conn = sqlite3.connect("players.db")
                c = conn.cursor()
                c.execute(
                    """SELECT 1 FROM fixtures
                       WHERE tournament_id = ? AND round_number = ?
                         AND channel_id = ?
                         AND NOT ((team1 = ? AND team2 = ?)
                                  OR (team1 = ? AND team2 = ?))
                       LIMIT 1""",
                    (
                        self.tournament_id,
                        self.round_number,
                        new_channel_id,
                        team1,
                        team2,
                        team2,
                        team1,
                    ),
                )
                used_by_round_fixture = c.fetchone()
                c.execute(
                    """SELECT 1 FROM fixtures
                       WHERE tournament_id = ? AND round_number != ?
                         AND channel_id = ?
                         AND ((team1 = ? AND team2 = ?)
                              OR (team1 = ? AND team2 = ?))
                       LIMIT 1""",
                    (
                        self.tournament_id,
                        self.round_number,
                        new_channel_id,
                        team1,
                        team2,
                        team2,
                        team1,
                    ),
                )
                used_by_previous_match = c.fetchone()
                conn.close()

                if used_by_round_fixture:
                    return await interaction.response.send_message(
                        "❌ That stadium is already assigned to another fixture "
                        "in this round. Choose a different stadium.",
                        ephemeral=True,
                    )
                if used_by_previous_match:
                    return await interaction.response.send_message(
                        "❌ This matchup used that stadium in an earlier round. "
                        "Choose a different stadium.",
                        ephemeral=True,
                    )

            self.fixtures[self.selected_fixture_index][2] = new_channel_id
            self.fixtures[self.selected_fixture_index][3] = MATCH_CHANNELS[
                new_channel_id
            ]
            await interaction.response.send_message(
                f"✅ Stadium changed for **{team1} vs {team2}** to "
                f"**{MATCH_CHANNELS[new_channel_id]}**.",
                ephemeral=True,
            )
            if self.message:
                await self.message.edit(content=self.summary(), view=self)

        stadium_select.callback = stadium_callback
        self.add_item(stadium_select)

        exact_button = Button(
            label="Post Exact Fixtures",
            emoji="📌",
            style=discord.ButtonStyle.success,
            custom_id="post_exact_saved_fixtures",
        )
        exact_button.callback = self.post_exact_callback
        self.add_item(exact_button)

        changed_button = Button(
            label="Post With Stadium Changes",
            emoji="🏟️",
            style=discord.ButtonStyle.primary,
            custom_id="post_changed_saved_fixtures",
        )
        changed_button.callback = self.post_changed_callback
        self.add_item(changed_button)

        cancel_button = Button(
            label="Cancel",
            style=discord.ButtonStyle.secondary,
            custom_id="cancel_saved_fixtures",
        )
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    async def _post(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message(
                "❌ This is not your menu!", ephemeral=True
            )

        await interaction.response.defer()
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        posted = await post_fixture_rows(
            self.ctx.bot,
            self.ctx.guild,
            [
                (team1, team2, channel_id, stadium)
                for team1, team2, channel_id, stadium in self.fixtures
            ],
            f"{self.tournament_name} - "
            f"{self.round_display_name or f'Group {self.group}'}",
        )
        if posted:
            await interaction.followup.send(
                f"✅ Reposted **{len(self.fixtures)}** fixture(s). "
                "Saved database fixtures were not changed."
            )
        else:
            await interaction.followup.send(
                "❌ Could not find the tournament fixtures channel."
            )
        self.stop()

    async def post_exact_callback(self, interaction: discord.Interaction):
        await self._post(interaction)

    async def post_changed_callback(self, interaction: discord.Interaction):
        await self._post(interaction)

    async def cancel_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message(
                "❌ This is not your menu!", ephemeral=True
            )
        await interaction.response.edit_message(
            content="❌ Fixture repost cancelled.", view=None
        )
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


def allocate_stadiums_for_matches(tournament_id, matchups, round_number):
    """
    Assign a unique stadium to every pending matchup.

    A stadium cannot be used twice in the same tournament round, and the
    same matchup cannot return to a stadium it used in an earlier round.
    Returns [(channel_id, stadium_name), ...] in the same order as matchups,
    or None when the available stadiums cannot satisfy both rules.
    """
    if len(matchups) > len(MATCH_CHANNELS):
        return None

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    c.execute(
        """SELECT channel_id FROM fixtures
           WHERE tournament_id = ? AND round_number = ?""",
        (tournament_id, round_number),
    )
    used_this_round = {row[0] for row in c.fetchall()}

    c.execute(
        """SELECT team1, team2, channel_id FROM fixtures
           WHERE tournament_id = ?""",
        (tournament_id,),
    )
    previous_stadiums = {}
    for team1, team2, channel_id in c.fetchall():
        matchup = frozenset((team1, team2))
        previous_stadiums.setdefault(matchup, set()).add(channel_id)
    conn.close()

    stadium_ids = list(MATCH_CHANNELS.keys())
    candidates = []
    for team1, team2 in matchups:
        matchup = frozenset((team1, team2))
        forbidden = previous_stadiums.get(matchup, set())
        options = [
            channel_id for channel_id in stadium_ids
            if channel_id not in used_this_round and channel_id not in forbidden
        ]
        candidates.append(options)

    # Assign the most constrained matchups first, then restore original order.
    order = sorted(range(len(matchups)), key=lambda index: len(candidates[index]))
    assignments = {}

    def backtrack(position, used):
        if position == len(order):
            return True

        fixture_index = order[position]
        options = candidates[fixture_index].copy()
        random.shuffle(options)
        for channel_id in options:
            if channel_id in used:
                continue
            assignments[fixture_index] = channel_id
            if backtrack(position + 1, used | {channel_id}):
                return True
            assignments.pop(fixture_index, None)
        return False

    if not backtrack(0, set()):
        return None

    return [
        (assignments[index], MATCH_CHANNELS[assignments[index]])
        for index in range(len(matchups))
    ]


def validate_fixture_stadiums(tournament_id, round_number, fixtures):
    """Return an error string if pending fixtures violate stadium rules."""
    channel_ids = [fixture[2] for fixture in fixtures]
    duplicates = {
        channel_id for channel_id in channel_ids
        if channel_ids.count(channel_id) > 1
    }
    if duplicates:
        duplicate_names = ", ".join(
            MATCH_CHANNELS.get(channel_id, str(channel_id))
            for channel_id in duplicates
        )
        return (
            f"Stadiums must be unique within a round. Repeated: "
            f"**{duplicate_names}**."
        )

    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(
        """SELECT team1, team2, channel_id
           FROM fixtures
           WHERE tournament_id = ?""",
        (tournament_id,),
    )
    previous = c.fetchall()
    conn.close()

    for team1, team2, channel_id, _ in fixtures:
        matchup = frozenset((team1, team2))
        if any(
            frozenset((old_team1, old_team2)) == matchup
            and old_channel_id == channel_id
            for old_team1, old_team2, old_channel_id in previous
        ):
            return (
                f"**{team1} vs {team2}** already used "
                f"**{MATCH_CHANNELS.get(channel_id, channel_id)}** "
                "in an earlier fixture. Choose a different stadium."
            )

    return None


def generate_group_round_robin(teams, round_index):
    """
    Generate fixtures for round_index (0-based) of a round-robin schedule
    for an odd number of teams. Uses the circle method with a BYE placeholder.
    Returns (matches_list, rest_team).
    Works for even numbers too (rest_team will be None).
    """
    teams = list(teams)
    # If odd, add BYE to make even
    if len(teams) % 2 == 1:
        all_slots = ['__BYE__'] + teams  # fix BYE at position 0
    else:
        all_slots = [teams[0]] + teams[1:]  # fix team 0
    m = len(all_slots)

    # Build rotated list for this round (circle method: fix slot 0, rotate rest)
    rotating = list(all_slots[1:])
    if round_index > 0:
        # Rotate left by round_index
        rotating = rotating[round_index:] + rotating[:round_index]
    slots = [all_slots[0]] + rotating

    matches = []
    rest_team = None
    for i in range(m // 2):
        t1 = slots[i]
        t2 = slots[m - 1 - i]
        if t1 == '__BYE__':
            rest_team = t2
        elif t2 == '__BYE__':
            rest_team = t1
        else:
            matches.append((t1, t2))
    return matches, rest_team


# Team Selection View
class TeamSelectionView(View):

    def __init__(self, ctx, tournament_name, all_teams):
        super().__init__(timeout=300)
        self.ctx = ctx
        self.tournament_name = tournament_name
        self.selected_teams = []
        self.selected_teams_0 = []
        self.selected_teams_1 = []
        self.all_teams = all_teams
        self.message = None

        self.add_team_select()

    def add_team_select(self):
        self.clear_items()
        chunks = [self.all_teams[:25], self.all_teams[25:]]
        labels = ["🏆 Select Teams (1-25)", "🏆 More Teams (26+)"]

        for idx, chunk in enumerate(chunks):
            if not chunk:
                continue
            options = []
            for team in chunk:
                flag = get_team_flag(team)
                is_selected = team in self.selected_teams
                label = f"{'✅ ' if is_selected else ''}{team}"
                options.append(discord.SelectOption(
                    label=label, value=team, emoji=flag,
                    description="Selected" if is_selected else "Click to select"
                ))
            selected_count = sum(1 for t in self.selected_teams if t in chunk)
            placeholder = f"{labels[idx]} ({selected_count} selected)"
            select = Select(
                placeholder=placeholder,
                options=options,
                custom_id=f"team_select_{idx}",
                min_values=0,
                max_values=len(options)
            )
            select.callback = self._make_team_callback(idx)
            self.add_item(select)

        self.add_item(self.confirm_button)

    def _make_team_callback(self, chunk_idx):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.ctx.author.id:
                await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
                return
            if chunk_idx == 0:
                self.selected_teams_0 = interaction.data['values']
            else:
                self.selected_teams_1 = interaction.data['values']
            self.selected_teams = self.selected_teams_0 + self.selected_teams_1
            self.add_team_select()
            embed = discord.Embed(
                title=f"🏆 Creating Tournament: {self.tournament_name}",
                description=f"**Selected Teams ({len(self.selected_teams)}):**\n" +
                    "\n".join([f"{get_team_flag(t)} {t}" for t in self.selected_teams])
                    if self.selected_teams else "No teams selected yet.",
                color=0x00FF00
            )
            embed.set_footer(text="Select teams from the dropdowns • Click Confirm when done")
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

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
                 available_teams, round_info=None, preseeded=False):
        super().__init__(timeout=600)
        self.ctx = ctx
        self.bot = bot
        self.tournament_id = tournament_id
        self.fixtures = fixtures  # List of [team1, team2, channel_id, stadium_name]
        self.round_number = round_number
        self.available_teams = available_teams
        self.round_info = round_info  # Optional dict with round_type, round_display_name, rest_team
        self.preseeded = preseeded
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

        if self.preseeded:
            stadium_options = [
                discord.SelectOption(
                    label=stadium_name,
                    value=str(channel_id),
                    emoji="🏟️",
                )
                for channel_id, stadium_name in MATCH_CHANNELS.items()
            ]
            stadium_select = Select(
                placeholder="Select Stadium",
                options=stadium_options,
                custom_id="stadium_select",
            )

            async def stadium_callback(inter: discord.Interaction):
                if inter.user.id != self.ctx.author.id:
                    await inter.response.send_message(
                        "❌ This is not your menu!", ephemeral=True
                    )
                    return

                new_channel_id = int(inter.data["values"][0])
                new_stadium = MATCH_CHANNELS[new_channel_id]
                self.fixtures[fixture_idx][2] = new_channel_id
                self.fixtures[fixture_idx][3] = new_stadium
                await inter.response.defer(ephemeral=True)
                self.add_controls()
                embed = await self.create_fixture_embed()
                await self.message.edit(embed=embed, view=self)
                await inter.followup.send(
                    f"✅ Stadium changed to {new_stadium}", ephemeral=True
                )
                try:
                    await interaction.delete_original_response()
                except:
                    pass

            stadium_select.callback = stadium_callback
            edit_view.add_item(stadium_select)
            await interaction.response.send_message(
                f"Editing preseeded fixture {fixture_idx + 1}: "
                "only the stadium can be changed.",
                view=edit_view,
                ephemeral=True,
            )
            return

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
            async def team1_callback(inter: discord.Interaction):
                if inter.user.id != self.ctx.author.id:
                    await inter.response.send_message(
                        "❌ This is not your menu!", ephemeral=True)
                    return
                new_team1 = inter.data['values'][0]
                self.fixtures[fixture_idx][0] = new_team1
                await inter.response.defer(ephemeral=True)
                self.add_controls()
                embed = await self.create_fixture_embed()
                await self.message.edit(embed=embed, view=self)
                await inter.followup.send(f"✅ Team 1 changed to {new_team1}", ephemeral=True)
                try:
                    await interaction.delete_original_response()
                except:
                    pass

            for t1_idx, t1_chunk in enumerate([team1_options[:25], team1_options[25:]]):
                if not t1_chunk:
                    continue
                t1_placeholder = "Select Team 1" if t1_idx == 0 else "Select Team 1 (more...)"
                t1_select = Select(placeholder=t1_placeholder, options=t1_chunk,
                                   custom_id=f"team1_select_{t1_idx}")
                t1_select.callback = team1_callback
                edit_view.add_item(t1_select)

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
            async def team2_callback(inter: discord.Interaction):
                if inter.user.id != self.ctx.author.id:
                    await inter.response.send_message(
                        "❌ This is not your menu!", ephemeral=True)
                    return
                new_team2 = inter.data['values'][0]
                self.fixtures[fixture_idx][1] = new_team2
                await inter.response.defer(ephemeral=True)
                self.add_controls()
                embed = await self.create_fixture_embed()
                await self.message.edit(embed=embed, view=self)
                await inter.followup.send(f"✅ Team 2 changed to {new_team2}", ephemeral=True)
                try:
                    await interaction.delete_original_response()
                except:
                    pass

            for t2_idx, t2_chunk in enumerate([team2_options[:25], team2_options[25:]]):
                if not t2_chunk:
                    continue
                t2_placeholder = "Select Team 2" if t2_idx == 0 else "Select Team 2 (more...)"
                t2_select = Select(placeholder=t2_placeholder, options=t2_chunk,
                                   custom_id=f"team2_select_{t2_idx}")
                t2_select.callback = team2_callback
                edit_view.add_item(t2_select)

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
            (
                "Select fixture to change its stadium • Click Confirm when ready"
                if self.preseeded
                else "Select fixture to edit teams/stadium • Click Confirm when ready"
            ))

        return embed

    @discord.ui.button(label="✅ Confirm & Post Fixtures",
                       style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction,
                             button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!",
                                                    ephemeral=True)
            return

        stadium_error = validate_fixture_stadiums(
            self.tournament_id, self.round_number, self.fixtures
        )
        if stadium_error:
            await interaction.response.send_message(
                f"❌ Cannot post these fixtures.\n{stadium_error}",
                ephemeral=True,
            )
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

        # Save round metadata if provided (group / intergroup rounds)
        if self.round_info:
            c.execute(
                """INSERT INTO tournament_round_info
                       (tournament_id, round_number, round_type, round_display_name, rest_team)
                       VALUES (?, ?, ?, ?, ?)""",
                (self.tournament_id, self.round_number,
                 self.round_info.get('round_type'),
                 self.round_info.get('round_display_name'),
                 self.round_info.get('rest_team')))

        conn.commit()
        conn.close()

        await self.post_fixtures()

        for item in self.children:
            item.disabled = True

        await self.message.edit(view=self)
        await interaction.followup.send("✅ Fixtures confirmed and posted!")

    async def post_fixtures(self):
        tournament = get_active_tournament()
        tournament_name = tournament[1] if tournament else "Tournament"
        fixture_rows = [
            (team1, team2, channel_id, stadium)
            for team1, team2, channel_id, stadium in self.fixtures
        ]
        await post_fixture_rows(
            self.bot,
            self.ctx.guild,
            fixture_rows,
            f"{tournament_name} - Round {self.round_number}",
        )


class Tournament(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        init_tournament_db()

    @commands.command(
        name="checkfixtureimage",
        help="[ADMIN] Preview a tournament fixture image with random teams and stadium",
    )
    @commands.has_permissions(administrator=True)
    async def checkfixtureimage(self, ctx):
        """Generate a fixture-image preview without creating a tournament fixture."""
        try:
            with open("players.json", "r", encoding="utf-8") as f:
                teams = [
                    team.get("team")
                    for team in json.load(f)
                    if team.get("team") and get_team_flag_url(team.get("team"))
                ]
        except (FileNotFoundError, json.JSONDecodeError):
            teams = []

        # Keep the preview grounded in the same teams supported by the
        # tournament flag renderer, with a safe fallback if player data changes.
        if len(teams) < 2:
            teams = [
                "India",
                "Pakistan",
                "Australia",
                "England",
                "New Zealand",
                "South Africa",
            ]

        team1, team2 = random.sample(teams, 2)
        stadium_channel_id, stadium_name = random.choice(
            list(MATCH_CHANNELS.items())
        )

        await ctx.send(
            f"🖼️ Generating fixture image preview: "
            f"**{team1} vs {team2}** at **{stadium_name}**…"
        )

        vs_image = await create_vs_image(team1, team2, stadium_name)
        if not vs_image:
            return await ctx.send("❌ Could not generate the fixture image preview.")

        file = discord.File(vs_image, filename="fixture_image_preview.png")
        embed = discord.Embed(
            title="Fixture Image Preview",
            description=(
                f"**{team1}** vs **{team2}**\n"
                f"🏟️ **{stadium_name}**\n"
                f"Channel ID: `{stadium_channel_id}`"
            ),
            color=0x00FF00,
        )
        embed.set_image(url="attachment://fixture_image_preview.png")
        await ctx.send(embed=embed, file=file)

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

    @commands.command(name="pts", aliases=["points", "pointstable"],
                      help="View tournament points table. Add A/B/C for a specific group.")
    async def points_table(self, ctx, group: str = None):
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, current_round = tournament

        if group:
            group = group.upper()
            if group not in ('A', 'B', 'C'):
                await ctx.send("❌ Invalid group. Use `A`, `B`, or `C`.\n"
                               "Example: `-pts A`  |  `-pts B`  |  `-pts C`")
                return
            teams = get_group_standings(tournament_id, group)
            title_text = f"Group {group} Standings"
            footer_text = "TOP 6 QUALIFY"
        else:
            conn = sqlite3.connect('players.db')
            c = conn.cursor()
            c.execute("""SELECT team_name, points, matches_played, wins, losses, nrr, fpp,
                                COALESCE(qualified, 0)
                         FROM tournament_teams
                         WHERE tournament_id = ?
                         ORDER BY points DESC, nrr DESC""", (tournament_id,))
            teams = c.fetchall()
            conn.close()
            title_text = "Points Table"
            footer_text = "TOP 2 TEAMS DIRECTLY TO SEMIS"

        if not teams:
            msg = (f"❌ No teams found in Group {group}! "
                   f"Use `-assigngroups` to assign teams to groups."
                   if group else "❌ No teams found in the tournament!")
            await ctx.send(msg)
            return

        table_image = await create_points_table_image(tournament_name, teams,
                                                       title_text=title_text)
        if not table_image:
            await ctx.send("❌ Failed to create points table image!")
            return

        file = discord.File(table_image, filename="points_table.png")
        embed = discord.Embed(
            title=f"🏆 {tournament_name}" + (f" — Group {group}" if group else ""),
            color=0xFFD700)
        embed.set_image(url="attachment://points_table.png")
        embed.set_footer(text=footer_text)
        await ctx.send(embed=embed, file=file)

    # ── GROUP MANAGEMENT ──────────────────────────────────────────────────

    @commands.command(name="assigngroups", aliases=["ag"],
                      help="[ADMIN] Assign tournament teams to Groups A, B, C")
    @commands.has_permissions(administrator=True)
    async def assigngroups(self, ctx):
        """Interactively assign each tournament team to Group A, B, or C."""
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, _ = tournament

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("""SELECT team_name, group_name FROM tournament_teams
                     WHERE tournament_id = ? ORDER BY team_name""",
                  (tournament_id,))
        all_team_rows = c.fetchall()
        conn.close()

        if not all_team_rows:
            await ctx.send("❌ No teams in the tournament!")
            return

        all_teams = [row[0] for row in all_team_rows]
        current_assignments = {row[0]: row[1] for row in all_team_rows}

        # Build a summary of current assignments for the embed description
        def _current_desc(assignments):
            lines = []
            for g in ('A', 'B', 'C'):
                in_g = [t for t, gn in assignments.items() if gn and gn.upper() == g]
                lines.append(f"**Group {g}:** {', '.join(in_g) if in_g else '*none*'}")
            unassigned = [t for t, gn in assignments.items() if not gn]
            if unassigned:
                lines.append(f"⚠️ **Unassigned:** {', '.join(unassigned)}")
            return "\n".join(lines)

        assignments = dict(current_assignments)

        def _group_default(group_letter):
            return ", ".join(
                team for team in all_teams
                if assignments.get(team) and assignments[team].upper() == group_letter
            )

        class GroupAssignModal(Modal, title="Assign Tournament Groups"):
            group_a = TextInput(
                label="Group A (comma-separated team names)",
                placeholder="Team 1, Team 2, Team 3",
                style=discord.TextStyle.paragraph,
                required=False,
                max_length=4000
            )
            group_b = TextInput(
                label="Group B (comma-separated team names)",
                placeholder="Team 10, Team 11, Team 12",
                style=discord.TextStyle.paragraph,
                required=False,
                max_length=4000
            )
            group_c = TextInput(
                label="Group C (comma-separated team names)",
                placeholder="Team 19, Team 20, Team 21",
                style=discord.TextStyle.paragraph,
                required=False,
                max_length=4000
            )

            def __init__(inner_self, parent_view):
                super().__init__()
                inner_self.parent_view = parent_view
                inner_self.group_a.default = _group_default('A')
                inner_self.group_b.default = _group_default('B')
                inner_self.group_c.default = _group_default('C')

            async def on_submit(inner_self, interaction: discord.Interaction):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message(
                        "❌ This assignment form belongs to the admin who opened it.",
                        ephemeral=True)
                    return

                # Accept commas, new lines, or a mixture of both. Matching is
                # case-insensitive while the database keeps the official name.
                team_by_lower = {team.lower(): team for team in all_teams}
                raw_groups = {
                    'A': inner_self.group_a.value,
                    'B': inner_self.group_b.value,
                    'C': inner_self.group_c.value
                }
                parsed_groups = {}
                unknown = []
                duplicate_groups = {}

                for group_letter, raw_value in raw_groups.items():
                    names = [
                        name.strip() for name in raw_value.replace("\n", ",").split(",")
                        if name.strip()
                    ]
                    parsed_groups[group_letter] = []
                    for name in names:
                        official_name = team_by_lower.get(name.lower())
                        if official_name is None:
                            unknown.append(name)
                            continue
                        if official_name in duplicate_groups:
                            duplicate_groups.setdefault(official_name, []).append(group_letter)
                        else:
                            duplicate_groups[official_name] = [group_letter]
                        if official_name not in parsed_groups[group_letter]:
                            parsed_groups[group_letter].append(official_name)

                duplicate_names = [
                    team for team, groups in duplicate_groups.items()
                    if len(groups) > 1
                ]
                oversized = [
                    f"Group {group_letter} has {len(group_teams)} teams (maximum is 9)"
                    for group_letter, group_teams in parsed_groups.items()
                    if len(group_teams) > 9
                ]

                if unknown or duplicate_names or oversized:
                    problems = []
                    if unknown:
                        problems.append(f"Unknown team(s): {', '.join(unknown)}")
                    if duplicate_names:
                        problems.append(
                            "Teams listed in multiple groups: "
                            + ", ".join(duplicate_names)
                        )
                    problems.extend(oversized)
                    await interaction.response.send_message(
                        "❌ Please fix the group assignment:\n• "
                        + "\n• ".join(problems),
                        ephemeral=True)
                    return

                new_assignments = {team: None for team in all_teams}
                for group_letter, group_teams in parsed_groups.items():
                    for team in group_teams:
                        new_assignments[team] = group_letter

                conn2 = sqlite3.connect('players.db')
                c2 = conn2.cursor()
                for team, group_name in new_assignments.items():
                    c2.execute(
                        "UPDATE tournament_teams SET group_name = ? "
                        "WHERE tournament_id = ? AND team_name = ?",
                        (group_name, tournament_id, team))
                conn2.commit()
                conn2.close()
                assignments.clear()
                assignments.update(new_assignments)

                await interaction.response.defer()
                for item in inner_self.parent_view.children:
                    item.disabled = True
                if inner_self.parent_view.message:
                    await inner_self.parent_view.message.edit(
                        embed=inner_self.parent_view._embed(),
                        view=inner_self.parent_view)

                summary = ""
                for group_letter in ('A', 'B', 'C'):
                    group_teams = sorted(parsed_groups[group_letter])
                    summary += (
                        f"**Group {group_letter}:** "
                        f"{', '.join(group_teams) if group_teams else '*empty*'}\n"
                    )
                unassigned = sorted(
                    team for team, group_name in new_assignments.items()
                    if not group_name
                )
                if unassigned:
                    summary += f"⚠️ **Still unassigned:** {', '.join(unassigned)}\n"

                done_embed = discord.Embed(
                    title="✅ Group Assignments Saved",
                    description=summary,
                    color=0x00FF00
                )
                done_embed.set_footer(
                    text="Use -setgroupfixtures A/B/C to generate group stage rounds.")
                await ctx.send(embed=done_embed)

        class GroupAssignView(View):
            def __init__(inner_self):
                super().__init__(timeout=300)
                inner_self.message = None

            def _embed(inner_self):
                return discord.Embed(
                    title=f"🏆 {tournament_name} — Group Assignment",
                    description=(
                        "Click **Open Assignment Form** and enter each group’s "
                        "team names separated by commas. You can assign up to "
                        "9 teams per group.\n\n"
                        "**Current assignments:**\n" + _current_desc(assignments)
                    ),
                    color=0x0066CC
                )

            @discord.ui.button(label="Open Assignment Form",
                               style=discord.ButtonStyle.primary,
                               custom_id="open_grp_assign")
            async def open_form(inner_self, interaction: discord.Interaction,
                                button: Button):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message(
                        "❌ Not your menu!", ephemeral=True)
                    return
                await interaction.response.send_modal(GroupAssignModal(inner_self))

        view = GroupAssignView()
        view.message = await ctx.send(embed=view._embed(), view=view)

    @commands.command(name="setgroupfixtures", aliases=["sgf"],
                      help="[ADMIN] Post next preseeded intra-group fixtures. Usage: -sgf <A/B/C>")
    @commands.has_permissions(administrator=True)
    async def setgroupfixtures(self, ctx, group: str):
        """Load and post the next preseeded round of intra-group fixtures."""
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        group = group.upper()
        if group not in ('A', 'B', 'C'):
            await ctx.send("❌ Specify group A, B, or C. Example: `-sgf A`")
            return

        tournament_id, tournament_name, _ = tournament

        group_teams_rows = get_group_standings(tournament_id, group)
        if not group_teams_rows:
            await ctx.send(
                f"❌ No teams found in Group {group}. "
                f"Use `-assigngroups` to assign teams to groups first.")
            return

        blocked_message = unfinished_group_round_message(tournament_id, group)
        if blocked_message:
            await ctx.send(blocked_message)
            return

        group_teams = [row[0] for row in group_teams_rows]

        # Count how many intra-group rounds have already been generated
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("""SELECT COUNT(*) FROM tournament_round_info
                     WHERE tournament_id = ? AND round_type = ?""",
                  (tournament_id, f'group_{group}'))
        rounds_done = c.fetchone()[0]
        conn.close()

        group_internal_round = rounds_done + 1
        preseeded_round, error = get_preseeded_group_round(
            tournament_name,
            group,
            group_internal_round,
            group_teams,
        )
        if error:
            await ctx.send(error)
            return
        matches, rest_team = preseeded_round

        target_round = get_next_tournament_round(tournament_id)

        stadium_assignments = allocate_stadiums_for_matches(
            tournament_id, matches, target_round
        )
        if stadium_assignments is None:
            await ctx.send(
                "❌ Could not assign unique stadiums for this round. "
                "Every fixture needs a different stadium, and a matchup "
                "cannot reuse a stadium from an earlier round."
            )
            return

        fixtures = [
            [t1, t2, channel_id, stadium]
            for (t1, t2), (channel_id, stadium) in zip(
                matches, stadium_assignments
            )
        ]

        round_display = f"Group {group} — Round {group_internal_round}"
        round_info = {
            'round_type': f'group_{group}',
            'round_display_name': round_display,
            'rest_team': rest_team
        }

        rest_note = f"\n⏸️ **Rest this round:** {rest_team}" if rest_team else ""
        await ctx.send(
            f"📋 Loading preseeded **{round_display}** "
            f"(Tournament Round {target_round}){rest_note}\n"
            f"Teams: {len(group_teams)} | Matches: {len(matches)}")

        conn2 = sqlite3.connect('players.db')
        c2 = conn2.cursor()
        c2.execute("SELECT team_name FROM tournament_teams WHERE tournament_id = ?",
                   (tournament_id,))
        all_teams = [row[0] for row in c2.fetchall()]
        conn2.close()

        view = FixtureEditView(ctx, self.bot, tournament_id, fixtures,
                               target_round, all_teams, round_info=round_info,
                               preseeded=True)
        embed = await view.create_fixture_embed()
        view.message = await ctx.send(embed=embed, view=view)

    @commands.command(
        name="postsamefixtures",
        help="[ADMIN] Repost the latest saved fixtures for a group. Usage: -postsamefixtures A",
    )
    @commands.has_permissions(administrator=True)
    async def postsamefixtures(self, ctx, group: str):
        """Repost a group's latest fixtures exactly as stored, without changing the DB."""
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        group = group.upper()
        if group not in ("A", "B", "C"):
            await ctx.send(
                "❌ Specify group A, B, or C. Example: `-postsamefixtures A`"
            )
            return

        tournament_id, tournament_name, _ = tournament
        conn = sqlite3.connect("players.db")
        c = conn.cursor()
        c.execute(
            """SELECT round_number, round_display_name
               FROM tournament_round_info
               WHERE tournament_id = ? AND round_type = ?
               ORDER BY round_number DESC
               LIMIT 1""",
            (tournament_id, f"group_{group}"),
        )
        round_info = c.fetchone()
        if not round_info:
            conn.close()
            await ctx.send(f"❌ No saved fixtures found for Group {group}.")
            return

        round_number, round_display_name = round_info
        c.execute(
            """SELECT team_name
               FROM tournament_teams
               WHERE tournament_id = ? AND UPPER(group_name) = ?""",
            (tournament_id, group),
        )
        group_teams = {row[0] for row in c.fetchall()}
        c.execute(
            """SELECT team1, team2, channel_id
               FROM fixtures
               WHERE tournament_id = ? AND round_number = ?
               ORDER BY id ASC""",
            (tournament_id, round_number),
        )
        stored_rows = [
            row for row in c.fetchall()
            if row[0] in group_teams and row[1] in group_teams
        ]
        conn.close()

        if not stored_rows:
            await ctx.send(
                f"❌ No fixtures found for the latest saved Group {group} round."
            )
            return

        view = SameFixturesRepostView(
            ctx=ctx,
            tournament_id=tournament_id,
            tournament_name=tournament_name,
            group=group,
            round_number=round_number,
            round_display_name=round_display_name,
            fixtures=[
                (team1, team2, channel_id, MATCH_CHANNELS.get(channel_id))
                for team1, team2, channel_id in stored_rows
            ],
        )
        view.message = await ctx.send(content=view.summary(), view=view)

    @commands.command(name="setigfixtures", aliases=["sigf"],
                      help="[ADMIN] Generate intergroup round fixtures. Usage: -sigf <1/2/3>")
    @commands.has_permissions(administrator=True)
    async def setigfixtures(self, ctx, ig_round: int):
        """
        Generate intergroup round fixtures matched by group standings rank.
          Round 1 → Group A (#1 A vs #1 B, #2 A vs #2 B, …)
          Round 2 → Group B vs Group C
          Round 3 → Group A vs Group C
        """
        if ig_round not in (1, 2, 3):
            await ctx.send(
                "❌ Specify intergroup round **1**, **2**, or **3**.\n"
                "• `-sigf 1` → Group A vs Group B (ranked by standings)\n"
                "• `-sigf 2` → Group B vs Group C\n"
                "• `-sigf 3` → Group A vs Group C")
            return

        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, _ = tournament

        blocked_message = unfinished_round_message(tournament_id)
        if blocked_message:
            await ctx.send(blocked_message)
            return

        group_map = {1: ('A', 'B'), 2: ('B', 'C'), 3: ('A', 'C')}
        g1, g2 = group_map[ig_round]

        standings_g1 = get_group_standings(tournament_id, g1)
        standings_g2 = get_group_standings(tournament_id, g2)

        if not standings_g1:
            await ctx.send(
                f"❌ No teams found in Group {g1}. "
                f"Use `-assigngroups` first.")
            return
        if not standings_g2:
            await ctx.send(
                f"❌ No teams found in Group {g2}. "
                f"Use `-assigngroups` first.")
            return

        num_matches = min(len(standings_g1), len(standings_g2))
        target_round = get_next_tournament_round(tournament_id)

        matchups = []
        match_desc = []
        for i in range(num_matches):
            t1 = standings_g1[i][0]   # rank i+1 in group g1
            t2 = standings_g2[i][0]   # rank i+1 in group g2
            matchups.append((t1, t2))
            flag1 = get_team_flag(t1)
            flag2 = get_team_flag(t2)
            match_desc.append(
                f"#{i+1} {flag1} {t1} vs {flag2} {t2} "
                f"*(#{i+1} {g1} vs #{i+1} {g2})*")

        stadium_assignments = allocate_stadiums_for_matches(
            tournament_id, matchups, target_round
        )
        if stadium_assignments is None:
            await ctx.send(
                "❌ Could not assign unique stadiums for this round. "
                "Every fixture needs a different stadium, and a matchup "
                "cannot reuse a stadium from an earlier round."
            )
            return

        fixtures = [
            [t1, t2, channel_id, stadium]
            for (t1, t2), (channel_id, stadium) in zip(
                matchups, stadium_assignments
            )
        ]

        round_display = f"Intergroup Round {ig_round} (Group {g1} vs Group {g2})"
        round_info = {
            'round_type': f'intergroup_{ig_round}',
            'round_display_name': round_display,
            'rest_team': None
        }

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("SELECT team_name FROM tournament_teams WHERE tournament_id = ?",
                  (tournament_id,))
        all_teams = [row[0] for row in c.fetchall()]
        conn.close()

        preview_embed = discord.Embed(
            title=f"🏆 {tournament_name} — {round_display}",
            description=(
                f"**Tournament Round:** {target_round}\n"
                f"**Matches:** {num_matches}\n\n"
                + "\n".join(match_desc)
            ),
            color=0xFF8C00
        )
        preview_embed.set_footer(
            text="Rankings from current group standings • Edit below before confirming")
        await ctx.send(embed=preview_embed)

        view = FixtureEditView(ctx, self.bot, tournament_id, fixtures,
                               target_round, all_teams, round_info=round_info)
        embed = await view.create_fixture_embed()
        view.message = await ctx.send(embed=embed, view=view)

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

        if not special_round:
            blocked_message = unfinished_round_message(tournament_id)
            if blocked_message:
                await ctx.send(blocked_message)
                return

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

                # Prevent two fixtures in the same round from sharing a
                # stadium, and prevent a repeated matchup from returning to
                # a stadium it has already used.
                conn = sqlite3.connect('players.db')
                c = conn.cursor()
                c.execute(
                    """SELECT id FROM fixtures
                       WHERE tournament_id = ? AND round_number = ?
                         AND channel_id = ?""",
                    (tournament_id, round_number, self.selected_channel_id),
                )
                duplicate_round_stadium = c.fetchone()
                c.execute(
                    """SELECT id FROM fixtures
                       WHERE tournament_id = ?
                         AND ((team1 = ? AND team2 = ?)
                              OR (team1 = ? AND team2 = ?))
                         AND channel_id = ?""",
                    (
                        tournament_id,
                        team1,
                        team2,
                        team2,
                        team1,
                        self.selected_channel_id,
                    ),
                )
                repeated_matchup_stadium = c.fetchone()
                conn.close()

                if duplicate_round_stadium and (
                    not is_reserve or duplicate_round_stadium[0] != existing[0]
                ):
                    await interaction.response.send_message(
                        "❌ That stadium is already assigned to another fixture "
                        "in this round. Choose a different stadium.",
                        ephemeral=True,
                    )
                    return

                if repeated_matchup_stadium and (
                    not is_reserve or repeated_matchup_stadium[0] != existing[0]
                ):
                    await interaction.response.send_message(
                        "❌ This matchup has already used that stadium in an "
                        "earlier fixture. Choose a different stadium.",
                        ephemeral=True,
                    )
                    return

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

        blocked_message = unfinished_round_message(tournament_id)
        if blocked_message:
            await ctx.send(blocked_message)
            return

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

            stadium_assignments = allocate_stadiums_for_matches(
                tournament_id, matching_result, target_round
            )
            if stadium_assignments is None:
                await ctx.send(
                    "❌ Could not assign unique stadiums for this round. "
                    "Every fixture needs a different stadium, and a matchup "
                    "cannot reuse a stadium from an earlier round."
                )
                return

            fixtures = [
                [t1, t2, channel_id, stadium]
                for (t1, t2), (channel_id, stadium) in zip(
                    matching_result, stadium_assignments
                )
            ]

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

    @commands.command(
        name="resetcurrentround",
        aliases=["rcr"],
        help="[ADMIN] Reset all unplayed fixtures in the active tournament's current round",
    )
    @commands.has_permissions(administrator=True)
    async def resetcurrentround(self, ctx):
        """Delete the active tournament's current round so it can be reposted."""
        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, current_round = tournament
        if current_round <= 0:
            await ctx.send("❌ The active tournament has no current round to reset.")
            return

        conn = sqlite3.connect("players.db")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT COUNT(*)
                   FROM fixtures
                   WHERE tournament_id = ? AND round_number = ? AND is_played = 1""",
                (tournament_id, current_round),
            )
            played_count = cursor.fetchone()[0]
            if played_count:
                await ctx.send(
                    f"❌ Cannot reset Round {current_round}: **{played_count}** "
                    "fixture(s) have already been played."
                )
                return

            cursor.execute(
                """SELECT COUNT(*)
                   FROM fixtures
                   WHERE tournament_id = ? AND round_number = ?""",
                (tournament_id, current_round),
            )
            fixture_count = cursor.fetchone()[0]
            cursor.execute(
                """SELECT COUNT(*)
                   FROM tournament_round_info
                   WHERE tournament_id = ? AND round_number = ?""",
                (tournament_id, current_round),
            )
            metadata_count = cursor.fetchone()[0]

            cursor.execute(
                """SELECT MAX(round_number)
                   FROM fixtures
                   WHERE tournament_id = ? AND round_number < ?""",
                (tournament_id, current_round),
            )
            previous_round = cursor.fetchone()[0] or 0

            conn.execute("BEGIN")
            cursor.execute(
                """DELETE FROM fixtures
                   WHERE tournament_id = ? AND round_number = ?""",
                (tournament_id, current_round),
            )
            deleted_fixtures = cursor.rowcount
            cursor.execute(
                """DELETE FROM tournament_round_info
                   WHERE tournament_id = ? AND round_number = ?""",
                (tournament_id, current_round),
            )
            deleted_metadata = cursor.rowcount
            cursor.execute(
                "UPDATE tournaments SET current_round = ? WHERE id = ?",
                (previous_round, tournament_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        await ctx.send(
            f"✅ Reset **{tournament_name} — Round {current_round}**.\n"
            f"Deleted **{deleted_fixtures}** fixture(s) and "
            f"**{deleted_metadata}** round metadata row(s).\n"
            f"Current round is now **{previous_round}**. "
            "You can repost the preseeded fixtures for all groups."
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
        in_tournament = False
        if tournament:
            tournament_id = tournament[0]
            conn = sqlite3.connect('players.db')
            c = conn.cursor()
            c.execute(
                "SELECT team_name FROM tournament_teams WHERE tournament_id = ? AND team_name = ?",
                (tournament_id, matched_team))
            in_tournament = bool(c.fetchone())
            conn.close()

        if in_tournament:
            # Full tournament overview (also shows series on page 0 via create_team_stats_embed)
            view = TeamStatsView(ctx, matched_team, self.bot)
            embed, _ = await view.create_team_stats_embed(0, "overview")
            view.update_buttons()
            view.message = await ctx.send(embed=embed, view=view)
        else:
            # No tournament — try series-only overview
            conn = sqlite3.connect('players.db')
            c = conn.cursor()
            c.execute("SELECT id, name, teams FROM series WHERE is_active = 1 ORDER BY id DESC")
            all_active_series = c.fetchall()

            team_series = []
            for sid, sname, steams_json in all_active_series:
                try:
                    steams = json.loads(steams_json) if steams_json else []
                except Exception:
                    steams = []
                if matched_team in steams:
                    c.execute(
                        """SELECT match_number, team1, team2, channel_id, is_played, winner
                           FROM series_fixtures
                           WHERE series_id = ? AND (team1 = ? OR team2 = ?)
                           ORDER BY match_number ASC""",
                        (sid, matched_team, matched_team))
                    sfixtures = c.fetchall()
                    team_series.append((sid, sname, sfixtures))
            conn.close()

            if not team_series:
                await ctx.send(
                    f"❌ **{matched_team}** is not in any active tournament or series!"
                )
                return

            flag = get_team_flag(matched_team)
            embed = discord.Embed(
                title=f"{flag} {matched_team} — Overview",
                color=get_team_color(matched_team)
            )

            for sid, sname, sfixtures in team_series:
                if not sfixtures:
                    embed.add_field(name=f"📋 Series: {sname}", value="No fixtures scheduled yet.", inline=False)
                    continue
                series_text = ""
                wins = losses = 0
                for match_num, t1, t2, ch_id, is_played, winner in sfixtures:
                    opp = t2 if t1 == matched_team else t1
                    opp_flag = get_team_flag(opp)
                    if is_played:
                        if winner == matched_team:
                            series_text += f"🟢 Match {match_num} vs {opp_flag} **{opp}** • ✅ Won\n"
                            wins += 1
                        elif winner:
                            series_text += f"🔴 Match {match_num} vs {opp_flag} **{opp}** • ❌ Lost\n"
                            losses += 1
                        else:
                            series_text += f"⚪ Match {match_num} vs {opp_flag} **{opp}** • Played\n"
                    else:
                        series_text += f"🏏 Match {match_num} vs {opp_flag} **{opp}** • <#{ch_id}>\n"

                played_count = wins + losses
                total = len(sfixtures)
                header = f"W {wins} – L {losses} | {played_count}/{total} played"
                embed.add_field(
                    name=f"📋 {sname} — {header}",
                    value=series_text or "No fixtures yet.",
                    inline=False
                )

            await ctx.send(embed=embed)

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
                chunks = [all_teams[:25], all_teams[25:]]
                placeholders = ["🏆 Select Tournament Winner", "🏆 More Teams..."]
                for idx, chunk in enumerate(chunks):
                    if not chunk:
                        continue
                    team_options = []
                    for team in chunk:
                        flag = get_team_flag(team)
                        team_options.append(discord.SelectOption(
                            label=team, value=team, emoji=flag
                        ))
                    select = Select(
                        placeholder=placeholders[idx],
                        options=team_options,
                        custom_id=f"winner_select_{idx}"
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


    @commands.command(name="editptsi", help="[ADMIN] Edit a series_teams value for a team in a specific series")
    @commands.has_permissions(administrator=True)
    async def editptsi_command(self, ctx, *, args: str = None):
        """
        Edit any field in series_teams for a specific series+team.
        Usage: -editptsi <series_name> | <team_name> | <field> | <value>
        Fields: wins, losses, matches_played, nrr
        Example: -editptsi ODI WC 2025 | India | wins | 5
        """
        if not args:
            await ctx.send(
                "**Usage:** `-editptsi <series_name> | <team_name> | <field> | <value>`\n"
                "**Fields:** `wins`, `losses`, `matches_played`, `nrr`\n"
                "**Example:** `-editptsi ODI WC 2025 | India | wins | 5`"
            )
            return

        parts = [p.strip() for p in args.split("|")]
        if len(parts) != 4:
            await ctx.send("❌ Please separate the 4 values with `|`.\n"
                           "**Usage:** `-editptsi <series_name> | <team_name> | <field> | <value>`")
            return

        series_name, team_name, field, raw_value = parts
        field = field.lower()

        allowed_fields = {"wins", "losses", "matches_played", "nrr"}
        if field not in allowed_fields:
            await ctx.send(f"❌ Invalid field `{field}`. Allowed: `wins`, `losses`, `matches_played`, `nrr`")
            return

        try:
            value = float(raw_value) if field == "nrr" else int(raw_value)
        except ValueError:
            await ctx.send(f"❌ Invalid value `{raw_value}` for field `{field}`.")
            return

        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Find matching series
        c.execute("SELECT id, name FROM series WHERE LOWER(name) LIKE ?", (f"%{series_name.lower()}%",))
        series_rows = c.fetchall()
        if not series_rows:
            conn.close()
            await ctx.send(f"❌ No series found matching **{series_name}**.")
            return
        if len(series_rows) > 1:
            names = "\n".join(f"• {r[1]}" for r in series_rows)
            conn.close()
            await ctx.send(f"❌ Multiple series matched. Be more specific:\n{names}")
            return

        series_id, series_display = series_rows[0]

        # Find matching team row
        c.execute(
            "SELECT id, team_name FROM series_teams WHERE series_id = ? AND LOWER(team_name) LIKE ?",
            (series_id, f"%{team_name.lower()}%")
        )
        team_rows = c.fetchall()
        if not team_rows:
            conn.close()
            await ctx.send(f"❌ No team matching **{team_name}** found in series **{series_display}**.")
            return
        if len(team_rows) > 1:
            names = "\n".join(f"• {r[1]}" for r in team_rows)
            conn.close()
            await ctx.send(f"❌ Multiple teams matched. Be more specific:\n{names}")
            return

        row_id, team_display = team_rows[0]

        # Fetch old value for confirmation
        c.execute(f"SELECT {field} FROM series_teams WHERE id = ?", (row_id,))
        old_value = c.fetchone()[0]

        # Apply update
        c.execute(f"UPDATE series_teams SET {field} = ? WHERE id = ?", (value, row_id))
        conn.commit()
        conn.close()

        embed = discord.Embed(
            title="✅ Series Team Updated",
            color=0x00CC66
        )
        embed.add_field(name="Series", value=series_display, inline=True)
        embed.add_field(name="Team", value=team_display, inline=True)
        embed.add_field(name="Field", value=field, inline=True)
        embed.add_field(name="Old Value", value=str(old_value), inline=True)
        embed.add_field(name="New Value", value=str(value), inline=True)
        embed.set_footer(text=f"Edited by {ctx.author.name}")
        await ctx.send(embed=embed)

    @commands.command(name="edittourney", help="[ADMIN] Edit a team's stat in the current tournament leaderboard")
    @commands.has_permissions(administrator=True)
    async def edittourney_command(self, ctx, *, args: str = None):
        """
        Edit any field shown in the current tournament's -pts leaderboard.
        Usage: -edittourney <team_name> | <field> | <value>
        Fields: points/pts, matches_played/m/mp, wins/w, losses/l, nrr, fpp, qualified/q
        Example: -edittourney India | points | 6
        """
        if not args:
            await ctx.send(
                "**Usage:** `-edittourney <team_name> | <field> | <value>`\n"
                "**Fields:** `points`/`pts`, `matches_played`/`m`, `wins`/`w`, "
                "`losses`/`l`, `nrr`, `fpp`, `qualified`/`q`\n"
                "**Example:** `-edittourney India | points | 6`"
            )
            return

        parts = [part.strip() for part in args.split("|")]
        if len(parts) != 3:
            await ctx.send(
                "❌ Please separate the 3 values with `|`.\n"
                "**Usage:** `-edittourney <team_name> | <field> | <value>`"
            )
            return

        team_name, field, raw_value = parts
        field = field.lower()
        field_aliases = {
            "pts": "points",
            "m": "matches_played",
            "mp": "matches_played",
            "w": "wins",
            "l": "losses",
            "q": "qualified",
        }
        field = field_aliases.get(field, field)
        allowed_fields = {
            "points", "matches_played", "wins", "losses",
            "nrr", "fpp", "qualified"
        }
        if field not in allowed_fields:
            allowed = ", ".join(sorted(allowed_fields))
            await ctx.send(f"❌ Invalid field `{field}`. Allowed: `{allowed}`")
            return

        try:
            value = float(raw_value) if field == "nrr" else int(raw_value)
        except ValueError:
            await ctx.send(f"❌ Invalid value `{raw_value}` for field `{field}`.")
            return

        if field == "qualified" and value not in (0, 1):
            await ctx.send("❌ `qualified` must be `0` (unqualified) or `1` (qualified).")
            return

        tournament = get_active_tournament()
        if not tournament:
            await ctx.send("❌ No active tournament found!")
            return

        tournament_id, tournament_name, _ = tournament
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        try:
            c.execute(
                """SELECT id, team_name
                   FROM tournament_teams
                   WHERE tournament_id = ? AND LOWER(team_name) LIKE ?""",
                (tournament_id, f"%{team_name.lower()}%")
            )
            team_rows = c.fetchall()
            if not team_rows:
                await ctx.send(
                    f"❌ No team matching **{team_name}** found in the active "
                    f"tournament (**{tournament_name}**)."
                )
                return
            if len(team_rows) > 1:
                names = "\n".join(f"• {row[1]}" for row in team_rows)
                await ctx.send(
                    f"❌ Multiple teams matched. Be more specific:\n{names}"
                )
                return

            row_id, team_display = team_rows[0]
            c.execute(f"SELECT {field} FROM tournament_teams WHERE id = ?", (row_id,))
            old_value = c.fetchone()[0]

            c.execute(
                f"UPDATE tournament_teams SET {field} = ? WHERE id = ?",
                (value, row_id)
            )
            conn.commit()
        except Exception as exc:
            await ctx.send(f"❌ Error updating tournament team: {exc}")
            return
        finally:
            conn.close()

        embed = discord.Embed(
            title="✅ Tournament Team Updated",
            color=0x00CC66
        )
        embed.add_field(name="Tournament", value=tournament_name, inline=True)
        embed.add_field(name="Team", value=team_display, inline=True)
        embed.add_field(name="Field", value=field, inline=True)
        embed.add_field(name="Old Value", value=str(old_value), inline=True)
        embed.add_field(name="New Value", value=str(value), inline=True)
        embed.set_footer(text=f"Edited by {ctx.author.name}")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Tournament(bot))