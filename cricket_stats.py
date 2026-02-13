import discord
import sqlite3
import re
import io
import aiohttp
import json
import os
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ========== HELPER FUNCTIONS ==========

def get_team_flag_url(team_name):
    """Get team flag emoji URL for images"""
    flag_codes = {
        "India": "1f1ee-1f1f3",  # 🇮🇳
        "Pakistan": "1f1f5-1f1f0",  # 🇵🇰
        "Australia": "1f1e6-1f1fa",  # 🇦🇺
        "England": "1f3f4-e0067-e0062-e0065-e006e-e0067-e007f",  # 🏴󠁧󠁢󠁥󠁮󠁧󠁿
        "New Zealand": "1f1f3-1f1ff",  # 🇳🇿
        "South Africa": "1f1ff-1f1e6",  # 🇿🇦
        "West Indies": "1f3f4",  # 🏴
        "Sri Lanka": "1f1f1-1f1f0",  # 🇱🇰
        "Bangladesh": "1f1e7-1f1e9",  # 🇧🇩
        "Afghanistan": "1f1e6-1f1eb",  # 🇦🇫
        "Netherlands": "1f1f3-1f1f1",  # 🇳🇱
        "Scotland": "1f3f4-e0067-e0062-e0073-e0063-e0074-e007f",  # 🏴󠁧󠁢󠁳󠁣󠁴󠁿
        "Ireland": "1f1ee-1f1ea",  # 🇮🇪
        "Zimbabwe": "1f1ff-1f1fc",  # 🇿🇼
        "UAE": "1f1e6-1f1ea",  # 🇦🇪
        "Canada": "1f1e8-1f1e6",  # 🇨🇦
        "USA": "1f1fa-1f1f8"  # 🇺🇸
    }
    code = flag_codes.get(team_name)
    if code:
        return f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{code}.png"
    return None

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
            LIMIT 100
        """)
    elif stat_type == "wickets":
        c.execute("""
            SELECT user_id, SUM(wickets) as total, SUM(balls_bowled) as balls
            FROM match_stats
            GROUP BY user_id
            HAVING total > 0
            ORDER BY total DESC
            LIMIT 100
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
            LIMIT 100
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
            LIMIT 100
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
            LIMIT 100
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
            LIMIT 100
        """)
    elif stat_type == "centuries":
        c.execute("""
            SELECT user_id, COUNT(*) as total
            FROM match_stats
            WHERE runs >= 100
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT 100
        """)
    elif stat_type == "fifties":
        c.execute("""
            SELECT user_id, COUNT(*) as total
            FROM match_stats
            WHERE runs >= 50 AND runs < 100
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT 100
        """)
    elif stat_type == "five_wickets":
        c.execute("""
            SELECT user_id, COUNT(*) as total
            FROM match_stats
            WHERE wickets >= 5
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT 100
        """)
    elif stat_type == "impact_points":
        c.execute("""
            SELECT user_id, 
                   SUM(runs + (wickets * 20)) as total_impact
            FROM match_stats
            GROUP BY user_id
            ORDER BY total_impact DESC
            LIMIT 100
        """)
    elif stat_type == "highest_score":
        c.execute("""
            SELECT user_id, MAX(runs) as highest, balls_faced
            FROM match_stats
            WHERE runs > 0
            GROUP BY user_id
            ORDER BY highest DESC
            LIMIT 100
        """)
    elif stat_type == "best_bowling":
        c.execute("""
            SELECT user_id, MAX(wickets) as best_wickets, 
                   runs_conceded, balls_bowled
            FROM match_stats
            WHERE wickets > 0
            GROUP BY user_id
            ORDER BY best_wickets DESC, runs_conceded ASC
            LIMIT 100
        """)
    elif stat_type == "ducks":
        c.execute("""
            SELECT user_id, COUNT(*) as total
            FROM match_stats
            WHERE runs = 0 AND balls_faced > 0 AND not_out = 0
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT 100
        """)
    elif stat_type == "most_runs_conceded":
        c.execute("""
            SELECT user_id, SUM(runs_conceded) as total
            FROM match_stats
            WHERE balls_bowled > 0
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT 100
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

def get_user_id_by_player_name(player_name):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM player_representatives WHERE player_name = ?", (player_name,))
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

def find_player(player_name):
    try:
        with open('players.json', 'r', encoding='utf-8') as f:
            teams_data = json.load(f)
    except:
        return None, None
    player_name_lower = player_name.lower()
    for team_data in teams_data:
        for player in team_data['players']:
            if player['name'].lower() == player_name_lower:
                return [player], [team_data['team']]
    matches = []
    match_teams = []
    for team_data in teams_data:
        for player in team_data['players']:
            if player_name_lower in player['name'].lower():
                matches.append(player)
                match_teams.append(team_data['team'])
    if matches:
        return matches, match_teams
    return None, None

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

def get_player_data(player_name):
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

def get_role_emoji(role):
    if "Wicketkeeper" in role:
        return "<:wicketkeeper:1451994159668920330>"
    elif "Batsman" in role:
        return "<:bat:1451967322146213980>"
    elif "Bowler" in role:
        return "<:ball:1451974295793172547>"
    elif "All-Rounder" in role or "All-rounder" in role:
        return "<:allrounder:1451978476033671279>"
    return ""

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

def get_active_tournament():
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT id, name, current_round FROM tournaments WHERE is_active = 1 LIMIT 1")
    result = c.fetchone()
    conn.close()
    return result

def update_tournament_stats(team1, team2, winner, team1_runs, team1_balls, team2_runs, team2_balls):
    tournament = get_active_tournament()
    if not tournament:
        return
    tournament_id = tournament[0]

    # Calculate run rates (runs per over)
    team1_rr = (team1_runs / team1_balls) * 6 if team1_balls > 0 else 0
    team2_rr = (team2_runs / team2_balls) * 6 if team2_balls > 0 else 0

    # FORCE winning team to ALWAYS have POSITIVE NRR change
    winner_nrr_change = abs(team1_rr - team2_rr)  # Always positive
    loser_nrr_change = -abs(team1_rr - team2_rr)  # Always negative

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    if winner == team1:
        # Team 1 won - gets POSITIVE NRR
        c.execute("""UPDATE tournament_teams SET points = points + 2, matches_played = matches_played + 1,
                    wins = wins + 1, nrr = nrr + ? WHERE tournament_id = ? AND team_name = ?""",
                 (winner_nrr_change, tournament_id, team1))
        # Team 2 lost - gets NEGATIVE NRR
        c.execute("""UPDATE tournament_teams SET matches_played = matches_played + 1, losses = losses + 1,
                    nrr = nrr + ? WHERE tournament_id = ? AND team_name = ?""",
                 (loser_nrr_change, tournament_id, team2))
    else:
        # Team 2 won - gets POSITIVE NRR
        c.execute("""UPDATE tournament_teams SET points = points + 2, matches_played = matches_played + 1,
                    wins = wins + 1, nrr = nrr + ? WHERE tournament_id = ? AND team_name = ?""",
                 (winner_nrr_change, tournament_id, team2))
        # Team 1 lost - gets NEGATIVE NRR
        c.execute("""UPDATE tournament_teams SET matches_played = matches_played + 1, losses = losses + 1,
                    nrr = nrr + ? WHERE tournament_id = ? AND team_name = ?""",
                 (loser_nrr_change, tournament_id, team1))

    c.execute("""UPDATE fixtures SET is_played = 1, winner = ?
                WHERE tournament_id = ? AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?)) AND is_played = 0""",
             (winner, tournament_id, team1, team2, team2, team1))
    conn.commit()
    conn.close()

def reverse_tournament_stats(team1, team2, winner, team1_runs, team1_balls, team2_runs, team2_balls):
    """Reverse tournament points table changes"""
    tournament = get_active_tournament()
    if not tournament:
        return

    tournament_id = tournament[0]

    # Calculate run rates (runs per over)
    team1_rr = (team1_runs / team1_balls) * 6 if team1_balls > 0 else 0
    team2_rr = (team2_runs / team2_balls) * 6 if team2_balls > 0 else 0

    team1_nrr_change = team1_rr - team2_rr
    team2_nrr_change = team2_rr - team1_rr

    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    if winner == team1:
        c.execute("""UPDATE tournament_teams 
                    SET points = points - 2,
                        matches_played = matches_played - 1,
                        wins = wins - 1,
                        nrr = nrr - ?
                    WHERE tournament_id = ? AND team_name = ?""",
                 (team1_nrr_change, tournament_id, team1))

        c.execute("""UPDATE tournament_teams 
                    SET matches_played = matches_played - 1,
                        losses = losses - 1,
                        nrr = nrr - ?
                    WHERE tournament_id = ? AND team_name = ?""",
                 (team2_nrr_change, tournament_id, team2))
    else:
        c.execute("""UPDATE tournament_teams 
                    SET points = points - 2,
                        matches_played = matches_played - 1,
                        wins = wins - 1,
                        nrr = nrr - ?
                    WHERE tournament_id = ? AND team_name = ?""",
                 (team2_nrr_change, tournament_id, team2))

        c.execute("""UPDATE tournament_teams 
                    SET matches_played = matches_played - 1,
                        losses = losses - 1,
                        nrr = nrr - ?
                    WHERE tournament_id = ? AND team_name = ?""",
                 (team1_nrr_change, tournament_id, team1))

    c.execute("""UPDATE fixtures 
                SET is_played = 0, winner = NULL
                WHERE tournament_id = ? 
                AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))""",
             (tournament_id, team1, team2, team2, team1))

    conn.commit()
    conn.close()

# ========== FANTASY HELPERS ==========

def get_india_nz_players():
    """Get all players from India and New Zealand teams"""
    try:
        with open('players.json', 'r', encoding='utf-8') as f:
            teams_data = json.load(f)
        
        india_players = []
        nz_players = []
        
        for team in teams_data:
            if team['team'] == 'India':
                india_players = [p['name'] for p in team['players']]
            elif team['team'] == 'New Zealand':
                nz_players = [p['name'] for p in team['players']]
        
        return india_players, nz_players
    except:
        return [], []

def get_fantasy_team(user_id):
    """Get user's fantasy team"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT team_data, total_points FROM fantasy_teams WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        return json.loads(result[0]), result[1]
    return None, 0

def save_fantasy_team(user_id, team_data):
    """Save user's fantasy team"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO fantasy_teams (user_id, team_data, total_points)
                 VALUES (?, ?, COALESCE((SELECT total_points FROM fantasy_teams WHERE user_id = ?), 0))""",
              (user_id, json.dumps(team_data), user_id))
    conn.commit()
    conn.close()

def update_fantasy_points(user_id, points_to_add):
    """Update fantasy team total points"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("UPDATE fantasy_teams SET total_points = total_points + ? WHERE user_id = ?",
              (points_to_add, user_id))
    conn.commit()
    conn.close()

def get_fantasy_leaderboard():
    """Get fantasy leaderboard data"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("""SELECT user_id, total_points, team_data 
                 FROM fantasy_teams 
                 ORDER BY total_points DESC""")
    results = c.fetchall()
    conn.close()
    return results

def calculate_fantasy_points_for_match(matches):
    """Calculate and award fantasy points after a match"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT user_id, team_data FROM fantasy_teams")
    fantasy_teams = c.fetchall()
    
    player_impact_points = {}
    for match in matches:
        user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out = map(int, match)
        player_name = get_player_name_by_user_id(user_id)
        if not player_name:
            continue
        impact_points = runs + (wickets * 20)
        player_impact_points[player_name] = impact_points
    
    points_awarded = {}
    for fantasy_user_id, team_data_json in fantasy_teams:
        team_data = json.loads(team_data_json)
        players_in_team = team_data['players']
        total_points = 0
        for player_name, impact in player_impact_points.items():
            if player_name in players_in_team:
                total_points += impact
        if total_points > 0:
            points_awarded[fantasy_user_id] = total_points
            update_fantasy_points(fantasy_user_id, total_points)
    
    conn.close()
    return points_awarded

# ========== VIEWS ==========

class PlayerSelectionView(discord.ui.View):
    def __init__(self, india_players, nz_players):
        super().__init__(timeout=300)
        self.selected_players = []
        self.india_players = india_players
        self.nz_players = nz_players
        self.selection_complete = False
        
        all_players = india_players + nz_players
        for i in range(0, len(all_players), 25):
            chunk = all_players[i:i+25]
            select = discord.ui.Select(
                placeholder=f"Select players ({i+1}-{min(i+25, len(all_players))})",
                min_values=0,
                max_values=min(11 - len(self.selected_players), len(chunk)),
                options=[
                    discord.SelectOption(
                        label=player,
                        value=player,
                        description=f"{'🇮🇳 India' if player in india_players else '🇳🇿 New Zealand'}"
                    )
                    for player in chunk
                ],
                custom_id=f"player_select_{i}"
            )
            select.callback = self.player_select_callback
            self.add_item(select)
    
    async def player_select_callback(self, interaction: discord.Interaction):
        for item in self.children:
            if isinstance(item, discord.ui.Select) and item.custom_id == interaction.data['custom_id']:
                selected = interaction.data['values']
                for player in self.selected_players[:]:
                    if player in [opt.value for opt in item.options]:
                        self.selected_players.remove(player)
                for player in selected:
                    if player not in self.selected_players:
                        self.selected_players.append(player)
                
                if len(self.selected_players) == 11:
                    self.selection_complete = True
                    for child in self.children:
                        child.disabled = True
                    await interaction.response.edit_message(
                        content=f"✅ **Team Selected!** ({len(self.selected_players)}/11 players)\n\n" + 
                                "\n".join([f"{i+1}. {p}" for i, p in enumerate(self.selected_players)]) +
                                "\n\n**Proceed to confirm your team.**",
                        view=self
                    )
                else:
                    await interaction.response.edit_message(
                        content=f"**Selecting Fantasy 11** ({len(self.selected_players)}/11 players selected)\n\n" +
                                ("**Selected Players:**\n" + "\n".join([f"{i+1}. {p}" for i, p in enumerate(self.selected_players)]) if self.selected_players else "No players selected yet.") +
                                f"\n\n{'⚠️ Select ' + str(11 - len(self.selected_players)) + ' more player(s)' if len(self.selected_players) < 11 else ''}",
                        view=self
                    )
                break

class ConfirmationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.confirmed = False
    
    @discord.ui.button(label="✅ Confirm Team", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.defer()
    
    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        self.stop()
        await interaction.response.defer()

class FantasyLeaderboardView(discord.ui.View):
    def __init__(self, bot, all_entries, items_per_page=10):
        super().__init__(timeout=120)
        self.bot = bot
        self.all_entries = all_entries
        self.items_per_page = items_per_page
        self.current_page = 0
        self.max_pages = max(1, (len(all_entries) + items_per_page - 1) // items_per_page)
        
    def get_page_embed(self):
        start_idx = self.current_page * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_entries = self.all_entries[start_idx:end_idx]
        
        embed = discord.Embed(
            title="🏆 Fantasy Cricket Leaderboard",
            description=f"**Top Fantasy 11 Teams**\n\n*Points are earned from player performances in matches*",
            color=0xFFD700
        )
        
        leaderboard_text = ""
        for i, (user_id, total_points, team_data_json) in enumerate(page_entries, start=start_idx + 1):
            team_data = json.loads(team_data_json)
            user = self.bot.get_user(user_id)
            username = user.name if user else f"User {user_id}"
            medal = ""
            if i == 1: medal = "🥇"
            elif i == 2: medal = "🥈"
            elif i == 3: medal = "🥉"
            player_count = len(team_data['players'])
            leaderboard_text += f"{medal} **{i}.** {username}\n"
            leaderboard_text += f"    └ **{total_points}** pts • {player_count} players\n\n"
        
        embed.add_field(
            name=f"Rankings ({start_idx + 1}-{min(end_idx, len(self.all_entries))} of {len(self.all_entries)})",
            value=leaderboard_text if leaderboard_text else "No teams yet!",
            inline=False
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.max_pages} • Create your team with /createfantasy11")
        return embed
    
    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.gray)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.get_page_embed(), view=self)
        else:
            await interaction.response.send_message("You're already on the first page!", ephemeral=True)
    
    @discord.ui.button(label="▶️ Next", style=discord.ButtonStyle.gray)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.max_pages - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.get_page_embed(), view=self)
        else:
            await interaction.response.send_message("You're already on the last page!", ephemeral=True)

class StatsView(View):
    def __init__(self, ctx, user_id):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.user_id = user_id

    async def create_stats_embed(self):
        stats = get_user_stats(self.user_id)
        if not stats:
            return discord.Embed(title="❌ Error", description="No stats found for this user!", color=0xFF0000)

        total_runs, total_balls_faced, total_runs_conceded, total_balls_bowled, total_wickets, times_not_out, matches_played = stats
        member = self.ctx.guild.get_member(self.user_id)
        player_name = get_player_name_by_user_id(self.user_id)
        team_name = get_user_team(self.user_id)
        color = get_team_color(team_name) if team_name else 0x0066CC
        player_data = None
        if player_name:
            players, _ = find_player(player_name)
            if players:
                player_data = players[0]

        embed = discord.Embed(color=color)

        if player_name and member:
            embed.set_author(name=f"{player_name} (@{member.name})",
                           icon_url=player_data['image'] if player_data and player_data.get('image') else None)
        elif member:
            embed.set_author(name=f"@{member.name}", icon_url=member.avatar.url if member.avatar else None)

        if team_name:
            flag = get_team_flag(team_name)
            embed.title = f"{flag}  ✦ Career Statistics"
        else:
            embed.title = "✦ Career Statistics"

        if player_data and player_data.get('image'):
            embed.set_thumbnail(url=player_data['image'])
        if member and member.avatar:
            embed.set_image(url=member.avatar.url)

        # Show role and style
        if player_data:
            role_emoji = get_role_emoji(player_data['role'])
            role_text = f"{role_emoji} **{player_data['role']}**\n"
            role_text += f"Batting: *{player_data.get('batting_style', 'N/A')}*\n"
            if player_data.get('bowling_style'):
                role_text += f"Bowling: *{player_data['bowling_style']}*"
            embed.add_field(name="Player Info", value=role_text, inline=False)

        # Calculate stats
        batting_avg = total_runs / (matches_played - times_not_out) if (matches_played - times_not_out) > 0 else total_runs
        strike_rate = (total_runs / total_balls_faced * 100) if total_balls_faced > 0 else 0
        economy = (total_runs_conceded / (total_balls_bowled / 6)) if total_balls_bowled > 0 else 0
        bowl_avg = (total_runs_conceded / total_wickets) if total_wickets > 0 else 0

        # Overall stats HORIZONTAL
        overall_text = f"**Matches:** {matches_played}  •  **Innings:** {matches_played}  •  **Not Outs:** {times_not_out or 0}"
        embed.add_field(name="📈 Overall", value=overall_text, inline=False)

        batting_text = (f"**Runs:** {total_runs or 0}  •  **Balls:** {total_balls_faced or 0}\n"
                       f"**Average:** {batting_avg:.2f}  •  **Strike Rate:** {strike_rate:.2f}")
        embed.add_field(name="🏏 Batting", value=batting_text, inline=True)

        bowl_avg_str = f"{bowl_avg:.2f}" if total_wickets > 0 else "N/A"
        bowling_text = (f"**Wickets:** {total_wickets or 0}  •  **Runs:** {total_runs_conceded or 0}\n"
                       f"**Economy:** {economy:.2f}  •  **Average:** {bowl_avg_str}")
        embed.add_field(name="🎳 Bowling", value=bowling_text, inline=True)

        if member and member.avatar:
            embed.set_footer(text="Nations Player 2025-2026", icon_url=member.avatar.url)
        else:
            embed.set_footer(text="Nations Player 2025-2026")

        return embed

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
            "bowling_average": "🎳 Best Bowling Average",
            "centuries": "💯 Most Centuries",
            "fifties": "5️⃣0️⃣ Most Fifties",
            "five_wickets": "🔥 Most 5-Wicket Hauls",
            "impact_points": "⭐ Most Impact Points",
            "highest_score": "🏆 Highest Score",
            "best_bowling": "🎯 Best Bowling Figures",
            "ducks": "🦆 Most Ducks",
            "most_runs_conceded": "💸 Most Runs Conceded"
        }

        data = get_leaderboard_data(self.stat_type)

        if not data:
            embed = discord.Embed(
                title=titles[self.stat_type],
                description="No data available yet.",
                color=0x00FF00
            )
            return embed, None

        # For runs/wickets: page 0 is graphic, rest are text pages (10 per page)
        # For all others: 10 players per page with pagination
        players_per_page = 10

        if self.stat_type in ["runs", "wickets"]:
            if page == 0:
                # Page 0: Show graphic
                embed = discord.Embed(
                    title=titles[self.stat_type],
                    description="🏆 **Top 5 Performers** 🏆",
                    color=0xFFD700
                )
                embed.set_image(url="attachment://leaderboard_top5.png")

                total_pages = ((len(data) - 1) // players_per_page) + 2
                embed.set_footer(text=f"Page 1 of {total_pages} • Visual Leaderboard")

                # Create graphic
                graphic = await create_top5_graphic(self.stat_type, data, self.ctx.guild, self.bot)
                return embed, graphic
            else:
                # Text pages: 10 players per page
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
                        balls = int(row[2])
                        overs = balls // 6
                        remaining_balls = balls % 6
                        overs_str = f"{overs}.{remaining_balls}" if remaining_balls > 0 else str(overs)
                        line = f"**{idx}.** {player_display}\n    └ {row[1]} runs ({overs_str} overs)\n\n"
                    else:  # wickets
                        balls = int(row[2])
                        overs = balls // 6
                        remaining_balls = balls % 6
                        overs_str = f"{overs}.{remaining_balls}" if remaining_balls > 0 else str(overs)
                        line = f"**{idx}.** {player_display}\n    └ {row[1]} wickets ({overs_str} overs)\n\n"

                    description += line

                embed.description = description

                total_pages = ((len(data) - 1) // players_per_page) + 2  # +1 for graphic page, +1 for ceiling
                embed.set_footer(text=f"Page {page + 1} of {total_pages} • Tournament Statistics")
                return embed, None
        else:
            # All other stats: paginated (10 per page)
            start_idx = page * players_per_page
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

                team_name = get_user_team(user_id)
                flag = get_team_flag(team_name) if team_name else ""
                emoji = get_player_emoji(player_name, self.bot) if player_name else "👤"

                player_display = f"{flag} {emoji} **{player_name}** (@{username})" if player_name else f"@{username}"

                line = ""
                if self.stat_type == "economy":
                    # Convert balls to overs
                    balls = int(row[2])
                    overs = balls // 6
                    remaining_balls = balls % 6
                    overs_str = f"{overs}.{remaining_balls}" if remaining_balls > 0 else str(overs)
                    line = f"**{idx}.** {player_display}\n    └ {row[3]:.2f} economy ({int(row[1])} runs in {overs_str} overs)\n\n"
                elif self.stat_type == "strike_rate":
                    balls = int(row[2])
                    overs = balls // 6
                    remaining_balls = balls % 6
                    overs_str = f"{overs}.{remaining_balls}" if remaining_balls > 0 else str(overs)
                    line = f"**{idx}.** {player_display}\n    └ {row[3]:.2f} SR ({int(row[1])} runs off {overs_str} overs)\n\n"
                elif self.stat_type == "average":
                    line = f"**{idx}.** {player_display}\n    └ {row[3]:.2f} average ({int(row[1])} runs, {int(row[2])} dismissals)\n\n"
                elif self.stat_type == "bowling_average":
                    line = f"**{idx}.** {player_display}\n    └ {row[3]:.2f} average ({int(row[1])} runs, {int(row[2])} wickets)\n\n"
                elif self.stat_type == "centuries":
                    line = f"**{idx}.** {player_display}\n    └ {row[1]} centuries\n\n"
                elif self.stat_type == "fifties":
                    line = f"**{idx}.** {player_display}\n    └ {row[1]} fifties\n\n"
                elif self.stat_type == "five_wickets":
                    line = f"**{idx}.** {player_display}\n    └ {row[1]} five-wicket hauls\n\n"
                elif self.stat_type == "impact_points":
                    line = f"**{idx}.** {player_display}\n    └ {int(row[1])} impact points\n\n"
                elif self.stat_type == "highest_score":
                    balls = int(row[2])
                    overs = balls // 6
                    remaining_balls = balls % 6
                    overs_str = f"{overs}.{remaining_balls}" if remaining_balls > 0 else str(overs)
                    line = f"**{idx}.** {player_display}\n    └ {row[1]} ({overs_str} overs)\n\n"
                elif self.stat_type == "best_bowling":
                    balls = int(row[3])
                    overs = balls // 6
                    remaining_balls = balls % 6
                    overs_str = f"{overs}.{remaining_balls}" if remaining_balls > 0 else str(overs)
                    line = f"**{idx}.** {player_display}\n    └ {row[1]}/{row[2]} ({overs_str} overs)\n\n"
                elif self.stat_type == "ducks":
                    line = f"**{idx}.** {player_display}\n    └ {row[1]} ducks\n\n"
                elif self.stat_type == "most_runs_conceded":
                    line = f"**{idx}.** {player_display}\n    └ {row[1]} runs conceded\n\n"

                if len(description) + len(line) > 4000:
                    description += "... (truncated)"
                    break
                description += line

            embed.description = description

            total_pages = ((len(data) - 1) // players_per_page) + 1
            embed.set_footer(text=f"Page {page + 1} of {total_pages} • Tournament Statistics")
            return embed, None

    def update_buttons(self):
        data = get_leaderboard_data(self.stat_type)

        if self.stat_type in ["runs", "wickets"]:
            total_pages = ((len(data) - 1) // 10) + 2  # +1 for graphic, +1 for ceiling
        else:
            total_pages = ((len(data) - 1) // 10) + 1  # 10 players per page for all other stats

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

    @discord.ui.button(label="⚡ Strike Rate", style=discord.ButtonStyle.primary, row=0)
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

    @discord.ui.button(label="💯 Centuries", style=discord.ButtonStyle.primary, row=1)
    async def centuries_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.stat_type = "centuries"
        self.current_page = 0

        embed, _ = await self.create_leaderboard_embed(0)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="5️⃣0️⃣ Fifties", style=discord.ButtonStyle.primary, row=1)
    async def fifties_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.stat_type = "fifties"
        self.current_page = 0

        embed, _ = await self.create_leaderboard_embed(0)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="🔥 5-fers", style=discord.ButtonStyle.danger, row=2)
    async def five_wickets_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.stat_type = "five_wickets"
        self.current_page = 0

        embed, _ = await self.create_leaderboard_embed(0)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="⭐ Impact", style=discord.ButtonStyle.danger, row=2)
    async def impact_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.stat_type = "impact_points"
        self.current_page = 0

        embed, _ = await self.create_leaderboard_embed(0)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="🏆 High Score", style=discord.ButtonStyle.danger, row=2)
    async def highest_score_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.stat_type = "highest_score"
        self.current_page = 0

        embed, _ = await self.create_leaderboard_embed(0)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="🎯 Best Bowl", style=discord.ButtonStyle.danger, row=2)
    async def best_bowling_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.stat_type = "best_bowling"
        self.current_page = 0

        embed, _ = await self.create_leaderboard_embed(0)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="🦆 Ducks", style=discord.ButtonStyle.secondary, row=3)
    async def ducks_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.stat_type = "ducks"
        self.current_page = 0

        embed, _ = await self.create_leaderboard_embed(0)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="💸 Runs Conceded", style=discord.ButtonStyle.secondary, row=3)
    async def runs_conceded_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        self.stat_type = "most_runs_conceded"
        self.current_page = 0

        embed, _ = await self.create_leaderboard_embed(0)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary, row=3)
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

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.secondary, row=3)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return

        data = get_leaderboard_data(self.stat_type)

        if self.stat_type in ["runs", "wickets"]:
            total_pages = ((len(data) - 1) // 10) + 2
        else:
            total_pages = ((len(data) - 1) // 10) + 1

        if self.current_page < total_pages - 1:
            self.current_page += 1

        embed, graphic = await self.create_leaderboard_embed(self.current_page)
        self.update_buttons()

        if graphic:
            file = discord.File(graphic, filename="leaderboard_top5.png")
            await interaction.response.edit_message(embed=embed, attachments=[file], view=self)
        else:
            await interaction.response.edit_message(embed=embed, attachments=[], view=self)

# ========== COG CLASS ==========

class CricketStats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="stats", aliases=["s", "mystats"])
    async def stats(self, ctx, member: discord.Member = None):
        """View your or another member's cricket career statistics"""
        target = member or ctx.author
        view = StatsView(ctx, target.id)
        embed = await view.create_stats_embed()
        await ctx.send(embed=embed, view=view)

    @commands.command(name="leaderboard", aliases=["lb", "top"])
    async def leaderboard(self, ctx, stat_type: str = "runs"):
        """View tournament leaderboards (runs, wickets, etc.)"""
        stat_type = stat_type.lower()
        valid_stats = ["runs", "wickets", "economy", "strike_rate", "average", "bowling_average", "centuries", "fifties", "five_wickets", "impact_points", "highest_score", "best_bowling", "ducks", "most_runs_conceded"]
        
        if stat_type not in valid_stats:
            await ctx.send(f"❌ Invalid stat type! Use one of: {', '.join(valid_stats)}")
            return

        view = LeaderboardView(ctx, stat_type, self.bot)
        embed, graphic = await view.create_leaderboard_embed(0)
        view.update_buttons()

        if graphic:
            file = discord.File(graphic, filename="leaderboard_top5.png")
            view.message = await ctx.send(embed=embed, file=file, view=view)
        else:
            view.message = await ctx.send(embed=embed, view=view)

    @app_commands.command(name="createfantasy11", description="Create your Fantasy 11 team from India and New Zealand players")
    async def create_fantasy11(self, interaction: discord.Interaction):
        """Create a Fantasy 11 team"""
        user_id = interaction.user.id
        existing_team, _ = get_fantasy_team(user_id)
        if existing_team:
            await interaction.response.send_message("❌ You already have a Fantasy 11 team!", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        india_players, nz_players = get_india_nz_players()
        if not india_players or not nz_players:
            await interaction.followup.send("❌ Could not load player data.", ephemeral=True)
            return
        
        view = PlayerSelectionView(india_players, nz_players)
        await interaction.followup.send(
            "**🏏 Create Your Fantasy 11 Team**\nSelect **exactly 11 players**.",
            view=view, ephemeral=True
        )
        await view.wait()
        
        if not view.selection_complete or len(view.selected_players) != 11:
            await interaction.followup.send("❌ Incomplete selection.", ephemeral=True)
            return
        
        india_count = sum(1 for p in view.selected_players if p in india_players)
        nz_count = sum(1 for p in view.selected_players if p in nz_players)
        confirm_embed = discord.Embed(title="🏆 Confirm Your Fantasy 11 Team", color=0xFFD700)
        confirm_embed.add_field(name="Selected Players", value="\n".join(view.selected_players))
        
        confirm_view = ConfirmationView()
        await interaction.followup.send(embed=confirm_embed, view=confirm_view, ephemeral=True)
        await confirm_view.wait()
        
        if not confirm_view.confirmed:
            await interaction.followup.send("❌ Cancelled.", ephemeral=True)
            return
        
        team_data = {'players': view.selected_players, 'india_count': india_count, 'nz_count': nz_count}
        save_fantasy_team(user_id, team_data)
        await interaction.followup.send("✅ Success!", ephemeral=True)

    @commands.command(name="fantasylb", aliases=["flb"])
    async def fantasylb(self, ctx):
        """View fantasy cricket leaderboard"""
        entries = get_fantasy_leaderboard()
        if not entries:
            await ctx.send("❌ No fantasy teams found yet!")
            return
        view = FantasyLeaderboardView(self.bot, entries)
        await ctx.send(embed=view.get_page_embed(), view=view)

async def setup(bot):
    await bot.add_cog(CricketStats(bot))

# Top 5 graphic function (simplified placeholder if not present)
async def create_top5_graphic(stat_type, data, guild, bot):
    # This would normally generate the leaderboard_top5.png
    # Returning a buffer from an existing image if available or dummy
    # For now, let's assume it works or return None
    return None
