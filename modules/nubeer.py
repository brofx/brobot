from discord.ext import commands
import discord
import requests

NUBEER_STATS_URL = 'https://nubeer.io/api/3812-52134-452148-0482134'

class Nubeer(commands.Cog, name="Nubeer Information"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    async def nubeer(self, ctx: commands.Context):
        """Displays Nubeer Stats"""      
        embed = get_nubeer_stats()  
        if embed is None:
            return await ctx.send("Unable to get stats.")
        return await ctx.send(embed=embed)

def get_nubeer_stats():
    api_response = requests.get(NUBEER_STATS_URL)

    if api_response.ok:
        data: dict = api_response.json()["data"]
        if data is not None: 
            beers = data["beers"]
            users = data["users"]
            breweries = data["breweries"]
            ratings = data["ratings"]

            embed: discord.Embed = discord.Embed(title="Nubeer Stats")

            embed.add_field(name="Total Beers", value=beers)

            embed.add_field(name="Total Users", value=users)

            embed.add_field(name="Total Breweries", value=breweries)

            embed.add_field(name="Total Ratings", value=ratings)

            return embed

    return None

def setup(bot: commands.Bot):
    bot.add_cog(Nubeer(bot))
