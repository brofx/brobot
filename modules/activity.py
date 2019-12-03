from datetime import datetime

import discord
import redis
from discord.ext import commands

# TODO Make These configurable
REDIS_CONFIG = {"host": "localhost", "port": 6379, "db": 6}
HOURLY_STATS_KEY = "HOURLY"
USER_STATS_KEY = "USER"
MENTION_STATS_KEY = "MENTION"

PLACING_EMOJIS = [":first_place:", ":second_place:", ":third_place:"]


class ActivityTracker(commands.Cog, name="Activity Module"):
    """Tracks most active users, most mentions, and most active times of day"""

    def __init__(self, bot: commands.Bot):
        self.redis = redis.Redis(**REDIS_CONFIG, decode_responses=True)
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    async def mentions(self, ctx: commands.Context, *, target: str = None):
        """Displays the top list of mentions or the number of mentions for the user"""
        if target and target == "me":
            result = int(self.redis.zscore(MENTION_STATS_KEY, ctx.author.id) or 0)
            final_string = "You've been mentioned {} time{}".format(result, "s" if result != 1 else "")
            return await ctx.send(final_string)
        else:
            embed: discord.Embed = discord.Embed(title="Most Mentioned Users")
            for index, record in enumerate(self.redis.zrevrange(MENTION_STATS_KEY, 0, 2, withscores=True)):
                user_id, count = record
                row_text = "{}".format(int(count))
                embed.add_field(
                    name="{} - {}".format(PLACING_EMOJIS[index], ctx.guild.get_member(int(user_id)).display_name),
                    value=row_text, inline=False)
            return await ctx.send(embed=embed)

    @commands.command()
    @commands.guild_only()
    async def lines(self, ctx: commands.Context, *, target: str = None):
        """Displays the most talkative members or the number of lines for the user"""
        if target and target == "me":
            result = int(self.redis.zscore(USER_STATS_KEY, ctx.author.id) or 0)
            final_string = "You've said {} line{}".format(result, "s" if result != 1 else "")
            return await ctx.send(final_string)
        else:
            embed: discord.Embed = discord.Embed(title="Most Talkative Users")
            for index, record in enumerate(self.redis.zrevrange(USER_STATS_KEY, 0, 2, withscores=True)):
                user_id, count = record
                row_text = "{}".format(int(count))
                embed.add_field(
                    name="{} - {}".format(PLACING_EMOJIS[index], ctx.guild.get_member(int(user_id)).display_name),
                    value=row_text, inline=False)
            return await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Counts certain stats for messages in the channel"""
        author: discord.Member = message.author

        # Ignore commands or bot messages
        if author.bot or message.content.startswith("!"):
            return

        now: datetime = datetime.now()
        self.redis.hincrby(HOURLY_STATS_KEY, now.hour, 1)
        self.redis.zincrby(USER_STATS_KEY, 1, author.id)

        if message.mentions:
            for mention in message.mentions:
                # Excludes mentions of the bot since we who care
                if not mention.bot:
                    self.redis.zincrby(MENTION_STATS_KEY, 1, mention.id)


def setup(bot: commands.Bot):
    bot.add_cog(ActivityTracker(bot))
