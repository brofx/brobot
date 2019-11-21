from typing import List
import random

from discord.ext import commands


class Choose(commands.Cog, name="Choose Module"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    async def choose(self, ctx: commands.Context, *, choices: str = None):
        """Chooses an option from the provided list of choices"""
        if not choices:
            return await ctx.send("Syntax: !choose Option 1 | Option 2 | Option 3 ...")

        formatted_choices: List[str] = [choice.strip() for choice in choices.split("|")]

        await ctx.send(random.choice(formatted_choices))


def setup(bot: commands.Bot):
    bot.add_cog(Choose(bot))
