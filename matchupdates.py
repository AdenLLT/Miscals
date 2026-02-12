import discord
from discord.ext import commands
import json
import random
import re
from PIL import Image, ImageDraw, ImageFont
import io
import sqlite3
import asyncio
import aiohttp

# The bot user ID to monitor
CRICKET_BOT_ID = 753191385296928808

# MANUAL TEAM ABBREVIATIONS
TEAM_ABBREVIATIONS = {
    "India": "IND",
    "Pakistan": "PAK",
    "Australia": "AUS",
    "England": "ENG",
    "New Zealand": "NZ",
    "South Africa": "SA",
    "West Indies": "WI",
    "Sri Lanka": "SL",
    "Bangladesh": "BAN",
    "Afghanistan": "AFG",
    "Netherlands": "NED",
    "Scotland": "SCO",
    "Ireland": "IRE",
    "Zimbabwe": "ZIM",
    "UAE": "UAE",
    "Canada": "CAN",
    "USA": "USA"
}

# Load players from JSON
def load_players():
    try:
        with open('players.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

# Find player by name (flexible matching)
def find_player_team(player_name):
    """Find which team a player belongs to"""
    teams_data = load_players()
    player_name_lower = player_name.lower()

    # First try exact match
    for team_data in teams_data:
        for player in team_data['players']:
            if player['name'].lower() == player_name_lower:
                return team_data['team']

    # If no exact match, try partial match
    for team_data in teams_data:
        for player in team_data['players']:
            if player_name_lower in player['name'].lower():
                return team_data['team']
            # Try last name
            last_name = player['name'].split()[-1].lower()
            if player_name_lower == last_name:
                return team_data['team']

    return None

# Get player representative
def get_representative(player_name):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT user_id, username FROM player_representatives WHERE player_name = ?", 
              (player_name,))
    result = c.fetchone()
    conn.close()
    return result

# Get team flag URL for downloading
def get_team_flag_url(team_name):
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

# Emoji to number mapping
EMOJI_MAPPING = {
    'emoji_29': '0',
    'emoji_28': '1',
    'emoji_30': '2',
    'emoji_31': '3',
    'emoji_32': '4',
    'emoji_33': '5',
    'emoji_34': '6',
    'emoji_35': 'W',
    'PP1_emoji_30': '2LB',
    'PP2_emoji_31': '4LB',
    'PP3_emoji_32': '6LB',
    'PP4_emoji_33': '8LB'
}

# Store last processed timeline per channel
last_timelines = {}

# Store last processed wickets to prevent duplicates (username + timestamp)
last_wickets = {}

def parse_embed_fields(embed):
    """Parse the embed fields to extract match data - FIXED VERSION"""

    data = {}

    try:
        # Combine all field values into one text for easier searching
        full_text = ""
        for field in embed.fields:
            full_text += f"{field.name}: {field.value}\n"

        print(f"\n📄 FULL EMBED TEXT:\n{full_text}")

        # --- 1. CHECK INNINGS NUMBER ---
        innings_match = re.search(r'Innings:\s*\*\*(ONE|TWO)\*\*', full_text)
        innings = innings_match.group(1) if innings_match else "ONE"
        print(f"   📍 Innings: {innings}")

        # --- 2. EXTRACT ALL TEAM SCORES (can be any team names) ---
        # Pattern matches: "TEAM NAME: score (overs)" - supports any case
        team_pattern = r'([A-Za-z\s]+)\s*[^\:]*:\s*(\d+/\d+)\s*\((\d+\.\d+)\s*overs\)'
        all_teams = re.findall(team_pattern, full_text)

        if len(all_teams) < 2:
            print("   ⚠️ Less than 2 teams found!")
            return {}

        # Store both teams with their data
        team_info = {}
        for team_name, score, overs in all_teams:
            team_name_clean = team_name.strip()
            team_info[team_name_clean] = {
                'score': score,
                'overs': float(overs),
                'runs': int(score.split('/')[0])
            }
            print(f"   📊 {team_name_clean}: {score} ({overs} overs)")

        # Sort teams by overs completed
        teams_sorted = sorted(team_info.items(), key=lambda x: x[1]['overs'], reverse=True)

        # Determine which team is batting based on INNINGS
        if innings == "ONE":
            # Innings 1: The team with MORE overs is currently batting
            batting_team_name = teams_sorted[0][0]
            batting_team_info = teams_sorted[0][1]

            data['team_a_score'] = batting_team_info['score']
            data['overs'] = str(batting_team_info['overs'])
            print(f"   ✅ Innings 1: {batting_team_name} is batting: {batting_team_info['score']} ({batting_team_info['overs']})")

        elif innings == "TWO":
            # Innings 2: The team with MORE overs COMPLETED innings 1 (finished)
            # The team with FEWER overs is CURRENTLY BATTING in innings 2
            innings1_team_name = teams_sorted[0][0]  # More overs = finished batting
            innings1_team_info = teams_sorted[0][1]

            batting_team_name = teams_sorted[1][0]  # Fewer overs = currently batting
            batting_team_info = teams_sorted[1][1]

            data['team_a_score'] = batting_team_info['score']
            data['overs'] = str(batting_team_info['overs'])

            # Store team names for innings 2
            data['innings2_batting_team'] = batting_team_name
            data['innings2_opposition_team'] = innings1_team_name

            print(f"   ✅ Innings 2: {batting_team_name} is batting: {batting_team_info['score']} ({batting_team_info['overs']})")

            # Calculate target from innings 1 team (the one with MORE overs)
            target = innings1_team_info['runs'] + 1
            data['target'] = f"Target {target}"
            print(f"   🎯 TARGET: {target} ({innings1_team_name} made {innings1_team_info['runs']} in innings 1)")

        # --- 2. EXTRACT BATTERS ---
        batters_section = re.search(r'Batters:\s*(.+?)(?:Bowler:|Partnership:|$)', full_text, re.DOTALL)
        if batters_section:
            batters_text = batters_section.group(1)
            batter_lines = [line.strip() for line in batters_text.split('\n') if line.strip() and 'runs' in line.lower()]

            batter_count = 0

            for line in batter_lines:
                if 'no batsman' in line.lower(): continue

                clean_line = line.replace('*', '').strip()
                match = re.search(r'^(.+?):\s*(\d+)\s*\((\d+)\)\s*runs', clean_line)

                if match:
                    username = match.group(1).strip()
                    runs = match.group(2)
                    balls = match.group(3)
                    is_on_strike = '**' in line

                    batter_count += 1
                    prefix = f"batsman{batter_count}"

                    conn = sqlite3.connect('players.db')
                    c = conn.cursor()
                    c.execute("SELECT player_name FROM player_representatives WHERE username = ?", (username,))
                    result = c.fetchone()
                    conn.close()

                    full_name = result[0] if result else username
                    last_name = full_name.split()[-1] if result else username
                    team = find_player_team(full_name)

                    data[f'{prefix}_username'] = username
                    data[f'{prefix}_name'] = last_name
                    data[f'{prefix}_score'] = f"{runs}({balls})"
                    data[f'{prefix}_team'] = team if team else ""

                    if team and 'batting_team' not in data:
                        data['batting_team'] = team

                        # Check if this is innings 2
                        if 'innings2_batting_team' in data:
                            # Innings 2: Use batting team abbreviation, opposition team full name
                            data['team_a_name'] = TEAM_ABBREVIATIONS.get(team, team[:3].upper())
                        else:
                            # Innings 1: Normal logic
                            data['team_a_name'] = TEAM_ABBREVIATIONS.get(team, team[:3].upper())

                    if is_on_strike:
                        data['on_strike'] = batter_count

        # --- 3. EXTRACT BOWLER ---
        bowler_section = re.search(r'Bowler:\s*(.+?)(?:\n|$)', full_text)
        if bowler_section:
            bowler_line = bowler_section.group(1).strip()
            clean_line = bowler_line.replace('*', '').strip()
            match = re.search(r'^(.+?):\s*(\d+)\s*-\s*(\d+)\s*\((\d+(?:\.\d+)?)\s*overs?\)', clean_line)

            if match:
                username = match.group(1).strip()
                runs = match.group(2)
                wickets = match.group(3)
                overs = match.group(4)

                conn = sqlite3.connect('players.db')
                c = conn.cursor()
                c.execute("SELECT player_name FROM player_representatives WHERE username = ?", (username,))
                result = c.fetchone()
                conn.close()

                full_name = result[0] if result else username
                last_name = full_name.split()[-1] if result else username
                team = find_player_team(full_name)

                data['bowler_username'] = username
                data['bowler_name'] = last_name
                data['bowler_stats'] = f"{wickets}-{runs} ({overs})"
                data['bowler_team'] = team if team else ""

                if team:
                    # Always use bowler's actual team name
                    data['team_b_name'] = team

        # --- 4. EXTRACT TIMELINE ---
        timeline_match = re.search(r'Timeline:\s*(.+?)(?:\n|$)', full_text)
        if timeline_match:
            timeline_text = timeline_match.group(1)
            timeline = []
            for match in re.finditer(r':(?:(PP\d+)_)?emoji_(\d+):', timeline_text):
                prefix = match.group(1)  # PP1, PP2, etc. or None
                num = match.group(2)     # The number

                if prefix:
                    key = f'{prefix}_emoji_{num}'
                else:
                    key = f'emoji_{num}'

                timeline.append(EMOJI_MAPPING.get(key, '?'))

            data['timeline'] = timeline

        return data

    except Exception as e:
        print(f"❌ Error parsing embed fields: {e}")
        import traceback
        traceback.print_exc()
        return {}

def get_current_over_balls(timeline):
    """Extract only the balls from the current over (reset after every 6 balls)"""
    if not timeline:
        return []

    total_balls = len(timeline)
    current_over_position = total_balls % 6

    if current_over_position == 0:
        return timeline[-6:] if len(timeline) >= 6 else timeline

    return timeline[-current_over_position:]

def get_dynamic_font_size(text, max_width, base_size=45):
    """Calculate font size that fits text within max_width"""
    estimated_width = len(text) * (base_size * 0.6)

    if estimated_width <= max_width:
        return base_size

    scale_factor = max_width / estimated_width
    return int(base_size * scale_factor)

async def create_match_image(match_data, guild):
    """Create match status image by overlaying text on match.png"""

    try:
        img = Image.open("match.png").convert('RGBA')
        draw = ImageDraw.Draw(img)
        width, height = img.size

        print(f"🖼️ Image size: {width}x{height}")

        # Load fonts
        try:
            base_player_font_size = 90
            username_font = ImageFont.truetype("canva.otf", 1)
            score_font = ImageFont.truetype("nor.otf", 68)
            biggie_font = ImageFont.truetype("nor.otf", 115)
            vs_font = ImageFont.truetype("nor.otf", 35)
            small_font = ImageFont.truetype("nor.otf", 30)
            ball_font = ImageFont.truetype("nor.otf", 35)
            target_font = ImageFont.truetype("nor.otf", 40)
            usersmol_font = ImageFont.truetype("nor.otf", 40)
            bowlersmol_font = ImageFont.truetype("nor.otf", 50)
        except:
            username_font = ImageFont.load_default()
            score_font = ImageFont.load_default()
            vs_font = ImageFont.load_default()
            small_font = ImageFont.load_default()
            ball_font = ImageFont.load_default()
            target_font = ImageFont.load_default()

        RED = (255, 0, 0)
        PURPLE = (73, 0, 208)
        WHITE = (255, 255, 255)
        BLACK = (0, 0, 0)

        # Parse match data
        team_a_name = match_data.get('team_a_name', '')
        team_b_name = match_data.get('team_b_name', '')
        batting_team = match_data.get('batting_team', '')
        team_a_score = match_data.get('team_a_score', '0-0')
        overs = match_data.get('overs', '0.0')
        target = match_data.get('target', None)
        batsman1_name = match_data.get('batsman1_name', '')
        batsman1_username = match_data.get('batsman1_username', '')
        batsman1_score = match_data.get('batsman1_score', '0(0)')
        batsman1_team = match_data.get('batsman1_team', '')
        batsman2_name = match_data.get('batsman2_name', '')
        batsman2_username = match_data.get('batsman2_username', '')
        batsman2_score = match_data.get('batsman2_score', '0(0)')
        batsman2_team = match_data.get('batsman2_team', '')
        bowler_name = match_data.get('bowler_name', '')
        bowler_username = match_data.get('bowler_username', '')
        bowler_stats = match_data.get('bowler_stats', '0-0(0.0)')
        bowler_team = match_data.get('bowler_team', '')
        timeline = match_data.get('timeline', [])
        on_strike = match_data.get('on_strike', 1)

        print(f"📊 Match Data:")
        print(f"   Teams: {team_a_name} vs {team_b_name}")
        print(f"   Batting Team: {batting_team}")
        print(f"   Score: {team_a_score} ({overs} overs)")
        print(f"   Target: {target}")

        # CENTER - Team names and score
        center_x = width // 2
        center_y = 80

        # Draw team abbreviations
        if team_a_name:
            draw.text((center_x - 200, center_y + 80), team_a_name, fill=PURPLE, font=biggie_font, anchor="mm")

        if team_b_name:
            HOT_PINK =  (255, 0, 145)
            draw.text((center_x - 60, center_y + 200), f"VS {team_b_name}", fill=WHITE, font=vs_font, anchor="mm")

        # Draw main score
        draw.text((center_x + 95, center_y + 68), team_a_score, fill=WHITE, font=score_font, anchor="mm")

        # Draw overs
        draw.text((center_x + 150, center_y + 200), f"{overs} OV", fill=PURPLE, font=usersmol_font, anchor="mm")

        # Draw target if exists (in center, below score) in BLUE
        if target:
            draw.text((center_x + 40, center_y - 40), target, fill=WHITE, font=usersmol_font, anchor="mm")
            print(f"   🎯 Drew target: {target}")

        # LEFT SIDE - Batsmen
        left_x = 150
        batsman1_y = 160
        batsman2_y = 220
        flag_size = 180  # INCREASED from 100

        # Load red triangle for on-strike indicator
        try:
            triangle = Image.open("redt.png").convert('RGBA')
            triangle = triangle.resize((100, 50), Image.Resampling.LANCZOS)
        except Exception as e:
            print(f"⚠️ Warning loading triangle: {e}")
            triangle = None

        # Draw batting team flag (bigger)
        if batting_team:
            flag_url = get_team_flag_url(batting_team)
            if flag_url:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(flag_url) as resp:
                            if resp.status == 200:
                                flag_data = await resp.read()
                                flag_img = Image.open(io.BytesIO(flag_data)).convert('RGBA')
                                flag_img = flag_img.resize((flag_size, flag_size), Image.Resampling.LANCZOS)
                                flag_y = (batsman1_y + batsman2_y) // 2 - 20
                                img.paste(flag_img, (left_x - 130, flag_y - 100), flag_img)
                                print(f"   ✅ Drew batting team flag for {batting_team}")
                except Exception as e:
                    print(f"   ⚠️ Error loading batting flag: {e}")

        max_name_width = 180

        # Draw batsman 1
        if batsman1_name and batsman1_username:
            print(f"🎨 Drawing Batsman 1: {batsman1_name} (@{batsman1_username})")

            if triangle and on_strike == 1:
                img.paste(triangle, (left_x + 65, batsman1_y - 80), triangle)

            font_size = get_dynamic_font_size(batsman1_name.upper(), max_name_width, base_player_font_size)
            try:
                player_font = ImageFont.truetype("nor.otf", font_size)
            except:
                player_font = ImageFont.load_default()

            draw.text((left_x + 150, batsman1_y - 50), batsman1_name.upper(), fill=PURPLE, font=player_font, anchor="lm")
            draw.text((left_x + 350, batsman1_y - 50), batsman1_score, fill=PURPLE, font=usersmol_font, anchor="lm")
            draw.text((left_x + 150, batsman1_y - 15), f"@{batsman1_username}", fill=BLACK, font=username_font, anchor="lm")

        # Draw batsman 2
        if batsman2_name and batsman2_username:
            print(f"🎨 Drawing Batsman 2: {batsman2_name} (@{batsman2_username})")

            if triangle and on_strike == 2:
                img.paste(triangle, (left_x + 65, batsman2_y - 7), triangle)

            font_size = get_dynamic_font_size(batsman2_name.upper(), max_name_width, base_player_font_size)
            try:
                player_font = ImageFont.truetype("nor.otf", font_size)
            except:
                player_font = ImageFont.load_default()

            draw.text((left_x + 150, batsman2_y + 20), batsman2_name.upper(), fill=PURPLE, font=player_font, anchor="lm")
            draw.text((left_x + 350, batsman2_y + 20), batsman2_score, fill=PURPLE, font=usersmol_font, anchor="lm")
            draw.text((left_x + 150, batsman2_y + 50), f"@{batsman2_username}", fill=BLACK, font=username_font, anchor="lm")

        # RIGHT SIDE - Bowler
        right_x = width - 150
        bowler_y = 155  # MOVED UP from 190
        bowler_flag_size = 180  # BIGGER flag for bowler

        if bowler_name and bowler_username:
            print(f"🎨 Drawing Bowler: {bowler_name} (@{bowler_username})")

            # Draw bigger flag positioned higher
            if bowler_team:
                flag_url = get_team_flag_url(bowler_team)
                if flag_url:
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(flag_url) as resp:
                                if resp.status == 200:
                                    flag_data = await resp.read()
                                    flag_img = Image.open(io.BytesIO(flag_data)).convert('RGBA')
                                    flag_img = flag_img.resize((bowler_flag_size, bowler_flag_size), Image.Resampling.LANCZOS)
                                    img.paste(flag_img, (right_x - 50, bowler_y - 100), flag_img)
                                    print(f"   ✅ Drew flag for {bowler_team}")
                    except Exception as e:
                        print(f"   ⚠️ Error loading flag: {e}")

            draw.text((right_x - 140, bowler_y - 90), f"@{bowler_username}", fill=BLACK, font=username_font, anchor="rm")

            # Fixed font size for bowler name and stats (no dynamic sizing)
            try:
                bowler_fixed_font = ImageFont.truetype("nor.otf", 90)  # Fixed size
            except:
                bowler_fixed_font = ImageFont.load_default()

            draw.text((right_x - 100, bowler_y - 30), bowler_name.upper(), fill=PURPLE, font=bowlersmol_font, anchor="rm")
            draw.text((right_x - 130, bowler_y + 30), bowler_stats, fill=PURPLE, font=bowlersmol_font, anchor="rm")

        # BOTTOM RIGHT - Timeline circles
        circle_start_x = width - 420
        circle_y = height - 38
        circle_spacing = 70
        circle_radius = 28

        current_over_balls = get_current_over_balls(timeline)

        for i, ball in enumerate(current_over_balls):
            x = circle_start_x + (i * circle_spacing)

            # Determine fill color based on ball type
            if ball == 'W':
                fill_color = (217, 17, 17)
            elif ball == '0':
                fill_color = (100, 100, 100)
            elif ball == '6':
                fill_color = (191, 7, 232)
            elif ball == '4':
                fill_color = (41, 232, 7)
            elif 'LB' in ball:  # Leg byes
                fill_color = (255, 165, 0)  # Orange color for leg byes
            else:
                fill_color = (27, 22, 107)

            draw.ellipse([(x - circle_radius, circle_y - circle_radius), 
                         (x + circle_radius, circle_y + circle_radius)], 
                        fill=fill_color, outline=(255, 255, 255), width=4)

            # Use smaller font for LB text to fit in circle
            if 'LB' in ball:
                lb_font = ImageFont.truetype("nor.otf", 24)  # Smaller font for LB
                draw.text((x, circle_y), ball, fill=(255, 255, 255), font=lb_font, anchor="mm")
            else:
                draw.text((x, circle_y), ball, fill=(255, 255, 255), font=ball_font, anchor="mm")

        # Convert to bytes
        output = io.BytesIO()
        img.save(output, format='PNG')
        output.seek(0)

        return output

    except Exception as e:
        print(f"❌ Error creating match image: {e}")
        import traceback
        traceback.print_exc()
        return None

async def create_wicket_image(wicket_data, guild):
    """Create wicket OUT image"""
    try:
        img = Image.open("out.png").convert('RGBA')
        draw = ImageDraw.Draw(img)
        width, height = img.size

        print(f"🖼️ OUT Image size: {width}x{height}")

        # Load fonts
        try:
            player_name_font = ImageFont.truetype("nor.otf", 90)
            username_font = ImageFont.truetype("nor.otf", 40)
            score_font = ImageFont.truetype("nor.otf", 120)
            balls_font = ImageFont.truetype("nor.otf", 60)
            dismissal_font = ImageFont.truetype("nor.otf", 70)
        except:
            player_name_font = ImageFont.load_default()
            username_font = ImageFont.load_default()
            score_font = ImageFont.load_default()
            balls_font = ImageFont.load_default()
            dismissal_font = ImageFont.load_default()

        WHITE = (255, 255, 255)
        YELLOW = (255, 207, 0)  # #ffcf00

        # Get data
        out_player_name = wicket_data.get('out_player_name', 'UNKNOWN')
        out_username = wicket_data.get('out_username', 'unknown')
        runs = wicket_data.get('runs', '0')
        balls = wicket_data.get('balls', '0')
        dismissal_text = wicket_data.get('dismissal_text', '')
        dismissal_usernames = wicket_data.get('dismissal_usernames', '')
        team_name = wicket_data.get('team', '')

        # Check if it's a caught dismissal (has both caught and bowled)
        is_caught = 'c ' in dismissal_text and ' b ' in dismissal_text

        # CENTER-LEFT: Player name and username
        center_x = width // 2
        player_y = height // 2 - 80

        # Draw player name (WHITE, centered)
        name_size = 90
        if len(out_player_name) > 15:
            name_size = 65  # Shrink if more than 15 characters
        
        try:
            player_name_font = ImageFont.truetype("nor.otf", name_size)
        except:
            player_name_font = ImageFont.load_default()

        draw.text((center_x - 90, player_y - 20), out_player_name, fill=WHITE, font=player_name_font, anchor="mm")

        # Draw username below (WHITE, centered)
        draw.text((center_x - 90, player_y + 40), f"@{out_username}", fill=WHITE, font=username_font, anchor="mm")

        # RIGHT SIDE: Score
        score_x = center_x + 300
        score_y = player_y

        # Draw runs (YELLOW)
        draw.text((score_x, score_y), runs, fill=YELLOW, font=score_font, anchor="lm")

        # Draw balls (WHITE, smaller, right next to runs)
        bbox = draw.textbbox((score_x, score_y), runs, font=score_font)
        runs_width = bbox[2] - bbox[0]
        draw.text((score_x + runs_width + 20, score_y + 20), balls, fill=WHITE, font=balls_font, anchor="lm")

        # BOTTOM CENTER: Dismissal info
        dismissal_y = height - 110

        # Draw dismissal text (YELLOW)
        if is_caught:
            # Split dismissal text for caught dismissal: "c CATCHER b BOWLER"
            parts = dismissal_text.split(' b ')  # ['c CATCHER', 'BOWLER']

            # Draw "c CATCHER" on the left
            draw.text((center_x - 200, dismissal_y), parts[0], fill=YELLOW, font=dismissal_font, anchor="mm")

            # Draw "b BOWLER" WAY MORE to the right
            draw.text((center_x + 350, dismissal_y), f"b {parts[1]}", fill=YELLOW, font=dismissal_font, anchor="mm")
        else:
            # Single dismissal text (bowled only) - centered
            draw.text((center_x, dismissal_y), dismissal_text, fill=YELLOW, font=dismissal_font, anchor="mm")

        # Draw usernames below dismissal text (WHITE)
        if dismissal_usernames:
            if is_caught:
                # Split usernames for caught dismissal
                usernames = dismissal_usernames.split()  # ['@catcher', '@bowler']

                # Draw catcher username on the left (below "c CATCHER")
                draw.text((center_x - 200, dismissal_y + 60), usernames[0], fill=WHITE, font=username_font, anchor="mm")

                # Draw bowler username WAY MORE to the right (below "b BOWLER")
                draw.text((center_x + 350, dismissal_y + 60), usernames[1], fill=WHITE, font=username_font, anchor="mm")
            else:
                # Single username (bowled only) - centered
                draw.text((center_x, dismissal_y + 60), dismissal_usernames, fill=WHITE, font=username_font, anchor="mm")

        # MIDDLE RIGHT: Team flag
        if team_name:
            flag_url = get_team_flag_url(team_name)
            flag_size = 180

            if team_name.lower() == "west indies":
                try:
                    flag_img = Image.open("westindies.jpg").convert('RGBA')
                    flag_img = flag_img.resize((flag_size, flag_size), Image.Resampling.LANCZOS)

                    mask = Image.new('L', (flag_size, flag_size), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.ellipse((0, 0, flag_size, flag_size), fill=255)

                    circular_flag = Image.new('RGBA', (flag_size, flag_size), (0, 0, 0, 0))
                    circular_flag.paste(flag_img, (0, 0), mask)

                    flag_x = width - flag_size - 50
                    flag_y = (height // 2) - (flag_size // 2)
                    img.paste(circular_flag, (flag_x, flag_y), circular_flag)
                except Exception as e:
                    print(f"❌ Error loading West Indies flag: {e}")
            elif flag_url:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(flag_url) as resp:
                            if resp.status == 200:
                                flag_data = await resp.read()
                                flag_img = Image.open(io.BytesIO(flag_data)).convert('RGBA')
                                flag_img = flag_img.resize((flag_size, flag_size), Image.Resampling.LANCZOS)

                                mask = Image.new('L', (flag_size, flag_size), 0)
                                mask_draw = ImageDraw.Draw(mask)
                                mask_draw.ellipse((0, 0, flag_size, flag_size), fill=255)

                                circular_flag = Image.new('RGBA', (flag_size, flag_size), (0, 0, 0, 0))
                                circular_flag.paste(flag_img, (0, 0), mask)

                                flag_x = width - flag_size - 50
                                flag_y = (height // 2) - (flag_size // 2)
                                img.paste(circular_flag, (flag_x, flag_y), circular_flag)
                except Exception as e:
                    print(f"❌ Error loading flag: {e}")

        # Convert to bytes
        output = io.BytesIO()
        img.save(output, format='PNG')
        output.seek(0)

        return output

    except Exception as e:
        print(f"❌ Error creating wicket image: {e}")
        import traceback
        traceback.print_exc()
        return None

def parse_wicket_from_embed(embed):
    """Parse wicket information from embed fields - searches ALL fields"""
    try:
        print("\n🔍 SEARCHING EMBED FOR WICKET DATA...")

        # Combine ALL embed content
        full_text = ""

        # Add embed description if exists
        if embed.description:
            full_text += f"{embed.description}\n"
            print(f"   Description: {embed.description[:100]}...")

        # Add ALL field names and values
        for field in embed.fields:
            full_text += f"{field.name}: {field.value}\n"

        print(f"\n📄 FULL EMBED CONTENT:\n{full_text}\n")

        # Look for wicket indicators
        wicket_indicators = [
            "is out!",
            "is DUCK out!",
            "OUT!",
            "WICKET",
            "dismissed"
        ]

        is_wicket = any(indicator.lower() in full_text.lower() for indicator in wicket_indicators)

        if not is_wicket:
            print("   ❌ No wicket indicators found")
            return None

        print("   ✅ WICKET DETECTED IN EMBED!")

        # Extract username from patterns like "**username is out!**" or "username is DUCK out!"
        username_match = re.search(r'\*\*(.+?)\s+is(?:\s+DUCK)?\s+out', full_text)
        if not username_match:
            username_match = re.search(r'(.+?)\s+is(?:\s+DUCK)?\s+out', full_text)

        if not username_match:
            print("   ❌ Could not extract username")
            return None

        out_username = username_match.group(1).strip()
        print(f"   📍 Out player: {out_username}")

        # Check if it's a duck
        is_duck = "DUCK out" in full_text
        print(f"   🦆 Duck: {is_duck}")

        # Extract runs and balls - look for pattern like "53 (23)" or "`53 (23)`"
        stats_match = re.search(rf'{re.escape(out_username)}[^\d]*?(\d+)\s*\((\d+)\)', full_text)
        if not stats_match:
            # Try with backticks
            stats_match = re.search(r'`(\d+)\s*\((\d+)\)`', full_text)

        if not stats_match:
            print("   ❌ Could not extract runs/balls")
            return None

        runs = stats_match.group(1)
        balls = stats_match.group(2)
        print(f"   📊 Score: {runs}({balls})")

        # Extract caught by user ID (if exists)
        caught_by_user_id = None
        caught_match = re.search(r'Caught by.*?<@(\d+)>', full_text)
        if caught_match:
            caught_by_user_id = int(caught_match.group(1))
            print(f"   🤚 Caught by user ID: {caught_by_user_id}")

        # Find bowler - look for a DIFFERENT username with stats pattern
        bowler_username = None
        # Pattern: username: stats with dash and overs
        for line in full_text.split('\n'):
            if '╰' in line and '-' in line and '(' in line:
                bowler_match = re.search(r'(.+?):\s*╰', line)
                if bowler_match:
                    potential_bowler = bowler_match.group(1).strip()
                    if potential_bowler != out_username:
                        bowler_username = potential_bowler
                        print(f"   🎳 Bowler: {bowler_username}")
                        break

        return {
            'out_username': out_username,
            'runs': runs,
            'balls': balls,
            'bowler_username': bowler_username,
            'caught_by_user_id': caught_by_user_id,
            'is_duck': is_duck
        }

    except Exception as e:
        print(f"❌ Error parsing wicket from embed: {e}")
        import traceback
        traceback.print_exc()
        return None

def parse_wicket_message(message_content):
    """Parse wicket message to extract data"""
    try:
        lines = message_content.strip().split('\n')

        # Extract username from first line (e.g., "**s4nsk4r_50hartz is out!**")
        first_line = lines[0]

        # Check for duck
        is_duck = "DUCK out" in first_line

        # Extract username
        username_match = re.search(r'\*\*(.+?)\s+is', first_line)
        if not username_match:
            return None

        out_username = username_match.group(1)

        # Find the line with player stats (e.g., "s4nsk4r_50hartz: ╰ *`53 (23)`**")
        player_line = None
        bowler_line = None
        caught_by_user_id = None

        for line in lines:
            if out_username in line and '╰' in line:
                player_line = line
            elif 'Caught by' in line:
                # Extract user ID from mention
                caught_match = re.search(r'<@(\d+)>', line)
                if caught_match:
                    caught_by_user_id = int(caught_match.group(1))
            # Look for bowler line (has different username)
            elif '╰' in line and '`' in line and '-' in line and out_username not in line:
                bowler_line = line

        if not player_line:
            return None

        # Extract runs and balls from player line
        stats_match = re.search(r'`(\d+)\s+\((\d+)\)', player_line)
        if not stats_match:
            return None

        runs = stats_match.group(1)
        balls = stats_match.group(2)

        # Extract bowler username
        bowler_username = None
        if bowler_line:
            bowler_match = re.search(r'(.+?):', bowler_line)
            if bowler_match:
                bowler_username = bowler_match.group(1).strip()

        return {
            'out_username': out_username,
            'runs': runs,
            'balls': balls,
            'bowler_username': bowler_username,
            'caught_by_user_id': caught_by_user_id,
            'is_duck': is_duck
        }

    except Exception as e:
        print(f"❌ Error parsing wicket message: {e}")
        return None

class MatchUpdates(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.id != CRICKET_BOT_ID:
            return

        print(f"\n{'='*60}")
        print(f"✅ MESSAGE FROM CRICKET BOT!")
        print(f"{'='*60}")

        # FIRST: Check if there's an embed with wicket info OR match data
        wicket_info = None
        if message.embeds:
            wicket_info = parse_wicket_from_embed(message.embeds[0])

        # SECOND: If no wicket in embed, check plain text for wicket
        if not wicket_info and message.content:
            if "is out!" in message.content or "is DUCK out!" in message.content:
                print("🎯 WICKET MESSAGE DETECTED IN PLAIN TEXT!")
                wicket_info = parse_wicket_message(message.content)

        # Process wicket if found (from either embed or plain text)
        if wicket_info:
            print("🎯 PROCESSING WICKET!")

            # Check if we already processed this exact wicket recently (prevent duplicates)
            channel_id = message.channel.id
            wicket_key = f"{channel_id}_{wicket_info['out_username']}_{wicket_info['runs']}_{wicket_info['balls']}"

            import time
            current_time = time.time()

            # If we processed this exact wicket in the last 10 seconds, skip it
            if wicket_key in last_wickets:
                time_diff = current_time - last_wickets[wicket_key]
                if time_diff < 10:
                    print(f"⏭️ SKIPPING DUPLICATE WICKET (processed {time_diff:.1f}s ago)")
                    return

            # Mark this wicket as processed
            last_wickets[wicket_key] = current_time

            # Clean up old wicket entries (older than 1 minute)
            old_keys = [k for k, v in last_wickets.items() if current_time - v > 60]
            for k in old_keys:
                del last_wickets[k]

            # Get real player names from database
            conn = sqlite3.connect('players.db')
            c = conn.cursor()

            # Get out player's real name
            c.execute("SELECT player_name FROM player_representatives WHERE username = ?", 
                      (wicket_info['out_username'],))
            out_result = c.fetchone()

            if not out_result:
                print(f"❌ Player not found for {wicket_info['out_username']}")
                conn.close()
                return

            out_player_full_name = out_result[0]
            out_player_display_name = out_player_full_name.upper()  # FULL NAME for out player

            # Get out player's team
            out_player_team = find_player_team(out_player_full_name)

            # Get bowler's real name (FULL NAME)
            bowler_real_name = None
            if wicket_info['bowler_username']:
                c.execute("SELECT player_name FROM player_representatives WHERE username = ?", 
                          (wicket_info['bowler_username'],))
                bowler_result = c.fetchone()
                if bowler_result:
                    bowler_full_name = bowler_result[0]
                    bowler_real_name = bowler_full_name.upper()  # FULL NAME for bowler

            # Get caught by player's real name (FIRST NAME ONLY)
            caught_by_real_name = None
            if wicket_info['caught_by_user_id']:
                c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", 
                          (wicket_info['caught_by_user_id'],))
                caught_result = c.fetchone()
                if caught_result:
                    caught_full_name = caught_result[0]
                    caught_by_real_name = caught_full_name.split()[0].upper()  # FIRST NAME ONLY for caught

            conn.close()

            # Build dismissal text
            if caught_by_real_name and bowler_real_name:
                dismissal_text = f"c {caught_by_real_name} b {bowler_real_name}"
                caught_by_member = message.guild.get_member(wicket_info['caught_by_user_id'])
                caught_by_username = caught_by_member.name if caught_by_member else 'unknown'
                dismissal_usernames = f"@{caught_by_username} @{wicket_info['bowler_username']}"
            elif bowler_real_name:
                dismissal_text = f"b {bowler_real_name}"
                dismissal_usernames = f"@{wicket_info['bowler_username']}"
            else:
                dismissal_text = "OUT"
                dismissal_usernames = ""

            # Create wicket data
            wicket_data = {
                'out_player_name': out_player_display_name,  # FULL NAME
                'out_username': wicket_info['out_username'],
                'runs': wicket_info['runs'],
                'balls': wicket_info['balls'],
                'dismissal_text': dismissal_text,
                'dismissal_usernames': dismissal_usernames,
                'team': out_player_team
            }

            print(f"🎨 CREATING WICKET IMAGE...")

            # Create wicket image
            wicket_image = await create_wicket_image(wicket_data, message.guild)

            if not wicket_image:
                print("❌ Failed to create wicket image")
                return

            # Send as plain file
            file = discord.File(fp=wicket_image, filename="wicket.png")
            await message.channel.send(file=file)
            print(f"✅ SENT WICKET IMAGE\n")
            return

        # THIRD: Check for match status updates in embeds (not wickets)
        if not message.embeds:
            print("❌ No embeds found")
            return

        embed = message.embeds[0]

        if not embed.fields:
            print("❌ No embed fields")
            return

        print(f"✅ Embed has {len(embed.fields)} fields\n")

        # Parse the embed fields
        match_data = parse_embed_fields(embed)

        if not match_data:
            print("❌ No match data found")
            return

        if 'timeline' not in match_data or not match_data['timeline']:
            print("❌ No timeline found")
            return

        # Check if this is a new timeline
        channel_id = message.channel.id
        current_timeline = '|'.join(match_data['timeline'])

        if channel_id in last_timelines and last_timelines[channel_id] == current_timeline:
            print("ℹ️ Same timeline, skipping")
            return

        # Update last timeline
        last_timelines[channel_id] = current_timeline

        print(f"\n🎨 CREATING MATCH IMAGE...")

        # Create match image
        match_image = await create_match_image(match_data, message.guild)

        if not match_image:
            print("❌ Failed to create match image")
            return

        # Send as plain file (NO EMBED)
        file = discord.File(fp=match_image, filename="match_status.png")
        await message.channel.send(file=file)
        print(f"✅ SENT MATCH UPDATE IMAGE\n")

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if after.author.id != CRICKET_BOT_ID:
            return

        print("📝 Cricket bot edited a message")
        await self.on_message(after)

    @commands.command(name='test')
    async def test_match_image(self, ctx, batsman1: discord.Member = None, batsman2: discord.Member = None, bowler: discord.Member = None):
        """Test command: -test @user1 @user2 @user3"""

        if not batsman1 or not batsman2 or not bowler:
            await ctx.send("❌ Usage: `-test @batsman1 @batsman2 @bowler`")
            return

        print(f"\n🧪 TEST COMMAND TRIGGERED")
        print(f"   Batsman 1: {batsman1.name}")
        print(f"   Batsman 2: {batsman2.name}")
        print(f"   Bowler: {bowler.name}")

        # Generate random scores
        batsman1_runs = random.randint(0, 50)
        batsman1_balls = random.randint(batsman1_runs, batsman1_runs + 20)

        batsman2_runs = random.randint(0, 50)
        batsman2_balls = random.randint(batsman2_runs, batsman2_runs + 20)

        total_runs = batsman1_runs + batsman2_runs 
        wickets = 1
        overs_bowled = round(random.uniform(0.1, 5.0), 1)

        bowler_wickets = random.randint(0, 2)
        bowler_runs = random.randint(0, 30)
        bowler_overs = round(random.uniform(0.1, overs_bowled), 1)

        # Random on-strike
        on_strike = random.randint(1, 2)

        # Random timeline (last 6 balls)
        possible_balls = ['0', '1', '2', '3', '4', '6', 'W']
        timeline = [random.choice(possible_balls) for _ in range(6)]

        # ALWAYS innings 2 with target
        target_score = random.randint(total_runs + 10, total_runs + 80)
        target = f"Target {target_score}"

        # Try to get player names from database
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Get batsman 1 details
        c.execute("SELECT player_name FROM player_representatives WHERE username = ?", (batsman1.name,))
        result = c.fetchone()
        batsman1_full_name = result[0] if result else batsman1.name
        batsman1_last_name = batsman1_full_name.split()[-1] if result else batsman1.name
        batsman1_team = find_player_team(batsman1_full_name) if result else ""

        # Get batsman 2 details
        c.execute("SELECT player_name FROM player_representatives WHERE username = ?", (batsman2.name,))
        result = c.fetchone()
        batsman2_full_name = result[0] if result else batsman2.name
        batsman2_last_name = batsman2_full_name.split()[-1] if result else batsman2.name
        batsman2_team = find_player_team(batsman2_full_name) if result else ""

        # Get bowler details
        c.execute("SELECT player_name FROM player_representatives WHERE username = ?", (bowler.name,))
        result = c.fetchone()
        bowler_full_name = result[0] if result else bowler.name
        bowler_last_name = bowler_full_name.split()[-1] if result else bowler.name
        bowler_team = find_player_team(bowler_full_name) if result else ""

        conn.close()

        # Create match data
        match_data = {
            'team_a_name': TEAM_ABBREVIATIONS.get(batsman1_team, batsman1_team[:3].upper()) if batsman1_team else 'BAT',
            'team_b_name': bowler_team if bowler_team else 'BOW',  # Full team name for VS
            'batting_team': batsman1_team,  # Add batting team for flag
            'team_a_score': f'{total_runs}/{wickets}',
            'overs': str(overs_bowled),
            'batsman1_name': batsman1_last_name,
            'batsman1_username': batsman1.name,
            'batsman1_score': f'{batsman1_runs}({batsman1_balls})',
            'batsman1_team': batsman1_team,
            'batsman2_name': batsman2_last_name,
            'batsman2_username': batsman2.name,
            'batsman2_score': f'{batsman2_runs}({batsman2_balls})',
            'batsman2_team': batsman2_team,
            'bowler_name': bowler_last_name,
            'bowler_username': bowler.name,
            'bowler_stats': f'{bowler_wickets}-{bowler_runs} ({bowler_overs})',
            'bowler_team': bowler_team,
            'timeline': timeline,
            'on_strike': on_strike,
            'target': target
        }

        print(f"📊 Generated Test Data:")
        print(f"   Innings: TWO (Chasing)")
        print(f"   Batting Team: {batsman1_team}")
        print(f"   Bowling Team: {bowler_team}")
        print(f"   Score: {match_data['team_a_score']} ({match_data['overs']} overs)")
        print(f"   Target: {target}")
        print(f"   Batsman 1: {match_data['batsman1_score']} {'*' if on_strike == 1 else ''}")
        print(f"   Batsman 2: {match_data['batsman2_score']} {'*' if on_strike == 2 else ''}")
        print(f"   Bowler: {match_data['bowler_stats']}")
        print(f"   Timeline: {timeline}")

        # Create match image
        match_image = await create_match_image(match_data, ctx.guild)

        if not match_image:
            await ctx.send("❌ Failed to create test image")
            return

        # Send image
        file = discord.File(fp=match_image, filename="test_match.png")
        await ctx.send(f"🧪 **Test Match Image Generated** - 🎯 Innings 2 (Chasing)", file=file)
        print(f"✅ Test image sent!\n")

    @commands.command(name='testwicket', aliases=['tw'])
    async def test_wicket_image(self, ctx, out_player: discord.Member = None, bowler: discord.Member = None, caught_by: discord.Member = None):
        """Test wicket command: -testwicket @out_player @bowler [@caught_by]"""

        if not out_player or not bowler:
            await ctx.send("❌ Usage: `-testwicket @out_player @bowler [@caught_by]`")
            return

        print(f"\n🧪 TEST WICKET COMMAND TRIGGERED")
        print(f"   Out Player: {out_player.name}")
        print(f"   Bowler: {bowler.name}")
        print(f"   Caught By: {caught_by.name if caught_by else 'None'}")

        # Get player details from database
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Get out player details (FULL NAME)
        c.execute("SELECT player_name FROM player_representatives WHERE username = ?", (out_player.name,))
        result = c.fetchone()
        out_player_full_name = result[0] if result else out_player.name
        out_player_display_name = out_player_full_name.upper()  # FULL NAME
        out_player_team = find_player_team(out_player_full_name) if result else ""

        # Get bowler details (FULL NAME)
        c.execute("SELECT player_name FROM player_representatives WHERE username = ?", (bowler.name,))
        result = c.fetchone()
        bowler_full_name = result[0] if result else bowler.name
        bowler_real_name = bowler_full_name.upper()  # FULL NAME

        # Get caught by details (FIRST NAME ONLY)
        caught_by_real_name = None
        if caught_by:
            c.execute("SELECT player_name FROM player_representatives WHERE username = ?", (caught_by.name,))
            result = c.fetchone()
            if result:
                caught_by_full_name = result[0]
                caught_by_real_name = caught_by_full_name.split()[0].upper()  # FIRST NAME ONLY

        conn.close()

        # Generate random score
        runs = str(random.randint(0, 100))
        balls = str(random.randint(int(runs), int(runs) + 50))

        # Build dismissal text
        if caught_by_real_name and bowler_real_name:
            dismissal_text = f"c {caught_by_real_name} b {bowler_real_name}"
            dismissal_usernames = f"@{caught_by.name} @{bowler.name}"
        elif bowler_real_name:
            dismissal_text = f"b {bowler_real_name}"
            dismissal_usernames = f"@{bowler.name}"
        else:
            dismissal_text = "OUT"
            dismissal_usernames = ""

        # Create wicket data
        wicket_data = {
            'out_player_name': out_player_display_name,  # FULL NAME
            'out_username': out_player.name,
            'runs': runs,
            'balls': balls,
            'dismissal_text': dismissal_text,
            'dismissal_usernames': dismissal_usernames,
            'team': out_player_team
        }

        print(f"📊 Generated Test Wicket Data:")
        print(f"   Out Player: {out_player_display_name} ({out_player.name})")
        print(f"   Score: {runs}({balls})")
        print(f"   Dismissal: {dismissal_text}")
        print(f"   Team: {out_player_team}")

        # Create wicket image
        wicket_image = await create_wicket_image(wicket_data, ctx.guild)

        if not wicket_image:
            await ctx.send("❌ Failed to create test wicket image")
            return

        # Send image
        file = discord.File(fp=wicket_image, filename="test_wicket.png")
        await ctx.send(f"🧪 **Test Wicket Image Generated**", file=file)
        print(f"✅ Test wicket image sent!\n")

async def setup(bot):
    await bot.add_cog(MatchUpdates(bot))