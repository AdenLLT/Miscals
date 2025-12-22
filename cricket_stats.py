import discord
import sqlite3
from discord.ext import commands
from discord.ui import View, Button

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
            LIMIT 20
        """)
    elif stat_type == "wickets":
        c.execute("""
            SELECT user_id, SUM(wickets) as total, SUM(balls_bowled) as balls
            FROM match_stats
            GROUP BY user_id
            HAVING total > 0
            ORDER BY total DESC
            LIMIT 20
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

# Leaderboard View with category buttons
class LeaderboardView(View):
    def __init__(self, ctx):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.message = None

    async def create_leaderboard_embed(self, stat_type):
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
            return embed

        description = ""
        for idx, row in enumerate(data, 1):
            user_id = row[0]
            player_name = get_player_name_by_user_id(user_id)
            member = self.ctx.guild.get_member(user_id)
            username = member.name if member else "Unknown"

            player_display = f"{player_name} (@{username})" if player_name else f"@{username}"

            if stat_type == "runs":
                description += f"**{idx}.** {player_display}\n"
                description += f"    └ {row[1]} runs ({row[2]} balls)\n\n"
            elif stat_type == "wickets":
                description += f"**{idx}.** {player_display}\n"
                description += f"    └ {row[1]} wickets ({row[2]} balls)\n\n"
            elif stat_type == "economy":
                description += f"**{idx}.** {player_display}\n"
                description += f"    └ {row[3]:.2f} economy ({row[0]} runs in {row[1]} balls)\n\n"
            elif stat_type == "strike_rate":
                description += f"**{idx}.** {player_display}\n"
                description += f"    └ {row[3]:.2f} SR ({row[1]} runs off {row[2]} balls)\n\n"
            elif stat_type == "average":
                description += f"**{idx}.** {player_display}\n"
                description += f"    └ {row[3]:.2f} average ({row[1]} runs, {int(row[2])} dismissals)\n\n"
            elif stat_type == "bowling_average":
                description += f"**{idx}.** {player_display}\n"
                description += f"    └ {row[3]:.2f} average ({row[1]} runs, {int(row[2])} wickets)\n\n"

        embed.description = description
        embed.set_footer(text="Tournament Statistics")
        return embed

    @discord.ui.button(label="🏏 Runs", style=discord.ButtonStyle.success, row=0)
    async def runs_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        embed = await self.create_leaderboard_embed("runs")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🎯 Wickets", style=discord.ButtonStyle.success, row=0)
    async def wickets_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        embed = await self.create_leaderboard_embed("wickets")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="💰 Economy", style=discord.ButtonStyle.success, row=0)
    async def economy_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        embed = await self.create_leaderboard_embed("economy")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⚡ Strike Rate", style=discord.ButtonStyle.primary, row=1)
    async def sr_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        embed = await self.create_leaderboard_embed("strike_rate")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="📊 Bat Average", style=discord.ButtonStyle.primary, row=1)
    async def avg_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        embed = await self.create_leaderboard_embed("average")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🎳 Bowl Average", style=discord.ButtonStyle.primary, row=1)
    async def bowl_avg_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your menu!", ephemeral=True)
            return
        embed = await self.create_leaderboard_embed("bowling_average")
        await interaction.response.edit_message(embed=embed, view=self)

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

            # Batting stats
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

            # Bowling stats
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
        # Check if this is a reply to a message
        if not ctx.message.reference:
            await ctx.send("❌ Please reply to a message containing match statistics!")
            return

        # Get the message being replied to
        replied_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)

        # Extract stats from the message content
        content = replied_msg.content

        # Find all lines that contain stats (format: user_id, runs, balls, etc.)
        import re
        pattern = r'(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)'
        matches = re.findall(pattern, content)

        if not matches:
            await ctx.send("❌ No valid statistics found in the replied message!")
            return

        # Add stats to database
        conn = sqlite3.connect('players.db')
        c = conn.cursor()

        added_count = 0
        for match in matches:
            user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out = map(int, match)

            c.execute("""
                INSERT INTO match_stats (user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, runs, balls_faced, runs_conceded, balls_bowled, wickets, not_out))
            added_count += 1

        conn.commit()
        conn.close()

        await ctx.send(f"✅ Successfully added statistics for **{added_count}** players!")

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
        embed = await view.create_leaderboard_embed("runs")
        view.message = await ctx.send(embed=embed, view=view)

    @commands.command(name="resetstats", help="[ADMIN] Reset all match stats")
    @commands.has_permissions(administrator=True)
    async def resetstats_command(self, ctx):
        conn = sqlite3.connect('players.db')
        c = conn.cursor()
        c.execute("DELETE FROM match_stats")
        conn.commit()
        conn.close()
        await ctx.send("✅ All match statistics have been reset!")

# Setup function to load the cog
async def setup(bot):
    await bot.add_cog(CricketStats(bot))