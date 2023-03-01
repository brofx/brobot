from datetime import datetime
from typing import List

import requests
import discord
from discord.ext import commands

EGS_URL = url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
EGS_PARAMS = {"allowCountries": "US", "country": "US", "locale": "en-US"}

class EGS(commands.Cog, name="Epic Game Store Games"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    async def egs(self, ctx: commands.Context):
        """Returns free game info from epic g ames"""
        embed: discord.Embed = discord.Embed(title="Free Epic games")
        game_list, image_to_display = get_game_list()
        embed.set_image(url=image_to_display)
        for day, games in game_list["current"].items():
            embed.add_field(name="Free Until {}".format(day), value="\n".join(games), inline=False)
        for day, games in game_list["upcomming"].items():
            embed.add_field(name="Free Starting {}".format(day), value="\n".join(games), inline=False)

        return await ctx.send(embed=embed)


def get_game_list():
    res = requests.get(EGS_URL, params=EGS_PARAMS).json()
    games = {
        "current": {},
        "upcomming": {}
    }

    image_to_display = None
    for x in res['data']['Catalog']['searchStore']['elements']:
        if not x['promotions']:
            continue

        is_available_now = bool(x['promotions']['promotionalOffers'])
        promo_key = "promotionalOffers" if is_available_now else "upcomingPromotionalOffers"
        promo_type = "current" if is_available_now else "upcomming"
        date_key = "endDate" if is_available_now else "startDate"
        promo_title = x['title']
        promo_time = datetime.strptime(
            x['promotions'][promo_key][0]['promotionalOffers'][0][date_key],
            "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%m/%d")

        if promo_time not in games[promo_type]:
            games[promo_type][promo_time] = []

        games[promo_type][promo_time].append(promo_title)

        if is_available_now and image_to_display is None:
            image_to_display = get_image(x["keyImages"])

    return games, image_to_display


def get_image(images: List[dict]):
    result = None
    for img_item in images:
        if img_item["type"] == "DieselStoreFrontTall":
            result = img_item["url"]
            break
    return result


async def setup(bot: commands.Bot):
    await bot.add_cog(EGS(bot))
