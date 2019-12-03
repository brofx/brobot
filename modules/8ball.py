import random
from typing import List

from discord.ext import commands
import discord


class EightBall(commands.Cog, name="Magic 8 Ball"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="8", aliases=["8ball"])
    @commands.guild_only()
    async def eightball(self, ctx: commands.Context, *, question=None):
        """Calls upon the magic eight ball"""
        messages: List[str] = ["It is certain",
                               "It is decidedly so",
                               "Without a doubt",
                               "Yes definitely",
                               "You may rely on it",
                               "As I see it yes",
                               "Most likely",
                               "Outlook good",
                               "Yes",
                               "Signs point to yes",
                               "Don't count on it",
                               "My reply is no",
                               "Cthulhu says no",
                               "Very doubtful",
                               "naw",
                               "sorry bud",
                               "yes, gods plan",
                               "that's gonna be a no from me dawg",
                               "No, stop asking."]
        embed: discord.Embed = discord.Embed(title=question or "Magic 8 Ball")
        embed.add_field(name="My Decision", value=random.choice(messages), inline=False)

        return await ctx.send(embed=embed)


def setup(bot: commands.Bot):
    bot.add_cog(EightBall(bot))
