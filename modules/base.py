from discord.ext import commands


class BaseModule(commands.Cog, name="Base Module"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    async def ping(self, ctx: commands.Context):
        await ctx.send("pong")

    #@commands.Cog.listener()
    #async def on_message(self, message):
    #    """Demo for listening to all messages in a module"""
    #    if message.author.bot: return
    #    if "yoyo" in message.content: 
    #        return await message.channel.send("Got a message: " + message.content)


def setup(bot: commands.Bot):
    bot.add_cog(BaseModule(bot))
