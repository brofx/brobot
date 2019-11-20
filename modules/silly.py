import datetime
import re
from random import choice

import discord
import requests
from discord.ext import commands

GOOD_BOT_RE = re.compile(r'^good bot$', re.IGNORECASE)


class Silly(commands.Cog, name="Silly Module"):
    """A collection of silly commands"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    async def mock(self, ctx: commands.Context, *, text: str):
        """Returns the given text in a mocking tone."""
        return await ctx.send("".join([choice([x.upper(), x.lower()]) for x in text]))

    @commands.command()
    @commands.guild_only()
    async def expanse(self, ctx: commands.Context):
        """Provides a countdown to when Season 4 of The Expanse releases."""
        today = datetime.datetime.now()
        expanse_date = datetime.datetime(2019, 12, 13, 18, 00, 0)
        delta = expanse_date - today
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        output = "{days} days, {hours} hours, {minutes} minutes, and {seconds} seconds until S4 of The Expanse!".format(
            days=delta.days, hours=hours, minutes=minutes, seconds=seconds)

        return await ctx.send(output)

    @commands.command()
    @commands.guild_only()
    async def rather(self, ctx: commands.Context):
        """Gets a random 'Would You Rather' question from reddit."""
        # TODO: Store this header somewhere and actually adjust version
        header = {"User-Agent": "BroBot/1.0 by github.com/brofx"}
        question_request = requests.get("http://www.reddit.com/r/wouldyourather.json?limit=100", headers=header).json()
        question = choice(question_request["data"]["children"])["data"]["title"]
        return await ctx.send(question)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Responds when someone calls the bot bad, implied sarcastically"""
        if message.author.bot:
            return

        if GOOD_BOT_RE.match(message.content):
            return await message.channel.send("bad human")


def setup(bot: commands.Bot):
    bot.add_cog(Silly(bot))
