from discord.ext import commands


class BaseModule(commands.Cog, name="Base Module"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    @commands.ro
    @commands.guild_only()
    async def ping(self, ctx: commands.Context):
        await ctx.send("pong")


def setup(bot: commands.Bot):
    bot.add_cog(BaseModule(bot))
