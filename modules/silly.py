from datetime import datetime, timedelta
import re
from random import choice

import discord
import requests
from discord.ext import commands

GOOD_BOT_RE = re.compile(r'^good bot$', re.IGNORECASE)
BAD_BOT_RE = re.compile(r'^bad bot$', re.IGNORECASE)
FUCK_YOU = re.compile(r'^fuck.+brobot.*$', re.IGNORECASE)

GOOD_BOT_RESPONSES = [
    "bad human",
    "no u",
    "you really think so? :blush:?",
    "thank you! i'll let my owners know how you feel"
]

BAD_BOT_RESPONSES = [
    "better than you",
    "deal with it",
    "fork it, fix it, pull request me",
    "remember when I asked for your opinion? me neither.",
    "you're annoying",
    "everyone is a bot except for you"
]

FUCK_YOU_RESPONSES = [
    "thats not nice :cry:",
    "what would make you say such a thing???",
    "i'm telling mom",
    "come again?"
]


class Silly(commands.Cog, name="Silly Module"):
    """A collection of silly commands"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    async def mock(self, ctx: commands.Context, *, text: str):
        """Returns the given text in a mocking tone."""
        result: str = "".join([choice([x.upper(), x.lower()]) for x in text])
        embed: discord.Embed = discord.Embed(title="") \
            .set_thumbnail(url="https://i.sc0tt.net/files/NBNso.png") \
            .add_field(name="​", value=result)
        return await ctx.send(embed=embed)

    @commands.command()
    @commands.guild_only()
    async def lenny(self, ctx: commands.Context):
        """Returns the lenny face"""
        return await ctx.send("( ͡° ͜ʖ ͡°)")

    @commands.command()
    @commands.guild_only()
    async def followage(self, ctx: commands.Context):
        """Shows the join date"""
        join_date: datetime = ctx.author.joined_at
        return await ctx.send("{} you joined the server on {}".format(ctx.author.mention, join_date.strftime("%Y-%m-%d at %I:%M %p")))

    @commands.command()
    @commands.guild_only()
    async def benny(self, ctx: commands.Context):
        """Returns the benny face"""
        return await ctx.send("(ง ͠° ͟ل͜ ͡°)ง")

    @commands.command()
    @commands.guild_only()
    async def expanse(self, ctx: commands.Context):
        """Provides a countdown to when Season 5 of The Expanse releases."""
        today: datetime = datetime.now()
        expanse_date: datetime = datetime(2020, 12, 16, 18, 00, 0)
        delta: timedelta = expanse_date - today
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        output: str = "{days} days, {hours} hours, {minutes} minutes, and {seconds} seconds until S5 of The Expanse!".format(
            days=delta.days, hours=hours, minutes=minutes, seconds=seconds)

        return await ctx.send(output)

    @commands.command()
    @commands.guild_only()
    async def rather(self, ctx: commands.Context):
        """Gets a random 'Would You Rather' question from reddit."""
        header: dict = {"User-Agent": "BroBot/1.0 by github.com/brofx"}
        question_request = requests.get("http://www.reddit.com/r/wouldyourather.json?limit=100", headers=header).json()
        question: str = choice(question_request["data"]["children"])["data"]["title"]
        return await ctx.send(question)

    @commands.command()
    @commands.guild_only()
    async def ask(self, ctx: commands.Context):
        """Gets a random 'Ask Reddit' question from reddit."""
        header: dict = {"User-Agent": "BroBot/1.0 by github.com/brofx"}
        question_request = requests.get("http://www.reddit.com/r/askreddit.json?limit=100", headers=header).json()
        question: str = choice(question_request["data"]["children"])["data"]["title"]
        return await ctx.send(question)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Responds when someone calls the bot bad, implied sarcastically"""

        author: discord.Member = message.author

        if author.bot:
            return

        if GOOD_BOT_RE.match(message.content):
            return await message.channel.send(choice(GOOD_BOT_RESPONSES))

        if BAD_BOT_RE.match(message.content):
            return await message.channel.send(choice(BAD_BOT_RESPONSES))

        if FUCK_YOU.match(message.content):
            return await message.channel.send(choice(FUCK_YOU_RESPONSES))


def setup(bot: commands.Bot):
    bot.add_cog(Silly(bot))
