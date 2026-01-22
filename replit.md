# replit.md

## Overview

This is a Discord bot built with Python and discord.py, focused on cricket statistics and tournament management. The bot provides features for tracking player stats, generating leaderboards, managing tournaments with fixtures, and displaying player cards with ratings. It serves a cricket gaming community, tracking match performance and organizing competitive tournaments.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Bot Framework
- **Framework**: discord.py with commands extension
- **Command Prefix**: `-` (hyphen)
- **Architecture Pattern**: Cog-based modular design with separate files for different features

### Core Modules
1. **main.py** - Bot initialization, event handling, and core setup
2. **cricket_stats.py** - Player statistics tracking, leaderboards, and stat calculations
3. **tournament.py** - Tournament management with teams, fixtures, and standings
4. **matchupdates.py** - Live match monitoring and updates from another cricket bot

### Database
- **Database**: SQLite (`players.db`)
- **Tables**:
  - `match_stats` - Individual match performance (runs, balls, wickets, etc.)
  - `tournaments` - Tournament metadata and status
  - `tournament_teams` - Team standings with points, wins, losses, NRR
  - `fixtures` - Match scheduling with round tracking

### Data Storage
- **Player Ratings**: `data.json` - Static player cards with batting/bowling ratings and images
- **Team Rosters**: `players.json` - International cricket team player data with roles and images
- **Elite Players**: `elite_players.json` - List of featured/special players
- **Discord Assets**: `player_stickers.json`, `player_emojis.json` - Discord asset IDs for players

### Image Generation
- **Library**: Pillow (PIL)
- **Purpose**: Generating player cards, leaderboard images, and tournament graphics
- **Approach**: Dynamic image creation with player stats overlaid on templates

### Async HTTP
- **Library**: aiohttp
- **Purpose**: Fetching player images from external URLs for card generation

## External Dependencies

### Discord Integration
- **discord.py** - Core bot framework with commands extension
- **Discord API** - Bot token stored in environment variable `TOKEN`

### Image Hosting
- **Tixte CDN** (us-east-1.tixte.net) - Hosts player card images referenced in data.json

### External Bot Integration
- Monitors messages from another Discord bot (ID: 753191385296928808) for match updates

### Python Libraries
- **sqlite3** - Database operations (built-in)
- **Pillow/PIL** - Image processing and generation
- **aiohttp** - Async HTTP requests for fetching images
- **pytz** - Timezone handling