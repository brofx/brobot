import random

import discord
from discord.ext import commands


class Roll(commands.Cog, name="Roll"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    async def roll(self, ctx: commands.Context, first: int = None, second: int = None):
        """Picks a random number between :first and :second or 0 and 100"""
        if not first and not second:
            # No args, default to 0-99
            first, second = (0, 100)
        elif not second:
            # When only the first argument is present, default to 0-first
            first, second = (0, first)
        elif second < first:
            # Otherwise, both are are present and this is an invalid range
            return await ctx.send("Invalid range")
        result: int = random.randint(first, second)
        embed: discord.Embed = discord.Embed(title=":game_die: random({}, {})".format(first, second))
        embed.add_field(name="Result", value=str(result), inline=False)
        return await ctx.send(embed=embed)


def setup(bot: commands.Bot):
    bot.add_cog(Roll(bot))
