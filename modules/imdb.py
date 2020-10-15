import os

import discord
import requests
from discord.ext import commands

url = "https://imdb8.p.rapidapi.com/title/auto-complete"


class IMDB(commands.Cog, name="IMDB"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.key = os.getenv("IMDB_KEY")

    @commands.command()
    @commands.guild_only()
    async def imdb(self, ctx: commands.Context, *, querystring=None):
        """Displays IMDB"""

        if not querystring:
            return await ctx.send("Error, usage: !imdb <title>")

        embed = get_response(self, querystring)
        if embed is None:
            return await ctx.send("Unable to find it! If this issue persists, contact @h3r0_sH0t#0027")
        return await ctx.send(embed=embed)


def get_response(self, querystring):
    query = {"q": querystring}
    headers = {
        'x-rapidapi-host': "imdb8.p.rapidapi.com",
        'x-rapidapi-key': self.key
    }
    api_response = requests.get(url, headers=headers, params=query)
    if api_response.ok:
        response: dict = api_response.json()
        if response is not None:
            title = response["d"][0]["l"]
            type_film = response["d"][0]["q"]
            imdb_id = response["d"][0]["id"]
            imdb_url = "https://www.imdb.com/title/" + imdb_id

            embed: discord.Embed = discord.Embed(title=title)

            embed.add_field(name="Type", value=type_film)

            embed.add_field(name="URL", value=imdb_url)

            return embed

    return None


def setup(bot: commands.Bot):
    bot.add_cog(IMDB(bot))
