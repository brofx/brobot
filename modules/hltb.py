from typing import List
import random
from bs4 import BeautifulSoup
import requests

from discord.ext import commands
import discord


class HLTB(commands.Cog, name="How Long To Beat"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    async def hltb(self, ctx: commands.Context, *, game: str = None):
        """Provides information on how long it could take to beat a game"""
        if not game:
            return await ctx.send("Syntax: !hltb [Game Name]")

        results = hltb(game, 1)
        if not results:
            return await ctx.send("I coulnd't find any info on that game.")

        name, main_story, main_extra, completionist = results[0]

        embed: discord.Embed = discord.Embed(title="How Long To Beat: {}".format(name))
        embed.add_field(name="Main Story", value=main_story, inline=False)
        embed.add_field(name="Main + Extras", value=main_extra, inline=False)
        embed.add_field(name="Completionist", value=completionist, inline=False)

        await ctx.send(embed=embed)


def hltb(game: str, result_count: int):
    url = "https://howlongtobeat.com/search_results.php?page=1"
    payload = {"queryString": game, "t": "games", "sorthead": "popular", "sortd": "Normal Order", "length_type": "main",
               "detail": "0"}
    test = {'Content-type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/48.0.2564.97 Safari/537.36',
            'origin': 'https://howlongtobeat.com', 'referer': 'https://howlongtobeat.com'}
    session = requests.Session()
    r = session.post(url, headers=test, data=payload)

    bs = BeautifulSoup(r.content, "html.parser")
    search_results = bs.findAll("div", {"class": "search_list_details"})
    num_games = min(len(search_results), result_count)
    all_results = []
    print(num_games)
    for x in range(num_games):
        game_listing = search_results[x]
        name = game_listing.a.text
        times = game_listing.findAll("div", {"class": lambda f: f and f.startswith("time_")})
        result = (name, *(item.text for item in times))
        all_results.append(result)
    return all_results


async def setup(bot: commands.Bot):
    await bot.add_cog(HLTB(bot))
