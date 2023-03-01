import re

import requests
import discord
from discord.ext import commands
from requests.utils import requote_uri


class UrbanDict(commands.Cog, name="Urban Dictionary Module"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    async def ud(self, ctx: commands.Context, *, term: str = None):
        """Gets the first urban dictionary definition for the given string."""

        if not term:
            return await ctx.send("Error, usage: !ud <term>")

        data: dict = requests.get(requote_uri("http://api.urbandictionary.com/v0/define?term={0}".format(term))).json()

        if not data['list']:
            return await ctx.send("No results found for {0}".format(term))

        # Only find definitions where the term matches
        try:
            result: dict = list(filter(lambda x: x['word'].lower() == term.lower(), data['list']))[0]
        except IndexError:
            return await ctx.send("No results found for {0}".format(term))

        # Provides a url to access
        # Discord will basically repeat the definition with an embed if this is used
        # url: str = 'http://{}.urbanup.com'.format(term.replace(" ", "-"))

        definition: str = re.sub(r'([\[\]])', '', result['definition'])

        response: discord.Embed = discord.Embed(title=term)
        response.add_field(name="Definition", value=definition, inline=False)

        return await ctx.send(embed=response)


async def setup(bot: commands.Bot):
    await bot.add_cog(UrbanDict(bot))
