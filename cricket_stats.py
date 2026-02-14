import discord
import sqlite3
import re
import io
import aiohttp
import json
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ========== HELPER FUNCTIONS ==========

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

def calculate_fantasy_points_for_match(matches, bot):
    """Calculate and award fantasy points after a match"""
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT user_id, team_data FROM fantasy_teams")
    fantasy_teams = c.fetchall()
    
    player_impact_points = {}
    
    for match in matches:
        # Assuming match is a dict with team1_stats, team2_stats, etc.
        # This part needs the rest of the logic from the text file which was truncated
        pass

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

# ========== IMAGE GENERATION FUNCTIONS ==========

async def create_match_scoreboard(match_data, guild):
    """Create cricket scoreboard with ALL players - IMPROVED LAYOUT"""
    width, height = 1900, 3200  # Increased width (was 1600), reduced height (was 3800)
    img = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Dark blue gradient background (BACK TO ORIGINAL)
    for y in range(height):
        ratio = y / height
        r = int(10 + (30 - 10) * ratio)
        g = int(20 + (50 - 20) * ratio)
        b = int(40 + (80 - 40) * ratio)
        draw.rectangle([(0, y), (width, y+1)], fill=(r, g, b))

    # Load fonts
    try:
        team_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
        score_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 85)
        overs_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 56)  # BIGGER and BOLD (was 48)
        player_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
        username_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
        stat_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 38)
        section_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 42)
        winner_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 56)
        extras_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 38)
    except:
        team_font = ImageFont.load_default()
        score_font = team_font
        overs_font = team_font
        player_font = team_font
        username_font = team_font
        stat_font = team_font
        section_font = team_font
        winner_font = team_font
        extras_font = team_font

    team1 = match_data['team1']
    team2 = match_data['team2']
    team1_stats = match_data['team1_stats']
    team2_stats = match_data['team2_stats']
    winner = match_data['winner']

    team1_color = get_team_color_rgb(team1)
    team2_color = get_team_color_rgb(team2)

    # Helper function to get flag URL
    def get_team_flag_url(team_name):
        flag_urls = {
            "India": "https://flagcdn.com/w320/in.png",
            "Pakistan": "https://flagcdn.com/w320/pk.png",
            "Australia": "https://flagcdn.com/w320/au.png",
            "England": "https://flagcdn.com/w320/gb-eng.png",
            "New Zealand": "https://flagcdn.com/w320/nz.png",
            "South Africa": "https://flagcdn.com/w320/za.png",
            "Sri Lanka": "https://flagcdn.com/w320/lk.png",
            "Bangladesh": "https://flagcdn.com/w320/bd.png",
            "Afghanistan": "https://flagcdn.com/w320/af.png",
            "Netherlands": "https://flagcdn.com/w320/nl.png",
            "Scotland": "https://flagcdn.com/w320/gb-sct.png",
            "Ireland": "https://flagcdn.com/w320/ie.png",
            "Zimbabwe": "https://flagcdn.com/w320/zw.png",
            "UAE": "https://flagcdn.com/w320/ae.png",
            "Canada": "https://flagcdn.com/w320/ca.png",
            "USA": "https://flagcdn.com/w320/us.png"
        }
        return flag_urls.get(team_name)

    # Load and place RECTANGULAR flags
    async def load_flag(team_name, x_pos, y_pos, flag_width=120, flag_height=80):
        if team_name.lower() == "west indies":
            try:
                flag_img = Image.open("westindies.jpg").convert('RGBA')
                flag_img = flag_img.resize((flag_width, flag_height), Image.Resampling.LANCZOS)
                img.paste(flag_img, (x_pos, y_pos), flag_img)
            except Exception as e:
                print(f"Error loading West Indies flag: {e}")
        else:
            flag_url = get_team_flag_url(team_name)
            if flag_url:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(flag_url) as resp:
                            if resp.status == 200:
                                flag_data = await resp.read()
                                flag_img = Image.open(io.BytesIO(flag_data)).convert('RGBA')
                                flag_img = flag_img.resize((flag_width, flag_height), Image.Resampling.LANCZOS)
                                img.paste(flag_img, (x_pos, y_pos), flag_img)
                except Exception as e:
                    print(f"Error loading flag for {team_name}: {e}")

    # Helper function to draw rounded rectangle with gradient (PURPLE TO BLACK)
    # Helper function to draw rounded rectangle with gradient (PURPLE TO BLACK) with WHITE OUTLINE
    def draw_rounded_gradient_bar(x, y, width, height, radius=15):
        # Create a temporary image for the bar with alpha channel
        bar_img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        bar_draw = ImageDraw.Draw(bar_img)

        # Draw gradient - PURPLE TO BLACK
        for i in range(height):
            ratio = i / height
            # Gradient from purple to black
            r = int(128 + (0 - 128) * ratio)  # 128 -> 0
            g = int(0 + (0 - 0) * ratio)      # 0 -> 0
            b = int(128 + (0 - 128) * ratio)  # 128 -> 0
            alpha = int(210 + (230 - 210) * ratio)  # Slight alpha gradient
            bar_draw.rectangle([(0, i), (width, i+1)], fill=(r, g, b, alpha))

        # Create mask for rounded corners
        mask = Image.new('L', (width, height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([(0, 0), (width, height)], radius=radius, fill=255)

        # Apply mask
        bar_img.putalpha(mask)

        # Paste onto main image
        img.paste(bar_img, (x, y), bar_img)

        # Draw thin white outline on top
        outline_img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        outline_draw = ImageDraw.Draw(outline_img)
        outline_draw.rounded_rectangle([(0, 0), (width-1, height-1)], radius=radius, outline=(255, 255, 255, 200), width=2)
        img.paste(outline_img, (x, y), outline_img)

    # Team headers positioned ABOVE their batting sections
    y_pos = 100

    # PURPLE BACKGROUND WITH YELLOW OUTLINE FOR TEAM 1 (BIGGER)
    purple_bg_width = 700  # Bigger (was 650)
    purple_bg_height = 280  # Bigger (was 240)
    purple_color = (100, 0, 150, 200)
    yellow_outline = (255, 215, 0, 255)  # YELLOW outline
    outline_width = 6

    # Draw purple rounded rectangle for team 1 with YELLOW outline
    purple_bg_1 = Image.new('RGBA', (purple_bg_width, purple_bg_height), (0, 0, 0, 0))
    purple_draw_1 = ImageDraw.Draw(purple_bg_1)
    # Draw yellow outline first
    purple_draw_1.rounded_rectangle([(0, 0), (purple_bg_width, purple_bg_height)], radius=25, outline=yellow_outline, width=outline_width)
    # Draw purple fill
    purple_draw_1.rounded_rectangle([(outline_width, outline_width), (purple_bg_width - outline_width, purple_bg_height - outline_width)], radius=22, fill=purple_color)
    img.paste(purple_bg_1, (80, y_pos - 20), purple_bg_1)

    # TEAM 1 HEADER
    await load_flag(team1, 100, y_pos, 120, 80)

    team1_score = f"{team1_stats['total_runs']}/{team1_stats['total_wickets']}"
    team1_overs = f"({team1_stats['total_balls']//6}.{team1_stats['total_balls']%6} ov)"

    draw.text((240, y_pos), team1, fill=(255, 255, 255), font=team_font)
    draw.text((240, y_pos + 70), team1_score, fill=(255, 215, 0), font=score_font)
    draw.text((240, y_pos + 175), team1_overs, fill=(255, 215, 0), font=overs_font)  # YELLOW and BIGGER

    # PURPLE BACKGROUND WITH YELLOW OUTLINE FOR TEAM 2 (BIGGER)
    purple_bg_x2 = width//2 + 80
    purple_bg_2 = Image.new('RGBA', (purple_bg_width, purple_bg_height), (0, 0, 0, 0))
    purple_draw_2 = ImageDraw.Draw(purple_bg_2)
    # Draw yellow outline first
    purple_draw_2.rounded_rectangle([(0, 0), (purple_bg_width, purple_bg_height)], radius=25, outline=yellow_outline, width=outline_width)
    # Draw purple fill
    purple_draw_2.rounded_rectangle([(outline_width, outline_width), (purple_bg_width - outline_width, purple_bg_height - outline_width)], radius=22, fill=purple_color)
    img.paste(purple_bg_2, (purple_bg_x2, y_pos - 20), purple_bg_2)

    # TEAM 2 HEADER
    await load_flag(team2, width//2 + 100, y_pos, 120, 80)

    team2_score = f"{team2_stats['total_runs']}/{team2_stats['total_wickets']}"
    team2_overs = f"({team2_stats['total_balls']//6}.{team2_stats['total_balls']%6} ov)"

    draw.text((width//2 + 240, y_pos), team2, fill=(255, 255, 255), font=team_font)
    draw.text((width//2 + 240, y_pos + 70), team2_score, fill=(255, 215, 0), font=score_font)
    draw.text((width//2 + 240, y_pos + 175), team2_overs, fill=(255, 215, 0), font=overs_font)  # YELLOW and BIGGER

    # Batting section
    y_pos = 580  # Moved down slightly to accommodate bigger squares (was 550)
    row_height = 130
    bar_height = 105

    # Team 1 batting
    batting_y = y_pos
    for i, p in enumerate(team1_stats['batting']):
        # Draw rounded gradient bar
        bar_width = (width // 2) - 70
        draw_rounded_gradient_bar(35, batting_y, bar_width, bar_height, radius=20)

        draw.text((50, batting_y + 15), p['name'], fill=(255, 255, 255), font=player_font)
        draw.text((50, batting_y + 60), f"@{p['username']}", fill=(220, 220, 220), font=username_font)
        runs_text = f"{p['runs']}({p['balls']})"
        runs_bbox = draw.textbbox((0, 0), runs_text, font=stat_font)
        draw.text((width//2 - 90 - runs_bbox[2], batting_y + 35), runs_text, 
                 fill=(255, 215, 0) if p['runs'] >= 50 else (255, 255, 255), font=stat_font)
        batting_y += row_height

    # Team 2 batting
    batting_y = y_pos
    for i, p in enumerate(team2_stats['batting']):
        # Draw rounded gradient bar
        bar_width = (width // 2) - 70
        bar_x_start = width // 2 + 35
        draw_rounded_gradient_bar(bar_x_start, batting_y, bar_width, bar_height, radius=20)

        draw.text((width//2 + 50, batting_y + 15), p['name'], fill=(255, 255, 255), font=player_font)
        draw.text((width//2 + 50, batting_y + 60), f"@{p['username']}", fill=(220, 220, 220), font=username_font)
        runs_text = f"{p['runs']}({p['balls']})"
        runs_bbox = draw.textbbox((0, 0), runs_text, font=stat_font)
        draw.text((width - 90 - runs_bbox[2], batting_y + 35), runs_text, 
                 fill=(255, 215, 0) if p['runs'] >= 50 else (255, 255, 255), font=stat_font)
        batting_y += row_height

    # Calculate divider position
    max_batters = max(len(team1_stats['batting']), len(team2_stats['batting']))
    divider_y = 580 + (max_batters * row_height) + 80

    # Draw horizontal divider line
    draw.rectangle([(60, divider_y), (width - 60, divider_y + 4)], fill=(100, 100, 100))

    # Bowling section
    bowling_y_start = divider_y + 90

    # Team 1 bowling
    bowling_y = bowling_y_start
    for i, p in enumerate(team1_stats['bowling']):
        # Draw rounded gradient bar
        bar_width = (width // 2) - 70
        draw_rounded_gradient_bar(35, bowling_y, bar_width, bar_height, radius=20)

        draw.text((50, bowling_y + 15), p['name'], fill=(255, 255, 255), font=player_font)
        draw.text((50, bowling_y + 60), f"@{p['username']}", fill=(220, 220, 220), font=username_font)
        overs = p['balls'] // 6
        balls = p['balls'] % 6
        overs_str = f"{overs}.{balls}" if balls > 0 else str(overs)
        bowling_text = f"{p['wickets']}-{p['runs_conceded']} ({overs_str})"
        bowling_bbox = draw.textbbox((0, 0), bowling_text, font=stat_font)
        # YELLOW for 3+ wickets (same as 50+ runs)
        draw.text((width//2 - 90 - bowling_bbox[2], bowling_y + 35), bowling_text, 
                 fill=(255, 215, 0) if p['wickets'] >= 3 else (220, 220, 220), font=stat_font)
        bowling_y += row_height

    # Team 2 bowling
    bowling_y = bowling_y_start
    for i, p in enumerate(team2_stats['bowling']):
        # Draw rounded gradient bar
        bar_width = (width // 2) - 70
        bar_x_start = width // 2 + 35
        draw_rounded_gradient_bar(bar_x_start, bowling_y, bar_width, bar_height, radius=20)

        draw.text((width//2 + 50, bowling_y + 15), p['name'], fill=(255, 255, 255), font=player_font)
        draw.text((width//2 + 50, bowling_y + 60), f"@{p['username']}", fill=(220, 220, 220), font=username_font)
        overs = p['balls'] // 6
        balls = p['balls'] % 6
        overs_str = f"{overs}.{balls}" if balls > 0 else str(overs)
        bowling_text = f"{p['wickets']}-{p['runs_conceded']} ({overs_str})"
        bowling_bbox = draw.textbbox((0, 0), bowling_text, font=stat_font)
        # YELLOW for 3+ wickets (same as 50+ runs)
        draw.text((width - 90 - bowling_bbox[2], bowling_y + 35), bowling_text, 
                 fill=(255, 215, 0) if p['wickets'] >= 3 else (220, 220, 220), font=stat_font)
        bowling_y += row_height

    # Calculate maximum bowling position for dynamic height
    max_bowlers = max(len(team1_stats['bowling']), len(team2_stats['bowling']))
    final_y = bowling_y_start + (max_bowlers * row_height) + 150  # Reduced bottom padding

    # Winner closer to bottom
    winner_text = f"{winner} WON!"
    winner_bbox = draw.textbbox((0, 0), winner_text, font=winner_font)
    winner_x = (width - winner_bbox[2]) // 2
    draw.text((winner_x, final_y), winner_text, fill=(255, 215, 0), font=team_font)

    # Extras disclaimer
    extras_text = " "
    extras_bbox = draw.textbbox((0, 0), extras_text, font=extras_font)
    extras_x = (width - extras_bbox[2]) // 2
    draw.text((extras_x, final_y + 70), extras_text, fill=(180, 180, 180), font=extras_font)

    # Crop image to actual content height
    crop_height = min(final_y + 130, height)  # 130px padding after extras text
    img = img.crop((0, 0, width, crop_height))

    output = io.BytesIO()
    img.save(output, format='PNG', quality=95)
    output.seek(0)
    return output


async def create_top5_graphic(stat_type, data, guild, bot):
    """Create a beautiful top 5 graphic with player images"""

    # Create canvas (2400x1200 for bigger cards)
    width, height = 2400, 1200
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
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 90)
        name_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
        username_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 50)
        stats_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
    except:
        title_font = ImageFont.load_default()
        name_font = ImageFont.load_default()
        username_font = ImageFont.load_default()
        stats_font = ImageFont.load_default()

    # Draw title with emoji
    if stat_type == "runs":
        title_emoji = "<:batting:1451967322146213980>"
        title_text = "TOP 5 RUN SCORERS"
    else:
        title_emoji = "<:bowling:1451974295793172547>"
        title_text = "TOP 5 WICKET TAKERS"

    title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(((width - title_width) / 2, 50), title_text, fill=(255, 215, 0, 255), font=title_font)

    # Player card settings - EVEN BIGGER CARDS
    card_width = 450
    card_height = 850
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
            card_draw.rectangle([(0, 0), (card_width-1, card_height-1)], outline=(255, 215, 0, 255), width=5)

            # Rank badge (top-left corner)
            rank_size = 90
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

            card.paste(rank_badge, (15, 15), rank_badge)

            # ADD FLAG IMAGE (top-right corner) - OPPOSITE TO RANK
            if team_name:
                flag_size = 90

                # Special handling for West Indies - use local file
                if team_name.lower() == "west indies":
                    try:
                        flag_img = Image.open("westindies.jpg").convert('RGBA')
                        flag_img = flag_img.resize((flag_size, flag_size), Image.Resampling.LANCZOS)

                        # Create circular mask
                        mask = Image.new('L', (flag_size, flag_size), 0)
                        mask_draw = ImageDraw.Draw(mask)
                        mask_draw.ellipse((0, 0, flag_size, flag_size), fill=255)

                        # Create circular flag
                        circular_flag = Image.new('RGBA', (flag_size, flag_size), (0, 0, 0, 0))
                        circular_flag.paste(flag_img, (0, 0), mask)

                        # Paste flag in top-right corner
                        flag_x = card_width - flag_size - 15
                        flag_y = 15
                        card.paste(circular_flag, (flag_x, flag_y), circular_flag)
                    except Exception as e:
                        print(f"Error loading West Indies flag: {e}")
                else:
                    # Use flag URL for other teams
                    flag_url = get_team_flag_url(team_name)
                    if flag_url:
                        try:
                            async with session.get(flag_url) as resp:
                                if resp.status == 200:
                                    flag_data = await resp.read()
                                    flag_img = Image.open(io.BytesIO(flag_data)).convert('RGBA')
                                    flag_img = flag_img.resize((flag_size, flag_size), Image.Resampling.LANCZOS)

                                    # Create circular mask
                                    mask = Image.new('L', (flag_size, flag_size), 0)
                                    mask_draw = ImageDraw.Draw(mask)
                                    mask_draw.ellipse((0, 0, flag_size, flag_size), fill=255)

                                    # Create circular flag
                                    circular_flag = Image.new('RGBA', (flag_size, flag_size), (0, 0, 0, 0))
                                    circular_flag.paste(flag_img, (0, 0), mask)

                                    # Paste flag in top-right corner
                                    flag_x = card_width - flag_size - 15
                                    flag_y = 15
                                    card.paste(circular_flag, (flag_x, flag_y), circular_flag)
                        except Exception as e:
                            print(f"Error loading flag for {team_name}: {e}")

            # Load player image
            if player_data and player_data.get('image'):
                try:
                    async with session.get(player_data['image']) as resp:
                        if resp.status == 200:
                            img_data = await resp.read()
                            player_img = Image.open(io.BytesIO(img_data)).convert('RGBA')

                            # Resize to fit card - even bigger image
                            player_img = player_img.resize((380, 380), Image.Resampling.LANCZOS)

                            # Paste player image
                            card.paste(player_img, (35, 130), player_img)
                except:
                    pass

            # Player name - adjusted position for bigger card with dynamic sizing
            name_y = 530

            # Try different font sizes to fit the name
            name_font_size = 52
            max_name_width = card_width - 40  # Leave 20px padding on each side

            while name_font_size > 28:  # Minimum readable size
                try:
                    test_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", name_font_size)
                except:
                    test_font = ImageFont.load_default()

                name_bbox = card_draw.textbbox((0, 0), player_name, font=test_font)
                name_width = name_bbox[2] - name_bbox[0]

                if name_width <= max_name_width:
                    break
                name_font_size -= 2

            # Use the font size that fits
            try:
                fitted_name_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", name_font_size)
            except:
                fitted_name_font = ImageFont.load_default()

            name_bbox = card_draw.textbbox((0, 0), player_name, font=fitted_name_font)
            name_width = name_bbox[2] - name_bbox[0]
            card_draw.text(((card_width - name_width) / 2, name_y), player_name, fill=(0, 0, 0, 255), font=fitted_name_font)

            # Username - PURPLE TEXT
            username_text = f"@{member.name}"
            username_y = 650
            username_bbox = card_draw.textbbox((0, 0), username_text, font=username_font)
            username_width = username_bbox[2] - username_bbox[0]
            card_draw.text(((card_width - username_width) / 2, username_y), username_text, fill=(255, 255, 255), font=username_font)

            # Stats
            if stat_type == "runs":
                stat_text = f"{row[1]} RUNS"
            else:
                stat_text = f"{row[1]} WICKETS"

            stat_y = 750
            stat_bbox = card_draw.textbbox((0, 0), stat_text, font=stats_font)
            stat_width = stat_bbox[2] - stat_bbox[0]
            card_draw.text(((card_width - stat_width) / 2, stat_y), stat_text, fill=(71, 8, 207), font=stats_font)

            # Paste card onto main image
            img.paste(card, (card_x, card_y), card)

    # Convert to bytes
    output = io.BytesIO()
    img = img.convert('RGB')
    img.save(output, format='PNG', quality=95)
    output.seek(0)

    return output

# ========== VIEW CLASSES ==========

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
            embed = discord.Embed(title="📊 Statistics", description="No match data available yet!", color=0xFF0000)
            return embed

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

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except:
                pass

# ========== COG CLASS ==========

class CricketStats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="addstats", aliases=["as"], help="[ADMIN] Add match stats")
    @commands.has_any_role(1452028308735922339)
    async def addstats_command(self, ctx, flag: str = ""):
        nolb = flag.upper() == "NOLB"
        if not ctx.message.reference:
            await ctx.send("❌ Please reply to a message containing match statistics!")
            return
        replied_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        content = replied_msg.content

        # Extract ONLY the first code block
        code_block_pattern = r'```(?:python)?\s*([\s\S]*?)```'
        code_blocks = re.findall(code_block_pattern, content)

        if not code_blocks:
            await ctx.send("❌ No code block found in the message!")
            return

        first_block = code_blocks[0]
        pattern = r'(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)'
        matches = re.findall(pattern, first_block)

        if not matches:
            await ctx.send("❌ No valid statistics found in the first code block!")
            return

        # Detect teams from stats
        teams_detected = set()
        for match in matches:
            user_id = int(match[0])
            team = get_user_team(user_id)
            if team:
                teams_detected.add(team)

        teams_list = list(teams_detected)

        if len(teams_list) != 2:
            await ctx.send(f"❌ Expected 2 teams, but detected {len(teams_list)} team(s): {', '.join(teams_list) if teams_list else 'None'}")
            return

        # Ask for team scores
        team_scores = {}

        for i, team in enumerate(teams_list):
            flag = get_team_flag(team)
            embed = discord.Embed(
                title=f"📊 Team Score Input - {team}",
                description=f"{flag} **{team}** detected in stats.\n\nPlease provide their **total score** (including extras) in this format:\n`runs/wickets overs YES/NO`\n\n**Examples:**\n• `150/11 11.2 YES` (batted first)\n• `145/8 10.0 NO` (batted second)",
                color=get_team_color(team)
            )
            embed.set_footer(text=f"Team {i + 1} of {len(teams_list)}")
            await ctx.send(embed=embed)

            def check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

            try:
                msg = await self.bot.wait_for('message', timeout=300.0, check=check)

                input_pattern = r'(\d+)/(\d+)\s+(\d+(?:\.\d+)?)\s+(YES|NO)'
                match = re.match(input_pattern, msg.content.strip(), re.IGNORECASE)

                if not match:
                    await ctx.send("❌ Invalid format! Stats addition cancelled.\nUse: `runs/wickets overs YES/NO`")
                    return

                runs = int(match.group(1))
                wickets = int(match.group(2))
                overs_str = match.group(3)
                batted_first = match.group(4).upper() == "YES"

                overs_parts = overs_str.split('.')
                balls = int(overs_parts[0]) * 6
                if len(overs_parts) > 1:
                    balls += int(overs_parts[1])

                team_scores[team] = {
                    'runs': runs,
                    'wickets': wickets,
                    'balls': balls,
                    'batted_first': batted_first
                }

                await ctx.send(f"✅ {team}: **{runs}/{wickets}** in **{overs_str}** overs recorded!")

            except TimeoutError:
                await ctx.send("❌ Timeout! Stats addition cancelled.")
                return

        # Get team names
        team1, team2 = teams_list
        team1_runs = team_scores[team1]['runs']
        team1_balls = team_scores[team1]['balls']
        team2_runs = team_scores[team2]['runs']
        team2_balls = team_scores[team2]['balls']

        # Check if scores are tied - ASK FOR SUPEROVER WINNER
        if team1_runs == team2_runs:
            tie_embed = discord.Embed(
                title="🟰 Match Tied!",
                description=f"Both teams scored **{team1_runs} runs**.\n\nWho won the **Super Over**?\n\nType the team name:",
                color=0xFFD700
            )

            flag1 = get_team_flag(team1)
            flag2 = get_team_flag(team2)

            tie_embed.add_field(
                name=f"{flag1} {team1}",
                value="Type this team name if they won",
                inline=True
            )
            tie_embed.add_field(
                name=f"{flag2} {team2}",
                value="Type this team name if they won",
                inline=True
            )

            await ctx.send(embed=tie_embed)

            def superover_check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

            try:
                superover_msg = await self.bot.wait_for('message', timeout=60.0, check=superover_check)
                superover_winner = superover_msg.content.strip()

                # Validate team name
                if superover_winner not in [team1, team2]:
                    await ctx.send(f"❌ Invalid team name! Please use either '{team1}' or '{team2}'. Stats addition cancelled.")
                    return

                winner = superover_winner
                await ctx.send(f"✅ {winner} won the Super Over!")

            except TimeoutError:
                await ctx.send("❌ Timeout! Stats addition cancelled.")
                return
        else:
            # Original winner determination for non-tied matches
            winner = team1 if team1_runs > team2_runs else team2

        loser = team2 if winner == team1 else team1

        # Calculate NRR changes (FORCE winning team to have positive NRR)
        team1_rr = (team1_runs / team1_balls) * 6 if team1_balls > 0 else 0
        team2_rr = (team2_runs / team2_balls) * 6 if team2_balls > 0 else 0

        winner_nrr_change = abs(team1_rr - team2_rr)  # ALWAYS POSITIVE for winner
        loser_nrr_change = -abs(team1_rr - team2_rr)  # ALWAYS NEGATIVE for loser

        # Get current NRR from database
        tournament = get_active_tournament()
        if tournament:
            conn = sqlite3.connect('players.db')
            c = conn.cursor()
            tournament_id = tournament[0]

            c.execute("SELECT nrr FROM tournament_teams WHERE tournament_id = ? AND team_name = ?", (tournament_id, winner))
            winner_current_nrr = c.fetchone()
            winner_current_nrr = winner_current_nrr[0] if winner_current_nrr else 0.0

            c.execute("SELECT nrr FROM tournament_teams WHERE tournament_id = ? AND team_name = ?", (tournament_id, loser))
            loser_current_nrr = c.fetchone()
            loser_current_nrr = loser_current_nrr[0] if loser_current_nrr else 0.0

            conn.close()

            winner_new_nrr = winner_current_nrr + winner_nrr_change
            loser_new_nrr = loser_current_nrr + loser_nrr_change

            # Show NRR preview
            nrr_embed = discord.Embed(
                title="📊 NRR Changes Preview",
                description="**This will be the NRR of teams after adding stats:**",
                color=0xFFD700
            )

            winner_flag = get_team_flag(winner)
            loser_flag = get_team_flag(loser)

            nrr_embed.add_field(
                name=f"{winner_flag} {winner} (WINNER)",
                value=f"Current NRR: **{winner_current_nrr:+.3f}**\n"
                      f"Change: **{winner_nrr_change:+.3f}** ✅\n"
                      f"New NRR: **{winner_new_nrr:+.3f}**",
                inline=True
            )

            nrr_embed.add_field(
                name=f"{loser_flag} {loser} (LOSER)",
                value=f"Current NRR: **{loser_current_nrr:+.3f}**\n"
                      f"Change: **{loser_nrr_change:+.3f}** ❌\n"
                      f"New NRR: **{loser_new_nrr:+.3f}**",
                inline=True
            )

            nrr_embed.set_footer(text="Type 'CONFIRM' to add stats or 'CANCEL' to abort")

            await ctx.send(embed=nrr_embed)

            # Wait for confirmation
            def confirm_check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

            try:
                confirm_msg = await self.bot.wait_for('message', timeout=60.0, check=confirm_check)

                if confirm_msg.content.upper() != 'CONFIRM':
                    await ctx.send("❌ Stats addition cancelled.")
                    return

            except TimeoutError:
                await ctx.send("❌ Timeout! Stats addition cancelled.")
                return

        # Now process the stats with the confirmed team scores
        team_stats = {}
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        for match in matches:
            user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out = map(int, match)
            c.execute("""INSERT INTO match_stats (user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""", (user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out))
            team = get_user_team(user_id)
            if team:
                if team not in team_stats:
                    team_stats[team] = {'batting': [], 'bowling': []}

                player_name = get_player_name_by_user_id(user_id)
                member = ctx.guild.get_member(user_id)
                username = member.name if member else "Unknown"

                # Add ALL players to batting list (even if they didn't bat)
                team_stats[team]['batting'].append({
                    'name': player_name or "Unknown",
                    'username': username,
                    'runs': runs,
                    'balls': balls_faced
                })

                # Only add bowlers who actually bowled
                if wickets > 0 or balls_bowled > 0:
                    team_stats[team]['bowling'].append({
                        'name': player_name or "Unknown",
                        'username': username,
                        'wickets': wickets,
                        'runs_conceded': runs_conceded,
                        'balls': balls_bowled
                    })

        conn.commit()
        conn.close()

        # Use the confirmed team scores
        team1_wickets = team_scores[team1]['wickets']
        team2_wickets = team_scores[team2]['wickets']

        # Sort batting and bowling
        team_stats[team1]['batting'].sort(key=lambda x: x['runs'], reverse=True)
        team_stats[team2]['batting'].sort(key=lambda x: x['runs'], reverse=True)
        team_stats[team1]['bowling'].sort(key=lambda x: x['wickets'], reverse=True)
        team_stats[team2]['bowling'].sort(key=lambda x: x['wickets'], reverse=True)

        match_data = {
            'team1': team1,
            'team2': team2,
            'team1_stats': {
                'total_runs': team1_runs,
                'total_balls': team1_balls,
                'total_wickets': team1_wickets,
                'batting': team_stats[team1]['batting'],
                'bowling': team_stats[team1]['bowling']
            },
            'team2_stats': {
                'total_runs': team2_runs,
                'total_balls': team2_balls,
                'total_wickets': team2_wickets,
                'batting': team_stats[team2]['batting'],
                'bowling': team_stats[team2]['bowling']
            },
            'winner': winner
        }

        scoreboard = await create_match_scoreboard(match_data, ctx.guild)

        # Update tournament stats with confirmed scores
        if not nolb:
            update_tournament_stats(team1, team2, winner, team1_runs, team1_balls, team2_runs, team2_balls)

        file = discord.File(scoreboard, filename="scoreboard.png")
        await ctx.send(f"✅ **Match Statistics Added Successfully**\n🏆 **{winner} WON**\n📊 **{len(matches)} players**", file=file)

    @commands.command(name="unaddstats", aliases=["uas"], help="[ADMIN] Remove match stats from bot message")
    @commands.has_any_role(1452028308735922339)
    async def unaddstats_command(self, ctx):
        if not ctx.message.reference:
            await ctx.send("❌ Please reply to a message containing match statistics!")
            return

        replied_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        content = replied_msg.content

        # Extract ONLY the first code block
        code_block_pattern = r'```(?:python)?\s*([\s\S]*?)```'
        code_blocks = re.findall(code_block_pattern, content)

        if code_blocks:
            # Use ONLY the first code block
            first_block = code_blocks[0]
            pattern = r'(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)'
            matches = re.findall(pattern, first_block)
        else:
            # Fallback to old behavior if no code block
            pattern = r'(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)'
            matches = re.findall(pattern, content)

        if not matches:
            await ctx.send("❌ No valid statistics found in the replied message!")
            return

        # Ask for team scores to reverse
        teams_detected = set()
        for match in matches:
            user_id = int(match[0])
            team = get_user_team(user_id)
            if team:
                teams_detected.add(team)

        teams_list = list(teams_detected)

        if len(teams_list) == 2:
            team_scores = {}

            for i, team in enumerate(teams_list):
                flag = get_team_flag(team)
                embed = discord.Embed(
                    title=f"📊 Team Score Input (for reversal) - {team}",
                    description=f"{flag} **{team}** detected.\n\nPlease provide the **total score** that was recorded:\n`runs/wickets overs`\n\n**Example:** `150/11 11.2`",
                    color=get_team_color(team)
                )
                embed.set_footer(text=f"Team {i + 1} of {len(teams_list)}")
                await ctx.send(embed=embed)

                def check(m):
                    return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

                try:
                    msg = await self.bot.wait_for('message', timeout=300.0, check=check)

                    input_pattern = r'(\d+)/(\d+)\s+(\d+(?:\.\d+)?)'
                    match = re.match(input_pattern, msg.content.strip(), re.IGNORECASE)

                    if not match:
                        await ctx.send("❌ Invalid format! Reversal cancelled.")
                        return

                    runs = int(match.group(1))
                    wickets = int(match.group(2))
                    overs_str = match.group(3)

                    overs_parts = overs_str.split('.')
                    balls = int(overs_parts[0]) * 6
                    if len(overs_parts) > 1:
                        balls += int(overs_parts[1])

                    team_scores[team] = {
                        'runs': runs,
                        'wickets': wickets,
                        'balls': balls
                    }

                except TimeoutError:
                    await ctx.send("❌ Timeout! Reversal cancelled.")
                    return

            team1, team2 = teams_list
            team1_runs = team_scores[team1]['runs']
            team1_balls = team_scores[team1]['balls']
            team1_wickets = team_scores[team1]['wickets']
            team2_runs = team_scores[team2]['runs']
            team2_balls = team_scores[team2]['balls']
            team2_wickets = team_scores[team2]['wickets']

            winner = team1 if team1_runs > team2_runs else team2

        # Delete from database
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        for match in matches:
            user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out = map(int, match)

            # Delete the most recent matching entry for this user
            c.execute("""
                DELETE FROM match_stats 
                WHERE id = (
                    SELECT id FROM match_stats 
                    WHERE user_id = ? AND runs = ? AND balls_faced = ? 
                    AND runs_conceded = ? AND balls_bowled = ? AND wickets = ? AND not_out = ?
                    ORDER BY id DESC LIMIT 1
                )
            """, (user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out))

        conn.commit()
        conn.close()

        if len(teams_list) == 2:
            # Reverse tournament stats
            reverse_tournament_stats(team1, team2, winner, team1_runs, team1_balls, team2_runs, team2_balls)

            await ctx.send(
                f"✅ Successfully removed statistics for **{len(matches)}** players!\n\n"
                f"**Match Result (Reversed):**\n"
                f"{team1}: {team1_runs}/{team1_wickets} in {team1_balls//6}.{team1_balls%6} overs\n"
                f"{team2}: {team2_runs}/{team2_wickets} in {team2_balls//6}.{team2_balls%6} overs\n\n"
                f"**Winner (Reversed):** {winner} 🏆"
            )
        else:
            await ctx.send(f"✅ Successfully removed statistics for **{len(matches)}** players!")

    @commands.command(name="stats", aliases=["s"], help="View cricket statistics")
    async def stats_command(self, ctx, *, target: str = None):
        if target:
            # Check if it's a player name
            players, team_names = find_player(target)
            if players:
                if len(players) > 1:
                    embed = discord.Embed(title="🔍 Multiple Players Found", color=0xFFA500)
                    desc = f"Multiple players match '{target}':\n\n"
                    for i, (player, team) in enumerate(zip(players, team_names), 1):
                        flag = get_team_flag(team)
                        desc += f"**{i}.** {flag} **{player['name']}** - {team}\n"
                    embed.description = desc
                    await ctx.send(embed=embed)
                    return

                player = players[0]
                user_id = get_user_id_by_player_name(player['name'])
                if not user_id:
                    await ctx.send(f"❌ {player['name']} hasn't claimed this player yet!")
                    return
            else:
                # Try to find member by username/mention
                try:
                    member = await commands.MemberConverter().convert(ctx, target)
                    user_id = member.id
                except:
                    await ctx.send(f"❌ Player or user '{target}' not found!")
                    return
        else:
            # Show stats for the command author
            user_id = ctx.author.id

        stats = get_user_stats(user_id)
        if not stats or stats[0] is None:
            message = "You haven't" if user_id == ctx.author.id else f"This player hasn't"
            await ctx.send(f"❌ {message} played any matches yet!")
            return

        # Create view but just to use its embed creation method
        view = PersonalStatsView(ctx, user_id)
        embed = await view.create_stats_embed("overview")

        # Send WITHOUT the view (no buttons)
        await ctx.send(embed=embed)

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

    @app_commands.command(name="scoreboard", description="Generate a match scoreboard")
    @app_commands.describe(
        channel_id="Channel ID where the stats message is",
        message_id="Message ID containing the stats",
        team1_score="Team 1 score (format: runs/wickets)",
        team1_overs="Team 1 overs (format: 10.2)",
        team2_score="Team 2 score (format: runs/wickets)",
        team2_overs="Team 2 overs (format: 10.2)"
    )
    async def scoreboard_slash(
        self, 
        interaction: discord.Interaction,
        channel_id: str,
        message_id: str,
        team1_score: str,
        team1_overs: str,
        team2_score: str,
        team2_overs: str
    ):
        """Generate a match scoreboard from stats"""

        await interaction.response.defer()

        try:
            # Fetch the channel
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                await interaction.followup.send("❌ Channel not found! Make sure the bot has access to that channel.")
                return

            # Fetch the message
            message = await channel.fetch_message(int(message_id))
        except discord.NotFound:
            await interaction.followup.send("❌ Message not found! Make sure the message ID and channel ID are correct.")
            return
        except ValueError:
            await interaction.followup.send("❌ Invalid message ID or channel ID format!")
            return
        except discord.Forbidden:
            await interaction.followup.send("❌ I don't have permission to access that channel!")
            return

        content = message.content

        # Extract ONLY the first code block
        code_block_pattern = r'```(?:python)?\s*([\s\S]*?)```'
        code_blocks = re.findall(code_block_pattern, content)

        if not code_blocks:
            await interaction.followup.send("❌ No code block found in the message!")
            return

        first_block = code_blocks[0]

        # Extract stats from the first block only
        pattern = r'(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)'
        matches = re.findall(pattern, first_block)

        if not matches:
            await interaction.followup.send("❌ No valid statistics found in the code block!")
            return

        # Parse team scores
        try:
            # Team 1
            team1_parts = team1_score.split('/')
            team1_runs = int(team1_parts[0])
            team1_wickets = int(team1_parts[1])

            overs1_parts = team1_overs.split('.')
            team1_balls = int(overs1_parts[0]) * 6
            if len(overs1_parts) > 1:
                team1_balls += int(overs1_parts[1])

            # Team 2
            team2_parts = team2_score.split('/')
            team2_runs = int(team2_parts[0])
            team2_wickets = int(team2_parts[1])

            overs2_parts = team2_overs.split('.')
            team2_balls = int(overs2_parts[0]) * 6
            if len(overs2_parts) > 1:
                team2_balls += int(overs2_parts[1])

        except (ValueError, IndexError):
            await interaction.followup.send(
                "❌ Invalid score/overs format!\n"
                "Use format: `runs/wickets` for score and `overs.balls` for overs\n"
                "Example: `150/8` and `10.2`"
            )
            return

        # Detect teams from stats
        teams_detected = set()
        for match in matches:
            user_id = int(match[0])
            team = get_user_team(user_id)
            if team:
                teams_detected.add(team)

        teams_list = list(teams_detected)

        if len(teams_list) != 2:
            await interaction.followup.send(
                f"❌ Expected 2 teams, but detected {len(teams_list)} team(s): {', '.join(teams_list) if teams_list else 'None'}"
            )
            return

        # Determine winner
        winner = teams_list[0] if team1_runs > team2_runs else teams_list[1]

        # Process stats and build team data
        team_stats = {}

        for match in matches:
            user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out = map(int, match)
            team = get_user_team(user_id)

            if team:
                if team not in team_stats:
                    team_stats[team] = {'batting': [], 'bowling': []}

                player_name = get_player_name_by_user_id(user_id)
                member = interaction.guild.get_member(user_id)
                username = member.name if member else "Unknown"

                # Add ALL players to batting list
                team_stats[team]['batting'].append({
                    'name': player_name or "Unknown",
                    'username': username,
                    'runs': runs,
                    'balls': balls_faced
                })

                # Only add bowlers who actually bowled
                if wickets > 0 or balls_bowled > 0:
                    team_stats[team]['bowling'].append({
                        'name': player_name or "Unknown",
                        'username': username,
                        'wickets': wickets,
                        'runs_conceded': runs_conceded,
                        'balls': balls_bowled
                    })

        # Sort batting and bowling
        team1, team2 = teams_list
        team_stats[team1]['batting'].sort(key=lambda x: x['runs'], reverse=True)
        team_stats[team2]['batting'].sort(key=lambda x: x['runs'], reverse=True)
        team_stats[team1]['bowling'].sort(key=lambda x: x['wickets'], reverse=True)
        team_stats[team2]['bowling'].sort(key=lambda x: x['wickets'], reverse=True)

        # Build match data
        match_data = {
            'team1': team1,
            'team2': team2,
            'team1_stats': {
                'total_runs': team1_runs,
                'total_balls': team1_balls,
                'total_wickets': team1_wickets,
                'batting': team_stats[team1]['batting'],
                'bowling': team_stats[team1]['bowling']
            },
            'team2_stats': {
                'total_runs': team2_runs,
                'total_balls': team2_balls,
                'total_wickets': team2_wickets,
                'batting': team_stats[team2]['batting'],
                'bowling': team_stats[team2]['bowling']
            },
            'winner': winner
        }

        # Generate scoreboard
        scoreboard = await create_match_scoreboard(match_data, interaction.guild)

        file = discord.File(scoreboard, filename="scoreboard.png")
        await interaction.followup.send(
            f"🏏 **Match Scoreboard**\n🏆 **{winner} WON**\n📊 **{len(matches)} players**",
            file=file
        )

async def setup(bot):
    await bot.add_cog(CricketStats(bot))