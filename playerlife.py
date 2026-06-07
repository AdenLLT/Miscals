import discord
import sqlite3
import json
import random
import asyncio
import math
import urllib.request
import urllib.error
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Select
from datetime import datetime, timedelta

# ============================================================
# GEMINI AI CONFIG
# ============================================================
GEMINI_API_KEY = "AIzaSyCqTGO6jFDIkzp1ofUqRYXc9sVKpVCJ0es"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
POSTS_PER_PAGE = 4

# ============================================================
# DATABASE INIT
# ============================================================

def init_playerlife_db():
    conn = sqlite3.connect('players.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS player_life
                 (user_id INTEGER PRIMARY KEY,
                  cash INTEGER DEFAULT 50000,
                  bank INTEGER DEFAULT 0,
                  reputation INTEGER DEFAULT 50,
                  confidence INTEGER DEFAULT 50,
                  fitness INTEGER DEFAULT 100,
                  energy INTEGER DEFAULT 100,
                  happiness INTEGER DEFAULT 50,
                  fans INTEGER DEFAULT 1000,
                  fan_loyalty INTEGER DEFAULT 50,
                  marital_status TEXT DEFAULT 'Single',
                  partner_name TEXT DEFAULT NULL,
                  house_level INTEGER DEFAULT 0,
                  car_id TEXT DEFAULT NULL,
                  sponsor_tier INTEGER DEFAULT 0,
                  sponsor_name TEXT DEFAULT NULL,
                  contract_value INTEGER DEFAULT 0,
                  last_train TIMESTAMP DEFAULT NULL,
                  last_rest TIMESTAMP DEFAULT NULL,
                  last_press TIMESTAMP DEFAULT NULL,
                  last_scandal TIMESTAMP DEFAULT NULL,
                  last_social TIMESTAMP DEFAULT NULL,
                  last_rehab TIMESTAMP DEFAULT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS player_rivals
                 (user_id INTEGER,
                  rival_id INTEGER,
                  declared_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY (user_id, rival_id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS player_cars
                 (user_id INTEGER,
                  car_name TEXT,
                  car_value INTEGER,
                  purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS player_properties
                 (user_id INTEGER,
                  property_name TEXT,
                  property_value INTEGER,
                  purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS social_media_accounts
                 (user_id INTEGER PRIMARY KEY,
                  platform TEXT DEFAULT 'CricketGram',
                  followers INTEGER DEFAULT 500,
                  posts INTEGER DEFAULT 0,
                  viral_posts INTEGER DEFAULT 0,
                  total_likes INTEGER DEFAULT 0,
                  verification_status INTEGER DEFAULT 0,
                  bio TEXT DEFAULT NULL,
                  last_post TIMESTAMP DEFAULT NULL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS social_posts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  post_type TEXT,
                  content TEXT,
                  likes INTEGER DEFAULT 0,
                  comments INTEGER DEFAULT 0,
                  went_viral INTEGER DEFAULT 0,
                  posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS locker_room
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  target_id INTEGER,
                  message TEXT,
                  sentiment TEXT,
                  sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS trash_talk_log
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  sender_id INTEGER,
                  target_id INTEGER,
                  message TEXT,
                  confidence_damage INTEGER,
                  sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS player_trophies
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  trophy_name TEXT,
                  awarded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS ai_feed_cache
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  cache_date TEXT,
                  language_filter TEXT DEFAULT 'all',
                  page_number INTEGER DEFAULT 0,
                  posts_json TEXT,
                  generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    conn.commit()
    conn.close()

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_life(user_id):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT * FROM player_life WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        cols = ["user_id","cash","bank","reputation","confidence","fitness","energy","happiness",
                "fans","fan_loyalty","marital_status","partner_name","house_level","car_id",
                "sponsor_tier","sponsor_name","contract_value","last_train","last_rest",
                "last_press","last_scandal","last_social","last_rehab","created_at"]
        return dict(zip(cols, row))
    return None

def ensure_life(user_id):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO player_life (user_id) VALUES (?)", (user_id,))
    c.execute("INSERT OR IGNORE INTO social_media_accounts (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def update_life(user_id, **kwargs):
    if not kwargs:
        return
    fields = ", ".join([f"{k} = ?" for k in kwargs])
    values = list(kwargs.values()) + [user_id]
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(f"UPDATE player_life SET {fields} WHERE user_id = ?", values)
    conn.commit()
    conn.close()

def get_social(user_id):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT * FROM social_media_accounts WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        cols = ["user_id","platform","followers","posts","viral_posts","total_likes","verification_status","bio","last_post"]
        return dict(zip(cols, row))
    return None

def update_social(user_id, **kwargs):
    if not kwargs:
        return
    fields = ", ".join([f"{k} = ?" for k in kwargs])
    values = list(kwargs.values()) + [user_id]
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute(f"UPDATE social_media_accounts SET {fields} WHERE user_id = ?", values)
    conn.commit()
    conn.close()

def get_player_name(user_id):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    c.execute("SELECT player_name FROM player_representatives WHERE user_id = ?", (user_id,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else None

def get_team_flag(team_name):
    flags = {
        "India": "🇮🇳", "Pakistan": "🇵🇰", "Australia": "🇦🇺", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
        "New Zealand": "🇳🇿", "South Africa": "🇿🇦", "West Indies": "🏝️", "Sri Lanka": "🇱🇰",
        "Bangladesh": "🇧🇩", "Afghanistan": "🇦🇫", "Netherlands": "🇳🇱", "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
        "Ireland": "🇮🇪", "Zimbabwe": "🇿🇼", "UAE": "🇦🇪", "Canada": "🇨🇦", "USA": "🇺🇸"
    }
    return flags.get(team_name, "🏳️")

def format_money(amount):
    if amount >= 1_000_000:
        return f"${amount/1_000_000:.2f}M"
    elif amount >= 1_000:
        return f"${amount/1_000:.1f}K"
    return f"${amount}"

def cooldown_check(last_time_str, hours):
    if not last_time_str:
        return True, 0
    try:
        last_time = datetime.strptime(last_time_str, '%Y-%m-%d %H:%M:%S')
        delta = datetime.utcnow() - last_time
        remaining = timedelta(hours=hours) - delta
        if remaining.total_seconds() <= 0:
            return True, 0
        return False, int(remaining.total_seconds() / 60)
    except:
        return True, 0

def stat_bar(value, max_val=100, length=10):
    filled = round((value / max_val) * length)
    return "█" * filled + "░" * (length - filled)

# ============================================================
# DATA CONSTANTS
# ============================================================

CARS = {
    "honda_civic": {"name": "Honda Civic", "emoji": "🚗", "price": 25000, "prestige": 5},
    "bmw_m3": {"name": "BMW M3", "emoji": "🏎️", "price": 80000, "prestige": 20},
    "mercedes_amg": {"name": "Mercedes AMG GT", "emoji": "🏎️", "price": 150000, "prestige": 35},
    "lamborghini": {"name": "Lamborghini Huracán", "emoji": "🦄", "price": 350000, "prestige": 60},
    "ferrari_sf": {"name": "Ferrari SF90", "emoji": "🔴", "price": 500000, "prestige": 75},
    "bugatti": {"name": "Bugatti Chiron", "emoji": "💎", "price": 3000000, "prestige": 100},
    "rolls_royce": {"name": "Rolls-Royce Phantom", "emoji": "👑", "price": 600000, "prestige": 90},
    "porsche_911": {"name": "Porsche 911 Turbo", "emoji": "⚡", "price": 200000, "prestige": 45},
}

HOUSES = [
    {"name": "Studio Apartment", "emoji": "🏠", "price": 0, "value": 50000},
    {"name": "City Flat", "emoji": "🏢", "price": 100000, "value": 200000},
    {"name": "Suburban House", "emoji": "🏡", "price": 400000, "value": 600000},
    {"name": "Luxury Villa", "emoji": "🏰", "price": 1500000, "value": 2500000},
    {"name": "Private Mansion", "emoji": "🏯", "price": 5000000, "value": 8000000},
    {"name": "Private Island Estate", "emoji": "🌴", "price": 15000000, "value": 25000000},
]

SPONSORS = [
    {"name": "Local Sports Shop", "emoji": "🏪", "tier": 1, "monthly": 5000, "min_fans": 5000},
    {"name": "UrbanFit Clothing", "emoji": "👕", "tier": 2, "monthly": 20000, "min_fans": 25000},
    {"name": "PowerDrink Energy", "emoji": "⚡", "tier": 3, "monthly": 75000, "min_fans": 100000},
    {"name": "SportsTech Pro", "emoji": "⌚", "tier": 4, "monthly": 200000, "min_fans": 500000},
    {"name": "GlobalAir Airlines", "emoji": "✈️", "tier": 5, "monthly": 500000, "min_fans": 1000000},
    {"name": "Nike Cricket", "emoji": "✅", "tier": 6, "monthly": 1500000, "min_fans": 5000000},
]

SCANDAL_EVENTS = [
    {"text": "was caught partying the night before a match! 🎉", "rep": -15, "fans": -5000, "cash": -10000, "conf": -10},
    {"text": "got into an argument with the umpire on live TV! 📺", "rep": -10, "fans": +2000, "cash": 0, "conf": -5},
    {"text": "was accused of ball tampering! 🏏", "rep": -25, "fans": -15000, "cash": -50000, "conf": -20},
    {"text": "posted a controversial tweet that went viral! 🐦", "rep": -20, "fans": +10000, "cash": 0, "conf": 0},
    {"text": "was seen driving at 200km/h on the highway! 🏎️", "rep": -5, "fans": +5000, "cash": -30000, "conf": +5},
    {"text": "got into a locker room brawl that was caught on camera! 🥊", "rep": -20, "fans": +8000, "cash": 0, "conf": -15},
    {"text": "skipped national team training for a brand shoot! 💸", "rep": -15, "fans": +3000, "cash": +25000, "conf": 0},
    {"text": "was spotted at a rival team's party! 🎭", "rep": -10, "fans": +2000, "cash": 0, "conf": -5},
    {"text": "made fun of a cricket legend in an interview! 🎤", "rep": -20, "fans": +15000, "cash": 0, "conf": +10},
    {"text": "leaked dressing room WhatsApp messages to the press! 📱", "rep": -30, "fans": +20000, "cash": 0, "conf": -25},
]

POSITIVE_EVENTS = [
    {"text": "saved a fan who fell in the stadium! 🦸", "rep": +20, "fans": +25000, "cash": 0, "conf": +15},
    {"text": "donated ${} to a children's cricket academy! 🏏", "rep": +25, "fans": +20000, "cash": 0, "conf": +10},
    {"text": "signed autographs for 3 hours outside the stadium! ✍️", "rep": +15, "fans": +12000, "cash": 0, "conf": +10},
    {"text": "was named as role model of the year by Cricket Monthly! 🏆", "rep": +20, "fans": +30000, "cash": +50000, "conf": +15},
    {"text": "appeared on the national TV sports show! 📺", "rep": +10, "fans": +15000, "cash": +5000, "conf": +5},
]

POST_TYPES = {
    "training": {
        "name": "Training Clip 🏋️",
        "templates": [
            "Started the day at 5am. No days off. 💪 #CricketGrind #NeverStop",
            "The nets don't lie. Putting in work every single day. 🏏 #TrainingMode",
            "Another session done. My coach says I'm looking sharper than ever. 🔥 #LevelUp",
            "When the batting machine breaks after 500 balls... buy another one 😤 #Standards",
            "Ran 10km before most people wake up. 🌅 This is the lifestyle. #Dedication",
        ],
        "base_likes": (500, 8000),
        "followers_gain": (50, 500),
        "rep_change": +2,
        "conf_change": +3,
    },
    "flex": {
        "name": "Lifestyle Flex 💎",
        "templates": [
            "New wheels just dropped 🔑 Life is good when you work hard. 🙏",
            "Views from the top suite in Dubai. Not bad for a kid from the streets 🌆",
            "Custom fitted. Dripped. Ready. 👑 #YungPlatinum",
            "They said it couldn't be done. New house, who dis? 🏠✨",
            "First class everywhere I go. 🛫 That's the standard now.",
        ],
        "base_likes": (800, 15000),
        "followers_gain": (100, 800),
        "rep_change": -2,
        "conf_change": +5,
    },
    "apology": {
        "name": "Public Apology 🙏",
        "templates": [
            "I want to sincerely apologise to everyone I've let down. I'm only human. 🙏",
            "Mistakes happen. I own mine 100%. Working to do better every day. ❤️",
            "To the fans who believed in me — I hear you. I'm sorry. Won't happen again. 💔",
            "This isn't who I am. I promise I'm working on it. Thank you for your patience 🙏",
        ],
        "base_likes": (2000, 20000),
        "followers_gain": (200, 1500),
        "rep_change": +8,
        "conf_change": -5,
    },
    "controversy": {
        "name": "Controversy Bait 💣",
        "templates": [
            "Some people in this sport don't deserve the jersey they wear. You know who you are. 👀",
            "Imagine being called a legend when you never faced real pressure. Interesting. 🤔",
            "Rankings are rigged. Fight me. 😤 #Truth",
            "A certain team's captain needs to learn what leadership actually means. 🎭",
            "Not naming names but some players' attitude in the locker room is absolutely SHOCKING 🤯",
        ],
        "base_likes": (5000, 50000),
        "followers_gain": (500, 5000),
        "rep_change": -10,
        "conf_change": +8,
    },
    "motivation": {
        "name": "Motivational Quote 🌟",
        "templates": [
            "\"Champions are made in the moments nobody sees.\" — remembering why I started. 🏏",
            "Every ball I face today is a story I'll tell my kids one day. 🌟",
            "Pain is temporary. Legacy is forever. 💪 #CricketLife",
            "Not here for applause. Here for the craft. 🙏 #Purpose",
            "Rise and grind. Today is another chance to be great. ☀️",
        ],
        "base_likes": (1500, 12000),
        "followers_gain": (100, 800),
        "rep_change": +3,
        "conf_change": +2,
    },
    "matchday": {
        "name": "Match Day Hype 🏟️",
        "templates": [
            "MATCHDAY. 🏟️ Blood, sweat and glory starts NOW. Let's GO!!!",
            "Headphones in. Tunnel vision locked. Matchday. 🔒🎵",
            "For everyone who ever doubted us — watch this space. 🏏🔥",
            "Family, flag, and pride on the line today. Won't let anyone down. 🙏🇮🇳",
            "The dressing room is electric right now. Can't wait for the nation to see this. 💪",
        ],
        "base_likes": (3000, 30000),
        "followers_gain": (300, 2500),
        "rep_change": +5,
        "conf_change": +7,
    },
}

TRASH_TALK_LINES = [
    "My warm-up lasts longer than your whole innings 😂",
    "You bowl like you're apologising to the batsman 🎳",
    "Your batting average couldn't fill a cricket scoreboard 📉",
    "I've seen more dangerous play in under-10 matches 👶",
    "Your career is shorter than a T5 match 💀",
    "My worst practice session is better than your best match 🤷",
    "They only picked you to make the numbers look right 🔢",
    "You're the reason cricket needs a mercy rule 😭",
    "I've had drinks that lasted longer than your batting 🥤",
    "The only record you'll break is 'most balls survived doing nothing' 😴",
]

PRESS_QUESTIONS = [
    {
        "question": "Critics are saying you've been underperforming. Your response?",
        "options": {
            "A": {"text": "I'm working hard. Results will follow.", "rep": +5, "conf": +3, "fans": +1000},
            "B": {"text": "Critics don't have a bat in hand. Let them try.", "rep": -5, "conf": +10, "fans": +5000},
            "C": {"text": "No comment.", "rep": -3, "conf": 0, "fans": -2000},
        }
    },
    {
        "question": "There are rumours of a rift in the dressing room. True?",
        "options": {
            "A": {"text": "Absolutely not, we're a family.", "rep": +5, "conf": +2, "fans": +500},
            "B": {"text": "What happens in the dressing room stays there.", "rep": +3, "conf": 0, "fans": +1000},
            "C": {"text": "I'll say this — some need to check their ego.", "rep": -10, "conf": +8, "fans": +8000},
        }
    },
    {
        "question": "How do you respond to being dropped from the squad?",
        "options": {
            "A": {"text": "I respect the selectors' decision. I'll work harder.", "rep": +8, "conf": -5, "fans": +2000},
            "B": {"text": "I disagree. I deserved that spot.", "rep": -5, "conf": +5, "fans": +4000},
            "C": {"text": "It's political. Nothing to do with performance.", "rep": -15, "conf": +10, "fans": +10000},
        }
    },
    {
        "question": "What's your message to young cricketers watching?",
        "options": {
            "A": {"text": "Believe in your dream and work relentlessly.", "rep": +10, "conf": +5, "fans": +5000},
            "B": {"text": "Get a good agent first. This sport is a business.", "rep": -5, "conf": +3, "fans": +3000},
            "C": {"text": "Watch me. I'll show you how it's done.", "rep": -2, "conf": +8, "fans": +2000},
        }
    },
    {
        "question": "Will you be announcing your retirement soon?",
        "options": {
            "A": {"text": "I've got years left. Count me in.", "rep": +5, "conf": +8, "fans": +3000},
            "B": {"text": "I'll go when cricket says goodbye, not when critics do.", "rep": +8, "conf": +10, "fans": +6000},
            "C": {"text": "Maybe. I haven't decided. It's complicated.", "rep": -5, "conf": -5, "fans": -3000},
        }
    },
]

LOCKER_ROOM_MESSAGES = [
    "Bro you were 🔥 in today's match, the crowd went MAD",
    "Between us - our captain has absolutely no idea what he's doing 😭",
    "Who keeps leaving their pads in the middle of the room?? 😤",
    "The team dinner was goated ngl 🍗 feeling locked in for tomorrow",
    "Bro you HAVE to get that haircut before the next match 💀",
    "Did you see coach's face when you hit that six? PRICELESS 😂",
    "Secret: I listen to pop music before every match. Don't tell anyone 🎵",
    "I'm so nervous for tomorrow I can't sleep 😰",
    "Bro your celebration after that wicket had me DEAD 💀",
    "Honestly? I think we're winning this tournament. Don't jinx it 🤫",
]

MARITAL_STATUSES = ["Single", "In a Relationship", "Engaged", "Married", "It's Complicated", "Divorced"]

RELATIONSHIP_EVENTS = [
    "Your partner surprised you at the stadium! +10 happiness 🥰",
    "Date night after a long tour. Feeling recharged! +15 happiness 💑",
    "Relationship drama leaked to the press! -10 rep 😬",
    "Partner gave you a pep talk before the match. +8 confidence! 💪",
    "Anniversary dinner at a 5-star restaurant. -$2000 💸",
]


# ============================================================
# AI FEED HELPERS
# ============================================================

def get_cricket_players():
    """Load player names from players.json (simple list for fallback usage)."""
    players = []
    try:
        with open('players.json', 'r') as f:
            data = json.load(f)
            if isinstance(data, list):
                for team_entry in data:
                    if isinstance(team_entry, dict) and 'players' in team_entry:
                        for p in team_entry['players']:
                            name = p.get('name', '')
                            if name:
                                players.append(name)
                    elif isinstance(team_entry, dict):
                        name = team_entry.get('name') or team_entry.get('player_name') or team_entry.get('fullName', '')
                        if name:
                            players.append(name)
                    elif isinstance(team_entry, str):
                        players.append(team_entry)
    except Exception:
        pass

    if not players:
        players = [
            "Virat Kohli", "Rohit Sharma", "MS Dhoni", "Jasprit Bumrah",
            "Babar Azam", "Shaheen Afridi", "Mohammad Rizwan",
            "Pat Cummins", "Steve Smith", "David Warner",
            "Ben Stokes", "Joe Root", "Jos Buttler",
            "Kane Williamson", "Trent Boult",
            "Kagiso Rabada", "Quinton de Kock",
            "Shakib Al Hasan", "Rashid Khan"
        ]
    return players[:40]


def get_feed_player_data(bot=None):
    """
    Returns a rich dict of claimed players with their stats and discord username.
    Used to inject real bot data into the AI feed prompt.
    Format: {player_name: {discord: "@username", team: "India", runs: 340, wickets: 12,
                           economy: 6.4, strike_rate: 142.0, matches: 8, highest: 67,
                           best_bowling: "3/24", centuries: 0, fifties: 2, impact: 424}}
    """
    result = {}
    try:
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        # Get all claimed players with user_id
        c.execute("""
            SELECT pr.player_name, pr.user_id
            FROM player_representatives pr
            WHERE pr.player_name IS NOT NULL
        """)
        claimed = c.fetchall()

        for player_name, user_id in claimed:
            # Career batting + bowling stats
            c.execute("""
                SELECT
                    SUM(runs) as total_runs,
                    SUM(balls_faced) as total_balls,
                    SUM(wickets) as total_wkts,
                    SUM(balls_bowled) as balls_bowled,
                    SUM(runs_conceded) as runs_conceded,
                    SUM(not_out) as not_outs,
                    COUNT(*) as matches,
                    MAX(runs) as highest,
                    MAX(wickets) as best_wkts
                FROM match_stats WHERE user_id = ?
            """, (user_id,))
            row = c.fetchone()

            # Tournament points table - find team
            team = None
            try:
                with open('players.json', 'r') as f:
                    teams_data = json.load(f)
                for td in teams_data:
                    if isinstance(td, dict) and 'players' in td:
                        for p in td['players']:
                            if p.get('name') == player_name:
                                team = td.get('team')
                                break
            except Exception:
                pass

            # Discord username lookup via bot
            discord_handle = f"@{player_name.lower().replace(' ', '_')}"
            if bot:
                try:
                    # Try to find the member across guilds the bot is in
                    for guild in bot.guilds:
                        member = guild.get_member(user_id)
                        if member:
                            discord_handle = f"@{member.name}"
                            break
                except Exception:
                    pass
            else:
                # Fallback: store user_id so we can look up later
                discord_handle = f"uid:{user_id}"

            if row and row[0] is not None:
                total_runs = int(row[0] or 0)
                total_balls_faced = int(row[1] or 0)
                total_wkts = int(row[2] or 0)
                balls_bowled = int(row[3] or 0)
                runs_conceded = int(row[4] or 0)
                not_outs = int(row[5] or 0)
                matches = int(row[6] or 0)
                highest = int(row[7] or 0)
                best_wkts = int(row[8] or 0)

                sr = round((total_runs / total_balls_faced * 100), 1) if total_balls_faced > 0 else 0.0
                eco = round((runs_conceded / (balls_bowled / 6)), 2) if balls_bowled > 0 else 0.0
                dismissals = matches - not_outs
                avg = round(total_runs / dismissals, 1) if dismissals > 0 else total_runs

                # Centuries and fifties
                c.execute("SELECT COUNT(*) FROM match_stats WHERE user_id = ? AND runs >= 100", (user_id,))
                centuries = c.fetchone()[0]
                c.execute("SELECT COUNT(*) FROM match_stats WHERE user_id = ? AND runs >= 50 AND runs < 100", (user_id,))
                fifties = c.fetchone()[0]

                # Best bowling figures: max wickets in one match, least runs that match
                c.execute("""
                    SELECT wickets, runs_conceded FROM match_stats
                    WHERE user_id = ? AND wickets > 0
                    ORDER BY wickets DESC, runs_conceded ASC LIMIT 1
                """, (user_id,))
                bb_row = c.fetchone()
                best_bowling = f"{bb_row[0]}/{bb_row[1]}" if bb_row else "0/0"

                # Impact points formula from cricket_stats.py
                c.execute("""
                    SELECT SUM(
                        runs + (wickets * 7) +
                        CASE WHEN wickets >= 5 THEN 70 WHEN wickets >= 3 THEN 40 ELSE 0 END +
                        CASE WHEN runs >= 100 THEN 100 WHEN runs >= 50 THEN 65 ELSE 0 END
                    ) FROM match_stats WHERE user_id = ?
                """, (user_id,))
                impact_row = c.fetchone()
                impact = int(impact_row[0] or 0)

                result[player_name] = {
                    'discord': discord_handle,
                    'team': team or 'Unknown',
                    'matches': matches,
                    'runs': total_runs,
                    'balls_faced': total_balls_faced,
                    'strike_rate': sr,
                    'average': avg,
                    'highest': highest,
                    'centuries': centuries,
                    'fifties': fifties,
                    'wickets': total_wkts,
                    'economy': eco,
                    'best_bowling': best_bowling,
                    'impact': impact,
                }
            else:
                # Claimed but no stats yet
                result[player_name] = {
                    'discord': discord_handle,
                    'team': team or 'Unknown',
                    'matches': 0,
                    'runs': 0, 'balls_faced': 0, 'strike_rate': 0.0,
                    'average': 0.0, 'highest': 0, 'centuries': 0, 'fifties': 0,
                    'wickets': 0, 'economy': 0.0, 'best_bowling': '0/0', 'impact': 0,
                }

        conn.close()
    except Exception as e:
        pass

    return result


def get_tournament_context():
    """Get active tournament standings for feed context."""
    try:
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("""
            SELECT t.name, tt.team_name, tt.points, tt.wins, tt.losses, tt.nrr, tt.matches_played
            FROM tournaments t
            JOIN tournament_teams tt ON t.id = tt.tournament_id
            WHERE t.is_active = 1 AND t.is_archived = 0
            ORDER BY tt.points DESC, tt.nrr DESC
        """)
        rows = c.fetchall()
        conn.close()
        if not rows:
            return None, []
        tourney_name = rows[0][0]
        standings = [
            {'team': r[1], 'pts': r[2], 'wins': r[3], 'losses': r[4], 'nrr': r[5], 'played': r[6]}
            for r in rows
        ]
        return tourney_name, standings
    except Exception:
        return None, []


import time as _time

# Fallback posts used when Gemini is rate-limited
FALLBACK_POSTS = {
    'english': [
        {"handle": "@cricket_soul99", "bio": "🏏 Cricket is religion", "content": "That last over was absolutely INSANE! The bowler was on fire, gave nothing away under pressure. This is what cricket is all about 🔥 #Cricket #T20", "likes": 847, "comments": 34, "time": "2h ago", "language": "english"},
        {"handle": "@stump_mic_fan", "bio": "Watching cricket since 1992 📺", "content": "People sleeping on how good Bumrah has been this series. 4 wickets and economy of 4.2? Absolute weapon. No one else comes close right now 💪 #Bumrah", "likes": 2341, "comments": 89, "time": "5h ago", "language": "english"},
        {"handle": "@sixhitter_vibes", "bio": "T20 addict | IPL every season", "content": "Unpopular opinion: Test cricket is still the ultimate format. Nothing tests a player's character like 5 days of pressure. Change my mind. 🏏 #TestCricket", "likes": 512, "comments": 156, "time": "1d ago", "language": "english"},
        {"handle": "@yorker_king_fan", "bio": "Fast bowling enthusiast ⚡", "content": "That cover drive in the last match was poetry. Textbook technique, perfect timing. The batting coach must be proud 😍 #Cricket", "likes": 1203, "comments": 41, "time": "3h ago", "language": "english"},
    ],
    'hinglish': [
        {"handle": "@desi_cricket_bhai", "bio": "Dil se cricket fan 🇮🇳", "content": "Yaar aaj ki innings toh kamaal thi! Bilkul mast batting ki usne, bhai logo ko samajh nahi aata iski value 🔥 #Cricket #India", "likes": 1847, "comments": 67, "time": "1h ago", "language": "hinglish"},
        {"handle": "@rohit_gang_official", "bio": "Hitman ka fan forever 💙", "content": "Bhai yeh log kya bolte rehte hain drop karo drop karo — ek match mein hi saara hisaab chukta kar diya usne 😤 Iski class dekho phir baat karo 🙌", "likes": 3421, "comments": 203, "time": "4h ago", "language": "hinglish"},
        {"handle": "@cricket_masala_daily", "bio": "Cricket gossip & updates 🏏", "content": "Kya scene hai yaar! Jab se naya captain aaya hai team ka mood hi alag hai. Ekdum positive vibes, sab ek saath khel rahe hain. Love to see it 🥹 #TeamIndia", "likes": 892, "comments": 55, "time": "6h ago", "language": "hinglish"},
        {"handle": "@ipl_fanatic_007", "bio": "IPL har season dekhta hoon 👀", "content": "Bhai honestly bol raha hoon iski tara koi bowl nahi kar sakta abhi. Woh angle, woh pace — matlab yaar dil khush ho gaya aaj 🎯 #Cricket", "likes": 2109, "comments": 78, "time": "2h ago", "language": "hinglish"},
    ],
}

def _get_fallback_posts(language_filter: str) -> list:
    """Return shuffled fallback posts when API is unavailable."""
    if language_filter == 'english':
        posts = list(FALLBACK_POSTS['english'])
    elif language_filter == 'hinglish':
        posts = list(FALLBACK_POSTS['hinglish'])
    else:
        posts = list(FALLBACK_POSTS['english'][:2]) + list(FALLBACK_POSTS['hinglish'][:2])
    random.shuffle(posts)
    # Randomise likes/comments slightly so it feels fresh
    for p in posts:
        p = dict(p)
        p['likes'] = max(10, p['likes'] + random.randint(-200, 400))
        p['comments'] = max(1, p['comments'] + random.randint(-10, 30))
    return posts


def call_gemini_sync(prompt: str) -> str:
    """
    Call Gemini REST API once. On 429 raises RuntimeError("RATE_LIMITED")
    immediately so the async caller can handle the wait without blocking.
    """
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 1.0, "maxOutputTokens": 3000}
    }).encode('utf-8')
    req = urllib.request.Request(
        GEMINI_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            text = data['candidates'][0]['content']['parts'][0]['text']
            print(f"[GEMINI] HTTP 200 OK — response length: {len(text)} chars")
            return text
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"[GEMINI] HTTP 429 Too Many Requests — raising RATE_LIMITED")
            raise RuntimeError("RATE_LIMITED")
        print(f"[GEMINI] HTTP {e.code} error")
        raise RuntimeError(f"Gemini API error: HTTP {e.code}")
    except Exception as e:
        print(f"[GEMINI] Exception: {type(e).__name__}: {e}")
        raise RuntimeError(f"Gemini API error: {e}")


async def call_gemini(prompt: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, call_gemini_sync, prompt)


def build_feed_prompt(player_data: dict, language_filter: str, page: int,
                      tourney_name: str = None, standings: list = None) -> str:
    """
    Build a Gemini prompt that injects real bot stats, discord usernames,
    tournament standings, and varies content by page type.
    """
    lang_instruction = {
        'all':      'Mix of English and Hinglish (Roman script). Roughly 50/50.',
        'english':  'All posts in English only.',
        'hinglish': 'All posts in Hinglish (Hindi in Roman script, e.g. "yaar", "bhai", "ekdum mast", "kya scene hai bhai"). NO Devanagari script.'
    }.get(language_filter, 'Mix of English and Hinglish.')

    # Page themes — each page has a DIFFERENT personality/content angle
    PAGE_THEMES = [
        "general fan reactions, player praise, match excitement",
        "TOXIC DRAMA PAGE — every single post must be salty, savage, brutal trash-talk about specific players and their bad stats. Include specific numbers (e.g. 'scored 4 off 18 balls lmao', '0 wickets in 3 matches', 'economy 14.2 bruh'). Roast players, call them overrated, mock their performances. Pure drama and toxicity. Fans fighting in comments. Be brutal and funny.",
        "leaderboard/stats obsession — posts referencing who tops the runs/wickets/economy/impact leaderboard (-lb), who's underperforming vs their stats, heated debates about rankings",
        "predictions, hot takes, controversial opinions about who will win the tournament, who should be dropped",
        "funny/meme-style posts, wholesome moments, player banter, fan celebrations mixed with light roasting",
        "tactical analysis mixed with drama — posts about team strategies, why certain teams are winning or losing in the tournament table (-pts)",
        "TOXIC DRAMA PAGE 2 — even MORE savage than page 2. Flame wars between rival fans, personal attacks on players' consistency, drag their economy rates and ducks through the mud. 'bhai yeh century nahi maar sakta kabhi', 'highest score 7 runs 💀💀', 'bench player energy fr'. Maximum toxicity.",
        "heartfelt appreciation posts mixed with subtle shade at rivals, trophy talk, NRR anxiety posts",
    ]
    theme = PAGE_THEMES[page % len(PAGE_THEMES)]

    # Pick a random sample of players WITH their stats for the prompt
    all_players = list(player_data.items())
    sample_players = random.sample(all_players, min(8, len(all_players))) if all_players else []

    # Build the player context block
    player_block_lines = []
    for pname, pstats in sample_players:
        discord_tag = pstats.get('discord', '@unknown')
        # Resolve uid: format entries as generic tags when no bot available
        if discord_tag.startswith('uid:'):
            discord_tag = f"@{pname.lower().split()[0]}_player"
        team = pstats.get('team', '?')
        runs = pstats.get('runs', 0)
        wkts = pstats.get('wickets', 0)
        sr = pstats.get('strike_rate', 0)
        eco = pstats.get('economy', 0)
        highest = pstats.get('highest', 0)
        best_bowl = pstats.get('best_bowling', '0/0')
        avg = pstats.get('average', 0)
        matches = pstats.get('matches', 0)
        impact = pstats.get('impact', 0)
        centuries = pstats.get('centuries', 0)
        fifties = pstats.get('fifties', 0)
        player_block_lines.append(
            f"  - {pname} ({discord_tag}) [{team}]: "
            f"{matches}M, {runs}R, SR={sr}, Avg={avg}, HS={highest}, {centuries}×100, {fifties}×50, "
            f"{wkts}wkts, Eco={eco}, BB={best_bowl}, Impact={impact}"
        )
    player_block = "\n".join(player_block_lines) if player_block_lines else "  (No player data available)"

    # Tournament context block
    tourney_block = ""
    if tourney_name and standings:
        top5 = standings[:5]
        rows = [f"  {i+1}. {s['team']} — {s['pts']}pts, W{s['wins']}L{s['losses']}, NRR {s['nrr']:+.3f}"
                for i, s in enumerate(top5)]
        tourney_block = f"\nActive Tournament: {tourney_name}\nTop standings:\n" + "\n".join(rows)

    seed = f"P{page}_D{datetime.utcnow().strftime('%Y%m%d')}_T{theme[:12].replace(' ','')}"

    prompt = f"""You are writing fake fan social media posts for "CricketGram" — a social feed inside a Discord cricket bot.

Page seed: {seed}
Page theme: {theme}
Language rule: {lang_instruction}

=== REAL PLAYER DATA FROM THE BOT ===
(These are real players claimed by Discord users in this cricket bot. Use their ACTUAL stats in your posts.)
{player_block}
{tourney_block}

=== STRICT RULES ===
1. Generate EXACTLY 4 posts, each completely different from the others on this page.
2. EVERY post MUST mention at least one real player from the list above BY NAME, including their Discord handle in parentheses — e.g. "Virat Kohli (@virat99)".
3. Use the REAL stats when talking about players — mention actual run counts, strike rates, economy, wickets, impact points, highest scores, ducks, etc. Make it feel like fans genuinely follow the leaderboard (-lb) and points table (-pts).
4. Follow the page theme closely. If it says TOXIC, be genuinely savage and roast players with their real bad stats.
5. Every page must feel DIFFERENT. Do not repeat styles or topics across pages.
6. Posts can reference: match results, leaderboard standings (-lb), impact points, economy rates, batting averages, tournament points table (-pts), NRR, player consistency or lack thereof, who topped the -lb this week, etc.
7. Language must match the rule — if Hinglish, use Roman script Hindi words naturally.
8. Handles should be creative cricket fan usernames, not the players' own names.

=== JSON SCHEMA ===
Return ONLY a valid JSON array (no markdown, no explanation):
[
  {{
    "handle": "@fan_username",
    "bio": "short fan bio 1 line",
    "content": "post content (1-3 sentences, emojis, hashtags, player name with (@discordhandle))",
    "likes": 123,
    "comments": 45,
    "time": "2h ago",
    "language": "english"
  }}
]"""

    return prompt


def get_feed_from_cache(cache_date: str, language_filter: str, page: int):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    try:
        c.execute(
            "SELECT posts_json FROM ai_feed_cache WHERE cache_date=? AND language_filter=? AND page_number=?",
            (cache_date, language_filter, page)
        )
        row = c.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception:
        conn.close()
    return None


def save_feed_to_cache(cache_date: str, language_filter: str, page: int, posts: list):
    conn = sqlite3.connect('players.db')
    c = conn.cursor()
    try:
        c.execute(
            "INSERT OR REPLACE INTO ai_feed_cache (cache_date, language_filter, page_number, posts_json) VALUES (?,?,?,?)",
            (cache_date, language_filter, page, json.dumps(posts))
        )
        conn.commit()
    except Exception:
        pass
    conn.close()


async def get_feed_page(language_filter: str, page: int, bot=None) -> tuple:
    """Returns (posts, is_fallback). Caches AI results, uses fallback on rate limit."""
    today = datetime.utcnow().strftime('%Y-%m-%d')
    cached = get_feed_from_cache(today, language_filter, page)
    if cached:
        return cached, False

    # Get rich player data with real stats and discord handles
    player_data = get_feed_player_data(bot=bot)
    tourney_name, standings = get_tournament_context()

    # Fall back to simple player list if no claimed players exist yet
    if not player_data:
        simple_players = get_cricket_players()
        player_data = {p: {'discord': f'@{p.lower().split()[0]}fan', 'team': 'Unknown',
                           'matches': 0, 'runs': 0, 'wickets': 0, 'strike_rate': 0.0,
                           'economy': 0.0, 'average': 0.0, 'highest': 0, 'best_bowling': '0/0',
                           'centuries': 0, 'fifties': 0, 'impact': 0}
                       for p in simple_players}

    prompt = build_feed_prompt(player_data, language_filter, page, tourney_name, standings)

    try:
        raw = await call_gemini(prompt)
        raw = raw.strip()
        if raw.startswith('```'):
            parts = raw.split('```')
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith('json'):
                raw = raw[4:]
        raw = raw.strip()
        posts = json.loads(raw)
        save_feed_to_cache(today, language_filter, page, posts)
        return posts, False
    except RuntimeError as e:
        if 'RATE_LIMITED' in str(e):
            return _get_fallback_posts(language_filter), True
        raise


def build_feed_embed(posts: list, page: int, language_filter: str, is_loading: bool = False, is_fallback: bool = False) -> discord.Embed:
    lang_emoji = {'all': '🌐', 'english': '🇬🇧', 'hinglish': '🇮🇳'}.get(language_filter, '🌐')
    lang_name = {'all': 'All Languages', 'english': 'English Only', 'hinglish': 'Hinglish Only'}.get(language_filter, 'All')
    embed = discord.Embed(
        title=f"📱 CricketGram Fan Feed  {lang_emoji} {lang_name}",
        description=f"*What fans are saying today... Page {page + 1}*",
        color=0xE1306C
    )
    if is_loading:
        embed.description = "⏳ *Generating AI fan posts... please wait a moment...*"
        embed.set_footer(text="Powered by Gemini AI | Refreshes daily")
        return embed
    if not posts:
        embed.description = "Could not load feed. Try again!"
        return embed
    for post in posts:
        handle = post.get('handle', '@unknown')
        bio = post.get('bio', '')
        content = post.get('content', '')
        likes = post.get('likes', 0)
        comments = post.get('comments', 0)
        time_ago = post.get('time', 'recently')
        lang_tag = "🇮🇳" if post.get('language') == 'hinglish' else "🇬🇧"
        field_name = f"{lang_tag} {handle}  •  {time_ago}"
        field_value = f"*{bio}*\n{content}\n❤️ **{likes:,}**  💬 **{comments}**"
        embed.add_field(name=field_name, value=field_value, inline=False)
    today_str = datetime.utcnow().strftime('%B %d, %Y')
    if is_fallback:
        embed.set_footer(text=f"⚠️ AI rate-limited — showing sample posts | Retry with 🔄 | {today_str}")
        embed.color = 0xFF8C00  # Orange tint to signal fallback
    else:
        embed.set_footer(text=f"📅 {today_str} | Refreshes daily at midnight UTC | Gemini AI")
    return embed

# ============================================================
# VIEWS
# ============================================================

class PressConferenceView(View):
    def __init__(self, ctx, question_data):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.question_data = question_data
        self.answered = False

        for key, opt in question_data["options"].items():
            btn = Button(label=f"{key}: {opt['text']}", style=discord.ButtonStyle.primary, custom_id=key)
            btn.callback = self.make_callback(key)
            self.add_item(btn)

    def make_callback(self, key):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.ctx.author.id:
                await interaction.response.send_message("❌ This press conference isn't yours!", ephemeral=True)
                return
            if self.answered:
                await interaction.response.send_message("Already answered!", ephemeral=True)
                return
            self.answered = True
            opt = self.question_data["options"][key]
            life = get_life(interaction.user.id)
            new_rep = max(0, min(100, life["reputation"] + opt["rep"]))
            new_conf = max(0, min(100, life["confidence"] + opt["conf"]))
            new_fans = max(0, life["fans"] + opt["fans"])
            update_life(interaction.user.id, reputation=new_rep, confidence=new_conf, fans=new_fans,
                        last_press=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
            color = 0x00FF00 if opt["rep"] >= 0 else 0xFF0000
            embed = discord.Embed(title="🎤 Press Conference", color=color)
            embed.add_field(name="Your Response", value=f'*"{opt["text"]}"*', inline=False)
            changes = []
            if opt["rep"] != 0: changes.append(f"Reputation: {opt['rep']:+d}")
            if opt["conf"] != 0: changes.append(f"Confidence: {opt['conf']:+d}")
            if opt["fans"] != 0: changes.append(f"Fans: {opt['fans']:+,}")
            embed.add_field(name="Impact", value="\n".join(changes) if changes else "No change", inline=False)
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

class SocialPostTypeView(View):
    def __init__(self, ctx, cog):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.cog = cog

        for key, data in POST_TYPES.items():
            btn = Button(label=data["name"], style=discord.ButtonStyle.primary)
            btn.callback = self.make_cb(key)
            self.add_item(btn)

    def make_cb(self, post_key):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.ctx.author.id:
                await interaction.response.send_message("Not your menu!", ephemeral=True)
                return
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(view=self)
            await self.cog._do_post(interaction, post_key)
        return callback

class BuyCarView(View):
    def __init__(self, ctx, cog):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.cog = cog
        for car_id, car in list(CARS.items())[:5]:
            btn = Button(label=f"{car['emoji']} {car['name']} ({format_money(car['price'])})", style=discord.ButtonStyle.primary)
            btn.callback = self.make_cb(car_id)
            self.add_item(btn)
        more_btn = Button(label="🔽 See Luxury Cars", style=discord.ButtonStyle.secondary, row=1)
        more_btn.callback = self.show_more
        self.add_item(more_btn)

    def make_cb(self, car_id):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.ctx.author.id:
                return
            await self.cog._purchase_car(interaction, car_id)
        return callback

    async def show_more(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            return
        embed = discord.Embed(title="🏎️ Luxury Car Showroom", color=0xFFD700,
                              description="Welcome to the exclusive tier. These aren't just cars — they're statements.")
        luxury = {k: v for k, v in CARS.items() if v["price"] >= 200000}
        for car_id, car in luxury.items():
            embed.add_field(name=f"{car['emoji']} {car['name']}", 
                          value=f"Price: **{format_money(car['price'])}**\nPrestige: {'⭐'*min(5, car['prestige']//20)}", inline=True)
        embed.set_footer(text="Use -buycar <car name> to purchase")
        await interaction.response.send_message(embed=embed, ephemeral=True)

class FeedView(View):
    """Interactive paginated AI fan feed with language filters and navigation."""

    def __init__(self, ctx, initial_page: int = 0, language_filter: str = 'all', bot=None):
        super().__init__(timeout=300)
        self.ctx = ctx
        self.page = initial_page
        self.language_filter = language_filter
        self.is_loading = False
        self.bot = bot
        self._update_buttons()

    def _update_buttons(self):
        self.clear_items()

        # Language filter buttons
        langs = [('🌐 All', 'all'), ('🇬🇧 English', 'english'), ('🇮🇳 Hinglish', 'hinglish')]
        for label, lang in langs:
            btn = Button(
                label=label,
                style=discord.ButtonStyle.success if self.language_filter == lang else discord.ButtonStyle.secondary,
                row=0
            )
            btn.callback = self._make_lang_cb(lang)
            self.add_item(btn)

        # Refresh button
        refresh_btn = Button(label="🔄 Refresh Page", style=discord.ButtonStyle.secondary, row=0)
        refresh_btn.callback = self.refresh_page
        self.add_item(refresh_btn)

        # Navigation
        prev_btn = Button(label="⬅️ Prev", style=discord.ButtonStyle.primary, disabled=(self.page == 0), row=1)
        prev_btn.callback = self.prev_page
        self.add_item(prev_btn)

        page_btn = Button(label=f"Page {self.page + 1}", style=discord.ButtonStyle.secondary, disabled=True, row=1)
        self.add_item(page_btn)

        next_btn = Button(label="➡️ Next", style=discord.ButtonStyle.primary, row=1)
        next_btn.callback = self.next_page
        self.add_item(next_btn)

    def _make_lang_cb(self, lang: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.ctx.author.id:
                await interaction.response.send_message("This feed belongs to someone else!", ephemeral=True)
                return
            self.language_filter = lang
            self.page = 0
            await self._load_and_update(interaction)
        return callback

    async def prev_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Not your feed!", ephemeral=True)
            return
        if self.page > 0:
            self.page -= 1
        await self._load_and_update(interaction)

    async def next_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Not your feed!", ephemeral=True)
            return
        self.page += 1
        await self._load_and_update(interaction)

    async def refresh_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Not your feed!", ephemeral=True)
            return
        # Force re-generate by deleting cache for this page
        today = datetime.utcnow().strftime('%Y-%m-%d')
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        try:
            c.execute(
                "DELETE FROM ai_feed_cache WHERE cache_date=? AND language_filter=? AND page_number=?",
                (today, self.language_filter, self.page)
            )
            conn.commit()
        except Exception:
            pass
        conn.close()
        await self._load_and_update(interaction)

    async def _load_and_update(self, interaction: discord.Interaction):
        # Show loading state
        self._update_buttons()
        loading_embed = build_feed_embed([], self.page, self.language_filter, is_loading=True)
        await interaction.response.edit_message(embed=loading_embed, view=self)

        # Generate posts
        try:
            posts, is_fallback = await get_feed_page(self.language_filter, self.page, bot=self.bot)
            embed = build_feed_embed(posts, self.page, self.language_filter, is_fallback=is_fallback)
        except Exception as e:
            embed = discord.Embed(
                title="📱 CricketGram Fan Feed",
                description=f"❌ Failed to generate feed: {str(e)[:200]}\n\nTry again in a moment!",
                color=0xFF0000
            )

        self._update_buttons()
        await interaction.edit_original_response(embed=embed, view=self)


# ============================================================
# MAIN COG
# ============================================================

class PlayerLife(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---- ENSURE PROFILE ----
    def cog_check_and_ensure(self, user_id):
        ensure_life(user_id)
        return get_life(user_id)

    # ==================================================
    # PROFILE & NET WORTH
    # ==================================================

    @commands.command(name="profile", aliases=["pf"], help="View your cricket life profile")
    async def profile_command(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        ensure_life(target.id)
        life = get_life(target.id)
        social = get_social(target.id)
        player_name = get_player_name(target.id)

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*) FROM player_cars WHERE user_id = ?", (target.id,))
            car_count = c.fetchone()[0]
        except: car_count = 0
        try:
            c.execute("SELECT COUNT(*) FROM player_properties WHERE user_id = ?", (target.id,))
            prop_count = c.fetchone()[0]
        except: prop_count = 0
        try:
            c.execute("SELECT COUNT(*) FROM player_rivals WHERE user_id = ?", (target.id,))
            rival_count = c.fetchone()[0]
        except: rival_count = 0
        try:
            c.execute("SELECT trophy_name FROM player_trophies WHERE user_id = ? ORDER BY awarded_at DESC LIMIT 3", (target.id,))
            trophies = [r[0] for r in c.fetchall()]
        except: trophies = []
        conn.close()

        house = HOUSES[min(life["house_level"], len(HOUSES)-1)]
        rep_bar = stat_bar(life["reputation"])
        conf_bar = stat_bar(life["confidence"])
        fit_bar = stat_bar(life["fitness"])
        energy_bar = stat_bar(life["energy"])
        happy_bar = stat_bar(life["happiness"])

        verified = "✅ Verified" if social and social["verification_status"] else "⬜ Unverified"

        embed = discord.Embed(
            title=f"🎯 {player_name or target.display_name}'s Cricket Life",
            color=0xFFD700
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        # Status
        ms_emoji = {"Single": "🧍", "In a Relationship": "💑", "Engaged": "💍", "Married": "💒", 
                    "It's Complicated": "🤷", "Divorced": "💔"}.get(life["marital_status"], "🧍")
        status_val = f"{ms_emoji} **{life['marital_status']}**"
        if life["partner_name"]:
            status_val += f" with {life['partner_name']}"

        embed.add_field(name="💰 Finances", 
                       value=f"Cash: **{format_money(life['cash'])}**\nBank: **{format_money(life['bank'])}**\nContract: **{format_money(life['contract_value'])}/mo**", 
                       inline=True)
        embed.add_field(name="📊 Stats",
                       value=f"Rep: `{rep_bar}` {life['reputation']}\nConf: `{conf_bar}` {life['confidence']}\nFitness: `{fit_bar}` {life['fitness']}", 
                       inline=True)
        embed.add_field(name="❤️ Wellbeing",
                       value=f"Energy: `{energy_bar}` {life['energy']}\nHappy: `{happy_bar}` {life['happiness']}\n{status_val}",
                       inline=True)
        embed.add_field(name="📱 Social Media",
                       value=f"Followers: **{social['followers']:,}** | {verified}\nPosts: {social['posts']} | Viral: {social['viral_posts']}\nLikes: {social['total_likes']:,}",
                       inline=True)
        embed.add_field(name="🏠 Lifestyle",
                       value=f"{house['emoji']} {house['name']}\n🚗 {car_count} car(s) owned\n🏅 Rival count: {rival_count}",
                       inline=True)
        embed.add_field(name="🏆 Recent Trophies",
                       value="\n".join(trophies) if trophies else "None yet", inline=True)

        if life["sponsor_name"]:
            embed.add_field(name="🤝 Sponsor", value=f"{life['sponsor_name']}", inline=False)
        embed.add_field(name="👥 Fans", value=f"**{life['fans']:,}** fans | Loyalty: {stat_bar(life['fan_loyalty'])} {life['fan_loyalty']}", inline=False)

        embed.set_footer(text=f"Use -networth for full financial breakdown • -fans for fan details")
        await ctx.send(embed=embed)

    @commands.command(name="networth", aliases=["nw"], help="View your total net worth breakdown")
    async def networth_command(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        ensure_life(target.id)
        life = get_life(target.id)
        player_name = get_player_name(target.id)

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("SELECT car_name, car_value FROM player_cars WHERE user_id = ?", (target.id,))
        cars = c.fetchall()
        c.execute("SELECT property_name, property_value FROM player_properties WHERE user_id = ?", (target.id,))
        props = c.fetchall()
        conn.close()

        cash_total = life["cash"] + life["bank"]
        car_total = sum(v for _, v in cars)
        prop_total = sum(v for _, v in props)
        house_val = HOUSES[min(life["house_level"], len(HOUSES)-1)]["value"]
        contract_annual = life["contract_value"] * 12
        grand_total = cash_total + car_total + prop_total + house_val

        embed = discord.Embed(
            title=f"💎 {player_name or target.display_name}'s Net Worth",
            description=f"### Total: **{format_money(grand_total)}**",
            color=0xFFD700
        )

        embed.add_field(name="💵 Cash & Bank", 
                       value=f"Wallet: {format_money(life['cash'])}\nBank: {format_money(life['bank'])}\nSubtotal: **{format_money(cash_total)}**", inline=True)

        house = HOUSES[min(life["house_level"], len(HOUSES)-1)]
        embed.add_field(name="🏠 Property", 
                       value=f"{house['emoji']} {house['name']}: {format_money(house_val)}" + 
                             ("\n" + "\n".join([f"🏢 {n}: {format_money(v)}" for n, v in props]) if props else "") + 
                             f"\nSubtotal: **{format_money(prop_total + house_val)}**", inline=True)

        car_text = "\n".join([f"🚗 {n}: {format_money(v)}" for n, v in cars]) if cars else "No cars"
        embed.add_field(name="🚗 Cars", value=f"{car_text}\nSubtotal: **{format_money(car_total)}**", inline=True)
        embed.add_field(name="📋 Annual Contract", value=f"**{format_money(contract_annual)}**/year", inline=True)
        embed.add_field(name="📈 Wealth Rank", 
                       value=self._get_wealth_rank(grand_total), inline=True)

        await ctx.send(embed=embed)

    def _get_wealth_rank(self, amount):
        if amount >= 50_000_000: return "🌍 **Cricket Legend Billionaire**"
        if amount >= 10_000_000: return "👑 **Cricket Royalty**"
        if amount >= 5_000_000: return "💎 **Elite Cricketer**"
        if amount >= 1_000_000: return "⭐ **Star Player**"
        if amount >= 500_000: return "🏅 **Established Pro**"
        if amount >= 100_000: return "📈 **Rising Star**"
        return "🌱 **Rookie Budget**"

    # ==================================================
    # TRAINING & FITNESS
    # ==================================================

    @commands.command(name="train", aliases=["tr"], help="Train to improve your cricket skills")
    async def train_command(self, ctx):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)
        can, mins = cooldown_check(life["last_train"], 3)
        if not can:
            await ctx.send(f"⏳ You're too exhausted to train again. Come back in **{mins} minutes**.")
            return
        if life["energy"] < 20:
            await ctx.send("😴 Your energy is too low to train! Use `-rest` first.")
            return

        training_types = ["Batting drills 🏏", "Bowling practice 🎳", "Fielding drills 🧤", 
                         "Gym session 💪", "Video analysis 📹", "Mental coaching 🧠"]
        training = random.choice(training_types)
        conf_gain = random.randint(3, 8)
        fit_gain = random.randint(2, 6)
        energy_cost = random.randint(15, 25)
        cash_cost = random.randint(500, 2000)

        new_conf = min(100, life["confidence"] + conf_gain)
        new_fit = min(100, life["fitness"] + fit_gain)
        new_energy = max(0, life["energy"] - energy_cost)
        new_cash = max(0, life["cash"] - cash_cost)
        fan_gain = random.randint(50, 300)
        new_fans = life["fans"] + fan_gain

        update_life(ctx.author.id, confidence=new_conf, fitness=new_fit, energy=new_energy,
                    cash=new_cash, fans=new_fans, last_train=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))

        embed = discord.Embed(title=f"💪 Training Session Complete!", color=0x00FF00,
                              description=f"**{training}** — Another day, another grind.")
        embed.add_field(name="📈 Gains", value=f"+{conf_gain} Confidence\n+{fit_gain} Fitness\n+{fan_gain} Fans (training clip)", inline=True)
        embed.add_field(name="📉 Costs", value=f"-{energy_cost} Energy\n-{format_money(cash_cost)} (session fee)", inline=True)
        embed.add_field(name="📊 New Stats", value=f"Conf: {new_conf}/100\nFitness: {new_fit}/100\nEnergy: {new_energy}/100", inline=False)
        embed.set_footer(text="Cooldown: 3 hours | Low energy? Use -rest")
        await ctx.send(embed=embed)

    @commands.command(name="rest", aliases=["rs"], help="Rest to recover energy")
    async def rest_command(self, ctx):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)
        can, mins = cooldown_check(life["last_rest"], 6)
        if not can:
            await ctx.send(f"⏳ You've already rested recently. Next rest in **{mins} minutes**.")
            return

        energy_gain = random.randint(30, 50)
        happy_gain = random.randint(5, 15)
        new_energy = min(100, life["energy"] + energy_gain)
        new_happy = min(100, life["happiness"] + happy_gain)

        rest_types = ["Had an incredible 10-hour sleep 😴", "Netflix and chill session 🎬", 
                     "Meditation and yoga 🧘", "Spa day 🛁", "Beach day with the fam 🏖️"]
        rest_type = random.choice(rest_types)
        update_life(ctx.author.id, energy=new_energy, happiness=new_happy,
                    last_rest=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))

        embed = discord.Embed(title="😴 Rest Complete!", color=0x87CEEB, description=f"*{rest_type}*")
        embed.add_field(name="Recovery", value=f"+{energy_gain} Energy\n+{happy_gain} Happiness", inline=True)
        embed.add_field(name="Current", value=f"Energy: {new_energy}/100\nHappiness: {new_happy}/100", inline=True)
        embed.set_footer(text="Cooldown: 6 hours | Keep energy high to train!")
        await ctx.send(embed=embed)

    @commands.command(name="rehab", aliases=["rh"], help="Visit rehabilitation center to recover fitness")
    async def rehab_command(self, ctx):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)
        can, mins = cooldown_check(life["last_rehab"], 12)
        if not can:
            await ctx.send(f"⏳ You're still in your rehab programme. Check back in **{mins} minutes**.")
            return

        cost = random.randint(5000, 20000)
        if life["cash"] < cost:
            await ctx.send(f"❌ Rehab costs **{format_money(cost)}** but you only have **{format_money(life['cash'])}**. Take out a loan!")
            return

        fit_gain = random.randint(20, 40)
        new_fit = min(100, life["fitness"] + fit_gain)
        new_cash = life["cash"] - cost
        update_life(ctx.author.id, fitness=new_fit, cash=new_cash,
                    last_rehab=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))

        embed = discord.Embed(title="🏥 Rehabilitation Complete!", color=0x00FF99,
                              description="The physio team worked miracles. You're feeling stronger already.")
        embed.add_field(name="Recovery", value=f"+{fit_gain} Fitness\nNew Fitness: **{new_fit}/100**", inline=True)
        embed.add_field(name="Cost", value=f"-{format_money(cost)}", inline=True)
        embed.set_footer(text="Cooldown: 12 hours")
        await ctx.send(embed=embed)

    # ==================================================
    # RIVALS & TRASH TALK
    # ==================================================

    @commands.command(name="rival", aliases=["rv"], help="Declare a rival")
    async def rival_command(self, ctx, member: discord.Member = None):
        if not member:
            await ctx.send("❌ Tag a player to declare them your rival! Example: `-rival @Player`")
            return
        if member.id == ctx.author.id:
            await ctx.send("❌ You can't rival yourself! 😂")
            return

        ensure_life(ctx.author.id)
        ensure_life(member.id)

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("SELECT 1 FROM player_rivals WHERE user_id = ? AND rival_id = ?", (ctx.author.id, member.id))
        existing = c.fetchone()
        if existing:
            await ctx.send(f"⚠️ You've already declared **{member.display_name}** your rival!")
            conn.close()
            return

        c.execute("INSERT INTO player_rivals (user_id, rival_id) VALUES (?, ?)", (ctx.author.id, member.id))
        conn.commit()
        conn.close()

        my_name = get_player_name(ctx.author.id) or ctx.author.display_name
        their_name = get_player_name(member.id) or member.display_name
        update_life(ctx.author.id, confidence=min(100, get_life(ctx.author.id)["confidence"] + 5))

        quotes = [
            f"The cricket world just got more interesting.",
            f"One pitch isn't big enough for both of them.",
            f"The rivalry we never knew we needed.",
            f"Prepare for fireworks on and off the field.",
        ]

        embed = discord.Embed(
            title="⚔️ RIVALRY DECLARED!",
            description=f"**{my_name}** has officially declared **{their_name}** as their rival!\n\n*\"{random.choice(quotes)}\"*",
            color=0xFF4444
        )
        embed.add_field(name="⚔️ Challenge Accepted?", value=f"{member.mention} — the gauntlet has been thrown. Do you accept?", inline=False)
        embed.add_field(name="Bonus", value="+5 Confidence (nothing like a rivalry to fire you up!)", inline=False)
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="trashtalk", aliases=["tt"], help="Send trash talk to reduce opponent's confidence")
    async def trashtalk_command(self, ctx, member: discord.Member = None):
        if not member:
            await ctx.send("❌ Tag someone to trash talk! Example: `-trashtalk @Player`")
            return
        if member.id == ctx.author.id:
            await ctx.send("❌ Talking trash to yourself? Seek help 😭")
            return

        ensure_life(ctx.author.id)
        ensure_life(member.id)

        my_life = get_life(ctx.author.id)
        their_life = get_life(member.id)

        line = random.choice(TRASH_TALK_LINES)
        damage = random.randint(5, 15)
        own_conf_boost = random.randint(3, 8)

        new_their_conf = max(0, their_life["confidence"] - damage)
        new_my_conf = min(100, my_life["confidence"] + own_conf_boost)

        update_life(ctx.author.id, confidence=new_my_conf)
        update_life(member.id, confidence=new_their_conf)

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("INSERT INTO trash_talk_log (sender_id, target_id, message, confidence_damage) VALUES (?,?,?,?)",
                  (ctx.author.id, member.id, line, damage))
        conn.commit()
        conn.close()

        my_name = get_player_name(ctx.author.id) or ctx.author.display_name
        their_name = get_player_name(member.id) or member.display_name

        embed = discord.Embed(title="🔥 TRASH TALK DELIVERED!", color=0xFF6600)
        embed.add_field(name=f"💬 {my_name} said:", value=f'*"{line}"*', inline=False)
        embed.add_field(name="📉 Effect on Target", 
                       value=f"{their_name}'s Confidence: -{damage} (now **{new_their_conf}/100**)", inline=True)
        embed.add_field(name="📈 Effect on You",
                       value=f"Your Confidence: +{own_conf_boost} (now **{new_my_conf}/100**)", inline=True)

        if their_life["confidence"] < 30:
            embed.set_footer(text="🧠 Their confidence is dangerously low. They're rattled!")
        await ctx.send(embed=embed)

    @commands.command(name="rivals", help="View your rivals list")
    async def rivals_command(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("SELECT rival_id FROM player_rivals WHERE user_id = ?", (target.id,))
        rival_ids = [r[0] for r in c.fetchall()]
        conn.close()

        if not rival_ids:
            await ctx.send(f"{'You have' if target == ctx.author else f'{target.display_name} has'} no declared rivals. Use `-rival @user` to start one!")
            return

        embed = discord.Embed(title=f"⚔️ {target.display_name}'s Rivals", color=0xFF4444)
        for rid in rival_ids[:10]:
            rmember = ctx.guild.get_member(rid)
            rname = get_player_name(rid) or (rmember.display_name if rmember else f"User {rid}")
            rlife = get_life(rid)
            embed.add_field(name=rname, value=f"Rep: {rlife['reputation']} | Conf: {rlife['confidence']}" if rlife else "No data", inline=True)
        await ctx.send(embed=embed)

    # ==================================================
    # SOCIAL MEDIA
    # ==================================================

    @commands.command(name="feed", aliases=["cricketfeed", "cf"], help="Open the AI-powered CricketGram fan feed")
    async def feed_command(self, ctx, language: str = "all"):
        """Open the live AI-generated cricket fan feed.
        Usage: -feed | -feed english | -feed hinglish
        """
        lang = language.lower().strip()
        if lang not in ('all', 'english', 'hinglish', 'hindi'):
            lang = 'all'
        if lang == 'hindi':
            lang = 'hinglish'

        ensure_life(ctx.author.id)
        view = FeedView(ctx, initial_page=0, language_filter=lang, bot=self.bot)

        loading_embed = build_feed_embed([], 0, lang, is_loading=True)
        msg = await ctx.send(embed=loading_embed, view=view)

        try:
            posts, is_fallback = await get_feed_page(lang, 0, bot=self.bot)
            embed = build_feed_embed(posts, 0, lang, is_fallback=is_fallback)
        except Exception as e:
            embed = discord.Embed(
                title="📱 CricketGram Fan Feed",
                description=f"❌ Could not connect to AI: `{str(e)[:200]}`\n\nCheck your API key or try again!",
                color=0xFF0000
            )

        view._update_buttons()
        await msg.edit(embed=embed, view=view)

    @commands.command(name="genposttoday", aliases=["gpt", "generatefeed"], help="[ADMIN] Pre-generate CricketGram feed pages — 1 call every 10 mins")
    @commands.has_permissions(administrator=True)
    async def genposttoday(self, ctx, pages: int = 8):
        """
        Pre-generate all feed pages for today, one API call every 10 minutes.
        This completely avoids Gemini rate limits by spacing calls far apart.
        On 429, waits another 10 minutes then retries.

        Usage: -genposttoday       → 8 pages × 3 langs = 24 calls (~4 hours)
               -genposttoday 3    → 3 pages × 3 langs =  9 calls (~1.5 hours)
        """
        CALL_INTERVAL = 600       # 10 minutes between each call
        RATE_LIMIT_WAIT = 600     # 10 minutes extra wait on 429
        MAX_RETRIES = 3           # retries per page before giving up

        pages = max(1, min(pages, 15))
        langs = ['all', 'english', 'hinglish']
        today = datetime.utcnow().strftime('%Y-%m-%d')
        LANG_EMOJI = {'all': '🌐', 'english': '🇬🇧', 'hinglish': '🇮🇳'}

        # Build todo list — skip already cached
        todo = []
        for lang in langs:
            for page in range(pages):
                if not get_feed_from_cache(today, lang, page):
                    todo.append((lang, page))

        skipped_already = pages * len(langs) - len(todo)
        total = len(todo)

        print(f"[FEED GEN] Starting: date={today} | todo={total} | cached={skipped_already}")
        print(f"[FEED GEN] Queue: {todo}")
        print(f"[FEED GEN] Interval: {CALL_INTERVAL}s | Est total time: {total * CALL_INTERVAL // 60}min")

        if not todo:
            embed = discord.Embed(
                title="✅ Feed Already Generated",
                description=(
                    f"All **{pages} pages × {len(langs)} langs** are already cached for today!\n\n📅 Date: `{today}`\nUsers can open `-feed` instantly."
                ),
                color=0x00FF00
            )
            await ctx.send(embed=embed)
            return

        est_mins = total * CALL_INTERVAL // 60
        status_embed = discord.Embed(
            title="🤖 CricketGram Feed Generator",
            description=(
                f"Generating **{total}** page(s) — **1 call every 10 minutes**\n"
                f"*(Skipping {skipped_already} already cached)*\n\n"
                f"⏱️ Est. total time: **~{est_mins} minutes**\n"
                f"🛡️ Auto-waits **10 min** on rate limit\n\n"
                f"Progress: `0 / {total}`  `{'░' * 20}`"
            ),
            color=0xE1306C
        )
        status_embed.set_footer(text=f"📅 {today} | 10 min between calls | Keep bot running!")
        status_msg = await ctx.send(embed=status_embed)

        # Fetch player data and tournament context once
        player_data = get_feed_player_data(bot=self.bot)
        tourney_name, standings = get_tournament_context()
        if not player_data:
            simple_players = get_cricket_players()
            player_data = {p: {
                'discord': f'@{p.lower().split()[0]}fan', 'team': 'Unknown',
                'matches': 0, 'runs': 0, 'wickets': 0, 'strike_rate': 0.0,
                'economy': 0.0, 'average': 0.0, 'highest': 0,
                'best_bowling': '0/0', 'centuries': 0, 'fifties': 0, 'impact': 0
            } for p in simple_players}

        print(f"[FEED GEN] Players loaded: {len(player_data)} | Tournament: {tourney_name or 'None'}")

        done = 0
        failed = []

        async def _update_status(lang, page, msg_override=None):
            pct = done / total
            filled = int(pct * 20)
            bar = '█' * filled + '░' * (20 - filled)
            lang_e = LANG_EMOJI.get(lang, '🌐')
            action = f"⏳ **{msg_override}**" if msg_override else f"**Generating:** {lang_e} `{lang}` — Page {page + 1}"
            desc = (
                f"{action}\n\n"
                f"Progress: `{done} / {total}`\n"
                f"`{bar}` {int(pct * 100)}%\n\n"
                f"✅ Done: **{done}**  |  ⏭️ Cached: **{skipped_already}**  |  ❌ Failed: **{len(failed)}**"
            )
            emb = discord.Embed(title="🤖 CricketGram Feed Generator", description=desc, color=0xE1306C)
            emb.set_footer(text=f"📅 {today} | 1 call per 10 min | Est. {((total - done) * CALL_INTERVAL) // 60}min remaining")
            try:
                await status_msg.edit(embed=emb)
            except Exception:
                pass

        for i, (lang, page) in enumerate(todo):
            lang_e = LANG_EMOJI.get(lang, '🌐')
            print(f"[FEED GEN] --- [{i+1}/{total}] lang={lang} page={page+1} ---")
            await _update_status(lang, page)

            prompt = build_feed_prompt(player_data, lang, page, tourney_name, standings)
            success = False

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    print(f"[FEED GEN] → Calling Gemini (attempt {attempt}/{MAX_RETRIES})...")
                    raw = await call_gemini(prompt)
                    raw = raw.strip()
                    if raw.startswith('```'):
                        parts = raw.split('```')
                        raw = parts[1] if len(parts) > 1 else raw
                        if raw.startswith('json'):
                            raw = raw[4:]
                    raw = raw.strip()
                    posts = json.loads(raw)
                    save_feed_to_cache(today, lang, page, posts)
                    done += 1
                    success = True
                    print(f"[FEED GEN] ✅ Success: lang={lang} page={page+1} | {len(posts)} posts saved | done={done}/{total}")
                    break

                except RuntimeError as e:
                    if 'RATE_LIMITED' in str(e):
                        print(f"[FEED GEN] ❌ 429 on lang={lang} page={page+1} attempt={attempt} — waiting {RATE_LIMIT_WAIT}s")
                        # Countdown in 60s chunks
                        remaining = RATE_LIMIT_WAIT
                        while remaining > 0:
                            wait_chunk = min(60, remaining)
                            mins_left = remaining // 60
                            secs_left = remaining % 60
                            await _update_status(lang, page,
                                f"Rate limited! Waiting {mins_left}m {secs_left:02d}s before retry {attempt}/{MAX_RETRIES}")
                            print(f"[FEED GEN]    ⏳ {remaining}s remaining...")
                            await asyncio.sleep(wait_chunk)
                            remaining -= wait_chunk
                        print(f"[FEED GEN]    🔄 Retrying after 429 wait...")
                    else:
                        print(f"[FEED GEN] ❌ API error: {str(e)[:100]}")
                        failed.append(f"{lang_e} `{lang}` p{page+1}: {str(e)[:60]}")
                        break

                except Exception as e:
                    print(f"[FEED GEN] ❌ Unexpected error: {str(e)[:100]}")
                    failed.append(f"{lang_e} `{lang}` p{page+1}: {str(e)[:60]}")
                    break

            if not success and not any(f"`{lang}` p{page+1}" in f for f in failed):
                print(f"[FEED GEN] 💀 Gave up on lang={lang} page={page+1} after {MAX_RETRIES} attempts")
                failed.append(f"{lang_e} `{lang}` p{page+1}: failed after {MAX_RETRIES} attempts")

            # Wait 10 minutes before next call (skip after last item)
            if i < total - 1:
                print(f"[FEED GEN] Sleeping {CALL_INTERVAL}s (10 min) before next call...")
                remaining = CALL_INTERVAL
                while remaining > 0:
                    wait_chunk = min(60, remaining)
                    mins_left = remaining // 60
                    secs_left = remaining % 60
                    await _update_status(lang, page,
                        f"✅ Done! Next call in {mins_left}m {secs_left:02d}s ({i+2}/{total})")
                    await asyncio.sleep(wait_chunk)
                    remaining -= wait_chunk

        # Final summary
        total_cached = done + skipped_already
        total_possible = pages * len(langs)
        print(f"[FEED GEN] === COMPLETE === generated={done} | cached={skipped_already} | failed={len(failed)} | coverage={total_cached}/{total_possible}")
        if failed:
            print(f"[FEED GEN] Failed: {failed}")

        if failed:
            fail_list = "\n".join(f"• {f}" for f in failed[:10])
            final_color = 0xFF8C00 if done > 0 else 0xFF0000
            final_desc = (
                f"**{done}/{total}** generated  |  **{skipped_already}** cached  |  **{len(failed)}** failed\n\n"
                f"**Cache coverage:** `{total_cached}/{total_possible}` pages ready\n\n"
                f"**Failed:**\n{fail_list}\n\n"
                f"{'✅ `-feed` works for cached pages.' if total_cached > 0 else '❌ No pages available.'}"
            )
        else:
            final_color = 0x00FF00
            final_desc = (
                f"**{done}** new page(s) generated  +  **{skipped_already}** already cached\n\n"
                f"**Total ready:** `{total_cached}/{total_possible}` pages across all languages\n\n"
                f"✅ Users can open `-feed` instantly — no rate limit errors!"
            )

        final_embed = discord.Embed(
            title="✅ Feed Generation Complete" if not failed else "⚠️ Feed Generation Done (with errors)",
            description=final_desc,
            color=final_color
        )
        final_embed.add_field(
            name="📋 Coverage",
            value=f"🌐 All · 🇬🇧 English · 🇮🇳 Hinglish\nPages 1–{pages} each",
            inline=True
        )
        final_embed.add_field(
            name="📅 Cache",
            value=f"`{today}` UTC\nExpires midnight UTC",
            inline=True
        )
        final_embed.set_footer(text="Run -genposttoday again tomorrow for fresh posts")
        await status_msg.edit(embed=final_embed)
    @commands.command(name="cleartodayfeed", aliases=["ctf"], help="[ADMIN] Clear today's cached feed so it regenerates fresh")
    @commands.has_permissions(administrator=True)
    async def cleartodayfeed(self, ctx):
        """Wipe today's feed cache so -genposttoday can start fresh."""
        today = datetime.utcnow().strftime('%Y-%m-%d')
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        try:
            c.execute("DELETE FROM ai_feed_cache WHERE cache_date = ?", (today,))
            deleted = c.rowcount
            conn.commit()
        except Exception as e:
            conn.close()
            await ctx.send(f"❌ Failed to clear cache: {e}")
            return
        conn.close()

        embed = discord.Embed(
            title="🗑️ Today's Feed Cache Cleared",
            description=f"Deleted **{deleted}** cached page(s) for `{today}`.\n\n"
                        f"Run `-genposttoday` to pre-generate a fresh batch.",
            color=0xFF6B6B
        )
        await ctx.send(embed=embed)

    @commands.command(name="socialmedia", aliases=["sm"], help="Access your social media account")
    async def socialmedia_command(self, ctx):
        ensure_life(ctx.author.id)
        social = get_social(ctx.author.id)
        life = get_life(ctx.author.id)
        player_name = get_player_name(ctx.author.id) or ctx.author.display_name

        verified_badge = "✅" if social["verification_status"] else ""
        follower_tier = self._follower_tier(social["followers"])

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("SELECT post_type, likes, went_viral, posted_at FROM social_posts WHERE user_id = ? ORDER BY posted_at DESC LIMIT 5", (ctx.author.id,))
        recent_posts = c.fetchall()
        conn.close()

        embed = discord.Embed(
            title=f"📱 {player_name}'s CricketGram {verified_badge}",
            description=f"*{social['bio'] or 'No bio yet. Use -setbio to add one!'}*",
            color=0xE1306C
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)

        embed.add_field(name="📊 Account Stats",
                       value=f"👥 **{social['followers']:,}** Followers\n"
                             f"📸 **{social['posts']}** Posts\n"
                             f"🔥 **{social['viral_posts']}** Viral Posts\n"
                             f"❤️ **{social['total_likes']:,}** Total Likes",
                       inline=True)
        embed.add_field(name="🏆 Account Status",
                       value=f"Tier: **{follower_tier}**\n"
                             f"{'✅ Verified Account' if social['verification_status'] else '⬜ Not Verified'}\n"
                             f"Engagement Rate: **{self._calc_engagement(social):.1f}%**",
                       inline=True)
        embed.add_field(name="💡 Growth Tips",
                       value=self._growth_tips(social, life),
                       inline=False)

        if recent_posts:
            post_text = ""
            for pt, lk, viral, ts in recent_posts:
                vmark = " 🔥 VIRAL" if viral else ""
                post_text += f"• [{POST_TYPES.get(pt, {}).get('name', pt)}] {lk:,} likes{vmark}\n"
            embed.add_field(name="📸 Recent Posts", value=post_text, inline=False)

        embed.set_footer(text="Use -post to share content | -setbio to update bio | -verify to get verified")
        await ctx.send(embed=embed)

    def _follower_tier(self, followers):
        if followers >= 10_000_000: return "🌍 Global Icon"
        if followers >= 1_000_000: return "💫 Celebrity"
        if followers >= 500_000: return "⭐ Influencer"
        if followers >= 100_000: return "🔥 Creator"
        if followers >= 10_000: return "📈 Rising"
        return "🌱 Newcomer"

    def _calc_engagement(self, social):
        if not social["posts"] or not social["followers"]: return 0
        avg_likes = social["total_likes"] / max(social["posts"], 1)
        return min(99.9, (avg_likes / max(social["followers"], 1)) * 100)

    def _growth_tips(self, social, life):
        tips = []
        if social["followers"] < 10000: tips.append("📌 Post daily to grow faster!")
        if social["viral_posts"] == 0: tips.append("💣 Try controversy bait to go viral")
        if life["reputation"] < 50: tips.append("🙏 Post an apology to recover rep")
        if not tips: tips.append("🚀 You're doing great! Keep posting!")
        return "\n".join(tips)

    @commands.command(name="post", aliases=["p"], help="Post content on social media")
    async def post_command(self, ctx):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)
        can, mins = cooldown_check(life["last_social"], 1)
        if not can:
            await ctx.send(f"⏳ You just posted! Wait **{mins} more minutes** before your next post.")
            return

        embed = discord.Embed(title="📱 What do you want to post?", 
                              description="Choose your content type for CricketGram:", color=0xE1306C)
        for key, data in POST_TYPES.items():
            embed.add_field(name=data["name"], value=f"Fans: +{data['followers_gain'][0]}-{data['followers_gain'][1]}", inline=True)

        view = SocialPostTypeView(ctx, self)
        await ctx.send(embed=embed, view=view)

    async def _do_post(self, interaction, post_key):
        user_id = interaction.user.id
        ensure_life(user_id)
        life = get_life(user_id)
        social = get_social(user_id)
        post_data = POST_TYPES[post_key]
        template = random.choice(post_data["templates"])

        # Calculate performance
        base_min, base_max = post_data["base_likes"]
        likes = random.randint(base_min, base_max)

        # Boost by follower count
        follower_boost = social["followers"] / 10000
        likes = int(likes * (1 + follower_boost * 0.1))

        fan_min, fan_max = post_data["followers_gain"]
        fan_gain = random.randint(fan_min, fan_max)

        # Viral check
        went_viral = random.random() < 0.08  # 8% chance
        if went_viral:
            likes *= random.randint(5, 20)
            fan_gain *= random.randint(5, 15)

        # Update social
        new_followers = social["followers"] + fan_gain
        new_posts = social["posts"] + 1
        new_viral = social["viral_posts"] + (1 if went_viral else 0)
        new_total_likes = social["total_likes"] + likes

        update_social(user_id, followers=new_followers, posts=new_posts, viral_posts=new_viral,
                      total_likes=new_total_likes, last_post=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))

        # Update life stats
        new_rep = max(0, min(100, life["reputation"] + post_data["rep_change"]))
        new_conf = max(0, min(100, life["confidence"] + post_data["conf_change"]))
        new_fans = life["fans"] + fan_gain
        update_life(user_id, reputation=new_rep, confidence=new_conf, fans=new_fans,
                    last_social=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))

        # Save post
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("INSERT INTO social_posts (user_id, post_type, content, likes, went_viral) VALUES (?,?,?,?,?)",
                  (user_id, post_key, template, likes, 1 if went_viral else 0))
        conn.commit()
        conn.close()

        color = 0xFF6600 if went_viral else 0xE1306C
        embed = discord.Embed(
            title=f"{'🔥 VIRAL POST!!! 🔥' if went_viral else '📸 Post Published!'}",
            description=f'*"{template}"*',
            color=color
        )
        if went_viral:
            embed.description += "\n\n**🚨 YOUR POST WENT VIRAL! THE INTERNET IS TALKING!**"

        embed.add_field(name="📊 Performance", 
                       value=f"❤️ {likes:,} likes\n👥 +{fan_gain:,} followers\n📱 {new_followers:,} total", inline=True)
        embed.add_field(name="📈 Impact",
                       value=f"Rep: {post_data['rep_change']:+d}\nConf: {post_data['conf_change']:+d}", inline=True)

        player_name = get_player_name(user_id) or interaction.user.display_name
        embed.set_author(name=f"{player_name} on CricketGram", icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"Total Followers: {new_followers:,} | Total Posts: {new_posts}")
        await interaction.channel.send(embed=embed)

    @commands.command(name="setbio", help="Set your social media bio")
    async def setbio_command(self, ctx, *, bio: str):
        ensure_life(ctx.author.id)
        if len(bio) > 150:
            await ctx.send("❌ Bio must be under 150 characters!")
            return
        update_social(ctx.author.id, bio=bio)
        await ctx.send(f"✅ Bio updated: *\"{bio}\"*")

    @commands.command(name="verify", help="Apply for social media verification (costs reputation)")
    async def verify_command(self, ctx):
        ensure_life(ctx.author.id)
        social = get_social(ctx.author.id)
        life = get_life(ctx.author.id)

        if social["verification_status"]:
            await ctx.send("✅ You're already verified!")
            return
        if social["followers"] < 50000:
            await ctx.send(f"❌ You need at least **50,000 followers** to apply for verification. You have **{social['followers']:,}**.")
            return
        if life["reputation"] < 60:
            await ctx.send(f"❌ Your reputation is too low ({life['reputation']}/100). Need at least **60** to be verified.")
            return

        update_social(ctx.author.id, verification_status=1)
        await ctx.send(f"🎉 **Congratulations!** Your CricketGram account is now **✅ Verified!** Your rep and follower count did the talking!")

    # ==================================================
    # FANS
    # ==================================================

    @commands.command(name="fans", help="View your fanbase details")
    async def fans_command(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        ensure_life(target.id)
        life = get_life(target.id)
        social = get_social(target.id)
        player_name = get_player_name(target.id) or target.display_name

        fan_tier = self._fan_tier(life["fans"])
        loyalty_desc = "🔥 Die-hard loyal" if life["fan_loyalty"] > 75 else "😊 Generally supportive" if life["fan_loyalty"] > 50 else "😐 Casual" if life["fan_loyalty"] > 25 else "😤 Ready to turn on you"

        embed = discord.Embed(
            title=f"👥 {player_name}'s Fanbase",
            description=f"**{life['fans']:,}** fans worldwide — Tier: **{fan_tier}**",
            color=0xFF69B4
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="📊 Fan Stats",
                       value=f"Total Fans: **{life['fans']:,}**\nFan Loyalty: **{life['fan_loyalty']}/100** — {loyalty_desc}\nSocial Followers: **{social['followers']:,}**",
                       inline=True)
        embed.add_field(name="🏆 Fan Milestones",
                       value=self._fan_milestones(life["fans"]),
                       inline=True)
        embed.add_field(name="💡 Fan Growth",
                       value="Train regularly 💪\nPost on social media 📱\nWin matches 🏆\nDo press conferences 🎤",
                       inline=False)
        embed.set_footer(text="Fans affect sponsor deals, reputation, and more!")
        await ctx.send(embed=embed)

    def _fan_tier(self, fans):
        if fans >= 5_000_000: return "🌍 Global Superstar"
        if fans >= 1_000_000: return "🌟 International Icon"
        if fans >= 500_000: return "⭐ National Celebrity"
        if fans >= 100_000: return "🔥 Fan Favourite"
        if fans >= 10_000: return "📈 Growing Star"
        return "🌱 Local Hero"

    def _fan_milestones(self, fans):
        milestones = [(10000, "10K ✅"), (50000, "50K"), (100000, "100K"), 
                      (500000, "500K"), (1000000, "1M"), (5000000, "5M")]
        text = ""
        for target, label in milestones:
            check = "✅" if fans >= target else f"({fans/target*100:.0f}%)"
            text += f"{label} {check}\n"
        return text

    # ==================================================
    # SCANDAL
    # ==================================================

    @commands.command(name="scandal", aliases=["sc2"], help="Roll for a random scandal event")
    async def scandal_command(self, ctx):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)
        can, mins = cooldown_check(life["last_scandal"], 12)
        if not can:
            await ctx.send(f"⏳ The media has forgotten your last scandal. Wait **{mins} more minutes** before stirring things up again.")
            return

        player_name = get_player_name(ctx.author.id) or ctx.author.display_name

        # 70% chance of scandal, 30% chance of positive event
        if random.random() < 0.70:
            event = random.choice(SCANDAL_EVENTS)
            is_negative = True
        else:
            event = random.choice(POSITIVE_EVENTS)
            is_negative = False
            if "{}" in event["text"]:
                donation = random.randint(5, 50) * 1000
                event = {**event, "text": event["text"].format(format_money(donation)), "cash": -donation}

        new_rep = max(0, min(100, life["reputation"] + event["rep"]))
        new_fans = max(0, life["fans"] + event["fans"])
        new_cash = max(0, life["cash"] + (event.get("cash", 0)))
        new_conf = max(0, min(100, life["confidence"] + event.get("conf", 0)))
        update_life(ctx.author.id, reputation=new_rep, fans=new_fans, cash=new_cash, confidence=new_conf,
                    last_scandal=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))

        color = 0xFF0000 if is_negative else 0x00FF00
        headline_starters = ["BREAKING:", "EXCLUSIVE:", "SOURCES SAY:", "CRICKET WORLD SHOCKED:"]
        embed = discord.Embed(
            title=f"📰 {random.choice(headline_starters)}",
            description=f"**{player_name}** {event['text']}",
            color=color
        )
        changes = []
        if event["rep"] != 0: changes.append(f"Reputation: {event['rep']:+d} → **{new_rep}**")
        if event["fans"] != 0: changes.append(f"Fans: {event['fans']:+,} → **{new_fans:,}**")
        if event.get("cash", 0) != 0: changes.append(f"Cash: {format_money(event['cash'])}")
        if event.get("conf", 0) != 0: changes.append(f"Confidence: {event['conf']:+d}")
        embed.add_field(name="📊 Impact", value="\n".join(changes) if changes else "No major impact", inline=False)

        if is_negative and new_rep < 30:
            embed.set_footer(text="⚠️ Your reputation is critically low! Use -press to do damage control.")
        else:
            embed.set_footer(text="Cooldown: 12 hours")
        await ctx.send(embed=embed)

    # ==================================================
    # PRESS CONFERENCE
    # ==================================================

    @commands.command(name="press", aliases=["pc"], help="Attend a press conference")
    async def press_command(self, ctx):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)
        can, mins = cooldown_check(life["last_press"], 6)
        if not can:
            await ctx.send(f"⏳ You just faced the press. Give it **{mins} more minutes** before the next one.")
            return

        question = random.choice(PRESS_QUESTIONS)
        embed = discord.Embed(
            title="🎤 PRESS CONFERENCE",
            description=f"**Journalist:** *\"{question['question']}\"*\n\n**Choose your response:**",
            color=0x1E90FF
        )
        view = PressConferenceView(ctx, question)
        await ctx.send(embed=embed, view=view)

    # ==================================================
    # CARS & PROPERTIES
    # ==================================================

    @commands.command(name="showroom", aliases=["cars"], help="View the car showroom")
    async def showroom_command(self, ctx):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)

        embed = discord.Embed(title="🚗 Cricket Star Car Showroom", 
                              description=f"Your balance: **{format_money(life['cash'])}**", color=0xFFD700)
        for car_id, car in CARS.items():
            can_afford = "✅" if life["cash"] >= car["price"] else "❌"
            embed.add_field(
                name=f"{car['emoji']} {car['name']} {can_afford}",
                value=f"Price: **{format_money(car['price'])}**\nPrestige: {'⭐' * min(5, car['prestige'] // 20) or '☆'}",
                inline=True
            )
        embed.set_footer(text="Use -buycar <name> to purchase • e.g. -buycar bmw m3")
        await ctx.send(embed=embed)

    @commands.command(name="buycar", aliases=["bc"], help="Buy a car")
    async def buycar_command(self, ctx, *, car_name: str):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)

        # Find car by partial name match
        found_id = None
        for car_id, car in CARS.items():
            if car_name.lower() in car["name"].lower() or car_name.lower() == car_id:
                found_id = car_id
                break

        if not found_id:
            await ctx.send(f"❌ Car '{car_name}' not found! Use `-showroom` to see available cars.")
            return

        car = CARS[found_id]
        if life["cash"] < car["price"]:
            await ctx.send(f"❌ You can't afford a **{car['name']}**! You need {format_money(car['price'])} but have {format_money(life['cash'])}.")
            return

        new_cash = life["cash"] - car["price"]
        update_life(ctx.author.id, cash=new_cash, car_id=found_id)

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("INSERT INTO player_cars (user_id, car_name, car_value) VALUES (?,?,?)",
                  (ctx.author.id, car["name"], car["price"]))
        conn.commit()
        conn.close()

        fan_boost = car["prestige"] * 100
        new_fans = life["fans"] + fan_boost
        update_life(ctx.author.id, fans=new_fans, cash=new_cash)

        embed = discord.Embed(title=f"{car['emoji']} NEW CAR UNLOCKED!", color=0xFFD700,
                              description=f"**{ctx.author.display_name}** just pulled up in a brand new **{car['name']}**!")
        embed.add_field(name="💸 Transaction", value=f"-{format_money(car['price'])}\nRemaining: {format_money(new_cash)}", inline=True)
        embed.add_field(name="📈 Clout Boost", value=f"+{fan_boost:,} fans\nPrestige: {'⭐' * min(5, car['prestige'] // 20)}", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="mycars", help="View your car collection")
    async def mycars_command(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("SELECT car_name, car_value, purchased_at FROM player_cars WHERE user_id = ? ORDER BY car_value DESC", (target.id,))
        cars = c.fetchall()
        conn.close()

        if not cars:
            await ctx.send(f"{'You have' if target == ctx.author else f'{target.display_name} has'} no cars! Use `-showroom` to buy one.")
            return

        total = sum(v for _, v, _ in cars)
        embed = discord.Embed(title=f"🚗 {target.display_name}'s Garage", 
                              description=f"**{len(cars)} cars** worth **{format_money(total)}** total", color=0xFFD700)
        for name, val, _ in cars:
            car_emoji = next((c["emoji"] for c in CARS.values() if c["name"] == name), "🚗")
            embed.add_field(name=f"{car_emoji} {name}", value=f"Value: {format_money(val)}", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="buyhouse", aliases=["bh"], help="Upgrade your house")
    async def buyhouse_command(self, ctx):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)
        current = life["house_level"]
        if current >= len(HOUSES) - 1:
            await ctx.send("🏯 You already own a **Private Island Estate** — the pinnacle of cricket wealth!")
            return

        next_house = HOUSES[current + 1]
        if life["cash"] < next_house["price"]:
            await ctx.send(f"❌ You need **{format_money(next_house['price'])}** for a {next_house['name']}. You only have {format_money(life['cash'])}.")
            return

        new_cash = life["cash"] - next_house["price"]
        new_fans = life["fans"] + next_house["price"] // 10
        update_life(ctx.author.id, house_level=current + 1, cash=new_cash, fans=new_fans)

        embed = discord.Embed(title=f"{next_house['emoji']} NEW HOME!", color=0x00FF00,
                              description=f"You just moved into a **{next_house['name']}** worth **{format_money(next_house['value'])}**!")
        embed.add_field(name="💸 Cost", value=format_money(next_house["price"]), inline=True)
        embed.add_field(name="📈 Property Value", value=format_money(next_house["value"]), inline=True)
        embed.add_field(name="👥 Fan Boost", value=f"+{next_house['price']//10:,} fans", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="myhouse", help="View your current property")
    async def myhouse_command(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        ensure_life(target.id)
        life = get_life(target.id)
        house = HOUSES[min(life["house_level"], len(HOUSES)-1)]
        player_name = get_player_name(target.id) or target.display_name

        embed = discord.Embed(title=f"🏠 {player_name}'s Home", color=0x00FF99)
        embed.add_field(name="Current Residence", value=f"{house['emoji']} **{house['name']}**\nEstimated Value: **{format_money(house['value'])}**", inline=False)
        if life["house_level"] < len(HOUSES) - 1:
            next_h = HOUSES[life["house_level"] + 1]
            embed.add_field(name="⬆️ Next Upgrade", value=f"{next_h['emoji']} {next_h['name']}\nCost: **{format_money(next_h['price'])}**", inline=False)
        await ctx.send(embed=embed)

    # ==================================================
    # SPONSORS
    # ==================================================

    @commands.command(name="getsponsor", aliases=["gs"], help="Get a sponsorship deal based on your fans")
    async def getsponsor_command(self, ctx):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)

        available = [s for s in SPONSORS if life["fans"] >= s["min_fans"]]
        if not available:
            await ctx.send(f"❌ You need more fans to attract sponsors! Current: **{life['fans']:,}** | Min required: **{SPONSORS[0]['min_fans']:,}**")
            return

        best = available[-1]  # Get the best available sponsor
        if life["sponsor_tier"] >= best["tier"]:
            current = next((s for s in SPONSORS if s["tier"] == life["sponsor_tier"]), None)
            await ctx.send(f"✅ You already have the best sponsor available: **{life['sponsor_name']}** ({format_money(current['monthly'])}/month)!\nGrow your fans for better deals!")
            return

        update_life(ctx.author.id, sponsor_tier=best["tier"], sponsor_name=f"{best['emoji']} {best['name']}",
                    contract_value=best["monthly"])

        embed = discord.Embed(title="🤝 SPONSORSHIP DEAL SIGNED!", color=0x00FF00,
                              description=f"**{best['emoji']} {best['name']}** wants YOU as their brand ambassador!")
        embed.add_field(name="💰 Monthly Earnings", value=f"**{format_money(best['monthly'])}/month**", inline=True)
        embed.add_field(name="📋 Annual Value", value=f"**{format_money(best['monthly'] * 12)}/year**", inline=True)
        embed.set_footer(text="Collect your monthly earnings with -collect | Grow fans for better deals!")
        await ctx.send(embed=embed)

    @commands.command(name="collect", aliases=["cl"], help="Collect your monthly sponsor earnings")
    async def collect_command(self, ctx):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)

        if not life["sponsor_name"] or life["contract_value"] == 0:
            await ctx.send("❌ You don't have a sponsor yet! Use `-getsponsor` to get one.")
            return

        earnings = life["contract_value"]
        new_cash = life["cash"] + earnings
        # Use last_press timestamp as collect tracker (using existing column)
        update_life(ctx.author.id, cash=new_cash)

        embed = discord.Embed(title="💵 Sponsor Payment Received!", color=0x00FF00,
                              description=f"**{life['sponsor_name']}** deposited your monthly payment!")
        embed.add_field(name="Amount", value=f"**{format_money(earnings)}**", inline=True)
        embed.add_field(name="New Balance", value=f"**{format_money(new_cash)}**", inline=True)
        await ctx.send(embed=embed)

    # ==================================================
    # LOCKER ROOM
    # ==================================================

    @commands.command(name="lockerroom", aliases=["lr"], help="Send a private locker room message to a teammate")
    async def lockerroom_command(self, ctx, member: discord.Member = None, *, message: str = None):
        if not member:
            # Show recent locker room activity
            conn = sqlite3.connect('players.db')
            c = conn.cursor()
            c.execute("SELECT sender_id, target_id, message, sent_at FROM locker_room WHERE target_id = ? ORDER BY sent_at DESC LIMIT 5", (ctx.author.id,))
            messages = c.fetchall()
            conn.close()

            embed = discord.Embed(title="🔒 Locker Room Inbox", color=0x4B0082)
            if messages:
                for sid, tid, msg, ts in messages:
                    sender = ctx.guild.get_member(sid)
                    sname = get_player_name(sid) or (sender.display_name if sender else "Someone")
                    embed.add_field(name=f"From {sname}", value=f"*\"{msg}\"*", inline=False)
            else:
                embed.description = "No messages yet. What happens in the locker room stays here 🤫"
            embed.set_footer(text="Use -lockerroom @player <message> to send one")
            await ctx.send(embed=embed, ephemeral=False)
            return

        if not message:
            message = random.choice(LOCKER_ROOM_MESSAGES)

        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("INSERT INTO locker_room (user_id, target_id, message, sentiment) VALUES (?,?,?,?)",
                  (ctx.author.id, member.id, message, "neutral"))
        conn.commit()
        conn.close()

        my_name = get_player_name(ctx.author.id) or ctx.author.display_name
        embed = discord.Embed(title="🔒 Locker Room Message Sent", color=0x4B0082,
                              description=f"*\"{message}\"*")
        embed.set_author(name=f"Private DM from {my_name}", icon_url=ctx.author.display_avatar.url)
        embed.set_footer(text="🤫 What happens in the locker room stays here")
        await ctx.send(embed=embed)

        # Try to DM the target
        try:
            dm_embed = discord.Embed(title="🔒 You got a Locker Room Message!", color=0x4B0082,
                                     description=f"*\"{message}\"*")
            dm_embed.set_footer(text=f"From: {my_name} • CricketGram Locker Room")
            await member.send(embed=dm_embed)
        except:
            pass

    # ==================================================
    # RELATIONSHIPS
    # ==================================================

    @commands.command(name="relationship", aliases=["rel"], help="Manage your relationship status")
    async def relationship_command(self, ctx, *, partner_name: str = None):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)

        if not partner_name:
            embed = discord.Embed(title="💑 Relationship Status", color=0xFF69B4)
            ms_emoji = {"Single": "🧍", "In a Relationship": "💑", "Engaged": "💍", "Married": "💒",
                        "It's Complicated": "🤷", "Divorced": "💔"}.get(life["marital_status"], "🧍")
            embed.add_field(name="Status", value=f"{ms_emoji} **{life['marital_status']}**", inline=False)
            if life["partner_name"]:
                embed.add_field(name="Partner", value=life["partner_name"], inline=False)
            embed.add_field(name="💡 Options", value="-relationship <name> to start dating\n-propose to get engaged\n-marry to tie the knot\n-breakup to end things", inline=False)
            await ctx.send(embed=embed)
            return

        if life["marital_status"] != "Single":
            await ctx.send(f"❌ You're already **{life['marital_status']}**! You can't start dating someone else. Drama! 👀")
            return

        update_life(ctx.author.id, marital_status="In a Relationship", partner_name=partner_name,
                    happiness=min(100, life["happiness"] + 15))
        await ctx.send(f"💑 **{ctx.author.display_name}** is now **In a Relationship** with **{partner_name}**! +15 Happiness 🥰")

    @commands.command(name="propose", help="Get engaged to your partner")
    async def propose_command(self, ctx):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)
        if life["marital_status"] != "In a Relationship":
            await ctx.send("❌ You need to be in a relationship first! Use `-relationship <name>`")
            return
        if life["cash"] < 50000:
            await ctx.send("💍 A ring costs **$50,000**! You don't have enough. Save up first!")
            return
        update_life(ctx.author.id, marital_status="Engaged", cash=life["cash"] - 50000, happiness=min(100, life["happiness"] + 20))
        await ctx.send(f"💍 **{ctx.author.display_name}** PROPOSED to **{life['partner_name']}**! They said YES! 🎉 -$50,000 for the ring | +20 Happiness")

    @commands.command(name="marry", help="Get married to your partner")
    async def marry_command(self, ctx):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)
        if life["marital_status"] != "Engaged":
            await ctx.send("❌ You need to be engaged first! Use `-propose`")
            return
        if life["cash"] < 100000:
            await ctx.send("💒 A wedding costs **$100,000**! Save up first!")
            return
        update_life(ctx.author.id, marital_status="Married", cash=life["cash"] - 100000, 
                    happiness=min(100, life["happiness"] + 25), fan_loyalty=min(100, life["fan_loyalty"] + 10))
        await ctx.send(f"💒 **{ctx.author.display_name}** and **{life['partner_name']}** are now **MARRIED!** 🎊\n-$100,000 | +25 Happiness | +10 Fan Loyalty")

    @commands.command(name="breakup", help="End your relationship")
    async def breakup_command(self, ctx):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)
        if life["marital_status"] == "Single":
            await ctx.send("❌ You're already single! 💀")
            return
        old_status = life["marital_status"]
        old_partner = life["partner_name"]
        new_status = "Divorced" if old_status == "Married" else "Single"
        update_life(ctx.author.id, marital_status=new_status, partner_name=None,
                    happiness=max(0, life["happiness"] - 20), reputation=max(0, life["reputation"] - 5))
        embed = discord.Embed(title="💔 Relationship Over", color=0xFF0000,
                              description=f"**{ctx.author.display_name}** and **{old_partner}** have gone their separate ways.\n*-20 Happiness | -5 Reputation*")
        if old_status == "Married":
            embed.add_field(name="⚠️ Divorce Settlement", value="The lawyers are expensive. -$75,000", inline=False)
            update_life(ctx.author.id, cash=max(0, life["cash"] - 75000))
        await ctx.send(embed=embed)

    # ==================================================
    # MONEY COMMANDS
    # ==================================================

    @commands.command(name="balance", aliases=["bal"], help="Check your wallet and bank balance")
    async def balance_command(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        ensure_life(target.id)
        life = get_life(target.id)
        embed = discord.Embed(title=f"💰 {target.display_name}'s Finances", color=0x00FF00)
        embed.add_field(name="👛 Wallet", value=f"**{format_money(life['cash'])}**", inline=True)
        embed.add_field(name="🏦 Bank", value=f"**{format_money(life['bank'])}**", inline=True)
        embed.add_field(name="💳 Total", value=f"**{format_money(life['cash'] + life['bank'])}**", inline=True)
        if life["contract_value"]:
            embed.add_field(name="📋 Monthly Income", value=f"**{format_money(life['contract_value'])}/mo**", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="deposit", aliases=["dep"], help="Deposit money into your bank")
    async def deposit_command(self, ctx, amount: str):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)
        if amount.lower() == "all":
            amount = life["cash"]
        else:
            try:
                amount = int(amount.replace(",", "").replace("$", ""))
            except:
                await ctx.send("❌ Invalid amount!")
                return
        if amount <= 0 or amount > life["cash"]:
            await ctx.send(f"❌ Invalid amount. You have **{format_money(life['cash'])}** in wallet.")
            return
        update_life(ctx.author.id, cash=life["cash"] - amount, bank=life["bank"] + amount)
        await ctx.send(f"🏦 Deposited **{format_money(amount)}** → Bank balance: **{format_money(life['bank'] + amount)}**")

    @commands.command(name="withdraw", aliases=["wd"], help="Withdraw money from your bank")
    async def withdraw_command(self, ctx, amount: str):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)
        if amount.lower() == "all":
            amount = life["bank"]
        else:
            try:
                amount = int(amount.replace(",", "").replace("$", ""))
            except:
                await ctx.send("❌ Invalid amount!")
                return
        if amount <= 0 or amount > life["bank"]:
            await ctx.send(f"❌ Invalid amount. You have **{format_money(life['bank'])}** in bank.")
            return
        update_life(ctx.author.id, cash=life["cash"] + amount, bank=life["bank"] - amount)
        await ctx.send(f"💵 Withdrew **{format_money(amount)}** → Wallet: **{format_money(life['cash'] + amount)}**")

    @commands.command(name="pay", aliases=["send2"], help="Send money to another player")
    async def pay_command(self, ctx, member: discord.Member, amount: int):
        ensure_life(ctx.author.id)
        ensure_life(member.id)
        if member.id == ctx.author.id:
            await ctx.send("❌ You can't pay yourself!")
            return
        life = get_life(ctx.author.id)
        if amount <= 0 or amount > life["cash"]:
            await ctx.send(f"❌ Invalid amount. Wallet: {format_money(life['cash'])}")
            return
        their_life = get_life(member.id)
        update_life(ctx.author.id, cash=life["cash"] - amount)
        update_life(member.id, cash=their_life["cash"] + amount)
        await ctx.send(f"💸 **{ctx.author.display_name}** sent **{format_money(amount)}** to **{member.display_name}**!")

    @commands.command(name="gamble", aliases=["gam"], help="Gamble your money (risky!)")
    async def gamble_command(self, ctx, amount: int):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)
        if amount <= 0 or amount > life["cash"]:
            await ctx.send(f"❌ Invalid amount. You have **{format_money(life['cash'])}**.")
            return

        outcome = random.random()
        if outcome < 0.45:  # 45% win
            winnings = int(amount * random.uniform(1.5, 3.0))
            new_cash = life["cash"] - amount + winnings
            update_life(ctx.author.id, cash=new_cash, happiness=min(100, life["happiness"] + 5))
            await ctx.send(f"🎰 **WINNER!** You gambled **{format_money(amount)}** and won **{format_money(winnings)}**! New balance: **{format_money(new_cash)}** 🤑")
        else:  # 55% loss
            new_cash = life["cash"] - amount
            update_life(ctx.author.id, cash=new_cash, happiness=max(0, life["happiness"] - 5))
            await ctx.send(f"💸 **You lost!** **{format_money(amount)}** gone. New balance: **{format_money(new_cash)}** 😭")

    # ==================================================
    # ADMIN COMMANDS
    # ==================================================

    @commands.command(name="addcash", help="[ADMIN] Add cash to a player's account")
    @commands.has_permissions(administrator=True)
    async def addcash_command(self, ctx, member: discord.Member, amount: int):
        ensure_life(member.id)
        life = get_life(member.id)
        update_life(member.id, cash=life["cash"] + amount)
        await ctx.send(f"✅ Added **{format_money(amount)}** to **{member.display_name}**'s wallet. New balance: **{format_money(life['cash'] + amount)}**")

    @commands.command(name="setstat", help="[ADMIN] Set a player's stat")
    @commands.has_permissions(administrator=True)
    async def setstat_command(self, ctx, member: discord.Member, stat: str, value: int):
        valid = ["reputation", "confidence", "fitness", "energy", "happiness", "fans", "fan_loyalty"]
        if stat not in valid:
            await ctx.send(f"❌ Valid stats: {', '.join(valid)}")
            return
        ensure_life(member.id)
        update_life(member.id, **{stat: max(0, min(100 if stat != "fans" else 999999999, value))})
        await ctx.send(f"✅ Set **{member.display_name}**'s **{stat}** to **{value}**")

    @commands.command(name="awardfans", help="[ADMIN] Award fans to a player (e.g. after a good match)")
    @commands.has_permissions(administrator=True)
    async def awardfans_command(self, ctx, member: discord.Member, amount: int, *, reason: str = "Award"):
        ensure_life(member.id)
        life = get_life(member.id)
        update_life(member.id, fans=life["fans"] + amount)
        update_social(member.id, followers=get_social(member.id)["followers"] + amount // 2)
        embed = discord.Embed(title="👥 Fans Awarded!", color=0xFFD700,
                              description=f"**{member.display_name}** gained **{amount:,}** fans!\n📌 Reason: {reason}")
        embed.add_field(name="New Fan Count", value=f"**{life['fans'] + amount:,}**", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="awardtrophy", help="[ADMIN] Award a trophy to a player")
    @commands.has_permissions(administrator=True)
    async def awardtrophy_command(self, ctx, member: discord.Member, *, trophy_name: str):
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("INSERT INTO player_trophies (user_id, trophy_name) VALUES (?,?)", (member.id, trophy_name))
        conn.commit()
        conn.close()
        player_name = get_player_name(member.id) or member.display_name
        embed = discord.Embed(title="🏆 Trophy Awarded!", color=0xFFD700,
                              description=f"**{player_name}** has been awarded the **{trophy_name}** trophy!")
        await ctx.send(embed=embed)

    # ==================================================
    # MISC / FUN
    # ==================================================

    @commands.command(name="richlist", aliases=["rl"], help="View richest players")
    async def richlist_command(self, ctx):
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("SELECT user_id, cash + bank as total FROM player_life ORDER BY total DESC LIMIT 10")
        results = c.fetchall()
        conn.close()

        embed = discord.Embed(title="💰 Richest Cricket Players", color=0xFFD700)
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        for i, (uid, total) in enumerate(results):
            member = ctx.guild.get_member(uid)
            name = get_player_name(uid) or (member.display_name if member else f"User {uid}")
            embed.add_field(name=f"{medals[i]} {name}", value=format_money(total), inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="fanlist", aliases=["fl"], help="View most popular players by fans")
    async def fanlist_command(self, ctx):
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("SELECT user_id, fans FROM player_life ORDER BY fans DESC LIMIT 10")
        results = c.fetchall()
        conn.close()

        embed = discord.Embed(title="👥 Most Popular Players", color=0xFF69B4)
        medals = ["🥇", "🥈", "🥉"] + ["⭐"] * 7
        for i, (uid, fans) in enumerate(results):
            member = ctx.guild.get_member(uid)
            name = get_player_name(uid) or (member.display_name if member else f"User {uid}")
            tier = self._fan_tier(fans)
            embed.add_field(name=f"{medals[i]} {name}", value=f"{fans:,} fans — {tier}", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="daily", help="Claim your daily reward")
    async def daily_command(self, ctx):
        ensure_life(ctx.author.id)
        life = get_life(ctx.author.id)
        can, mins = cooldown_check(life["last_rest"], 20)  # Using rest as daily tracker

        cash_reward = random.randint(2000, 10000)
        fan_reward = random.randint(100, 1000)
        new_cash = life["cash"] + cash_reward
        new_fans = life["fans"] + fan_reward
        new_energy = min(100, life["energy"] + 20)
        update_life(ctx.author.id, cash=new_cash, fans=new_fans, energy=new_energy)

        embed = discord.Embed(title="🎁 Daily Reward Claimed!", color=0x00FF00,
                              description=f"Another day in the cricket life!")
        embed.add_field(name="Rewards", value=f"💵 +{format_money(cash_reward)}\n👥 +{fan_reward:,} fans\n⚡ +20 Energy", inline=False)
        embed.set_footer(text="Come back tomorrow for more!")
        await ctx.send(embed=embed)

    @commands.command(name="crickethelp", aliases=["ch"], help="View all Player Life commands")
    async def crickethelp_command(self, ctx):
        embed = discord.Embed(title="🏏 Player Life — Command List", color=0xFFD700,
                              description="Build your cricket career on AND off the field!")
        embed.add_field(name="📊 Profile", value="`-profile` `-networth` `-balance` `-mycars` `-myhouse`", inline=False)
        embed.add_field(name="💪 Fitness", value="`-train` `-rest` `-rehab`", inline=False)
        embed.add_field(name="📱 Social Media", value="`-feed` `-feed english` `-feed hinglish` `-socialmedia` `-post` `-setbio` `-verify`", inline=False)
        embed.add_field(name="⚔️ Rivals", value="`-rival @user` `-trashtalk @user` `-rivals`", inline=False)
        embed.add_field(name="🎤 Events", value="`-press` `-scandal` `-lockerroom`", inline=False)
        embed.add_field(name="👥 Fans", value="`-fans` `-fanlist`", inline=False)
        embed.add_field(name="💑 Relationships", value="`-relationship` `-propose` `-marry` `-breakup`", inline=False)
        embed.add_field(name="🚗 Lifestyle", value="`-showroom` `-buycar` `-buyhouse`", inline=False)
        embed.add_field(name="🤝 Sponsors", value="`-getsponsor` `-collect`", inline=False)
        embed.add_field(name="💰 Money", value="`-deposit` `-withdraw` `-pay` `-gamble` `-daily` `-richlist`", inline=False)
        embed.set_footer(text="Admin: -addcash -setstat -awardfans -awardtrophy")
        await ctx.send(embed=embed)


async def setup(bot):
    init_playerlife_db()
    await bot.add_cog(PlayerLife(bot))