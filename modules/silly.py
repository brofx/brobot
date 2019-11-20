from discord.ext import commands
from random import choice

class Silly(commands.Cog, name="Silly Module"):
    """A collection of silly commands"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    async def mock(self, ctx: commands.Context, *, text: str):
        await ctx.send("".join([choice([x.upper(), x.lower()]) for x in text]))


def setup(bot: commands.Bot):
    bot.add_cog(Silly(bot))
