from datetime import datetime

import discord
import redis
import pendulum
import calendar
from datetime import datetime
from discord.ext import commands

# TODO Make These configurable
REDIS_CONFIG = {"host": "localhost", "port": 6379, "db": 6}
HOURLY_STATS_KEY = "HOURLY"
USER_STATS_KEY = "USER"
MENTION_STATS_KEY = "MENTION"
SEEN_KEY = "SEEN"

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

    @commands.command()
    @commands.guild_only()
    async def seen(self, ctx: commands.Context, *, target: str = None):
        if not target:
            return

        mentions = ctx.message.mentions
        if not target or not mentions or mentions[0].bot:
            return

        target_user: discord.Member = mentions[0]
        last_seen = self.redis.hget(SEEN_KEY, target_user.id)
        if last_seen:
            utc, message = last_seen.split("::")
            time_str = pendulum.from_timestamp(int(utc)).to_datetime_string()
            return await ctx.send(
                "Last time I saw {} was on {} saying {}".format(target_user.display_name, time_str, message))
        else:
            return await ctx.send("I don't have anything for that user.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Counts certain stats for messages in the channel"""
        author: discord.Member = message.author

        # Ignore commands or bot messages
        if author.bot or message.content.startswith("!") or not isinstance(message.channel, discord.TextChannel):
            return

        now: datetime = datetime.now()
        self.redis.hincrby(HOURLY_STATS_KEY, now.hour, 1)
        self.redis.zincrby(USER_STATS_KEY, 1, author.id)

        if message.mentions:
            for mention in message.mentions:
                # Excludes mentions of the bot since we who care
                if not mention.bot:
                    self.redis.zincrby(MENTION_STATS_KEY, 1, mention.id)

        # Seen data
        channel: discord.TextChannel = message.channel
        if channel.name == "main":
            dt: datetime = datetime.now()
            gmt = calendar.timegm(dt.utctimetuple())
            result = "{}::{}".format(gmt, message.content)
            self.redis.hset(SEEN_KEY, author.id, result)


async def setup(bot: commands.Bot):
    await bot.add_cog(ActivityTracker(bot))
