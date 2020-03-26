from datetime import datetime

import requests
import discord
from discord.ext import commands


class EGS(commands.Cog, name="Epic Game Store Games"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    async def egs(self, ctx: commands.Context):
        """Returns free game info from epic g ames"""
        embed: discord.Embed = discord.Embed(title="Free Epic games")
        game_list = get_game_list()
        for day, games in game_list["current"].items():
            embed.add_field(name="Free Until {}".format(day), value="\n".join(games), inline=False)
        for day, games in game_list["upcomming"].items():
            embed.add_field(name="Free Starting {}".format(day), value="\n".join(games), inline=False)

        return await ctx.send(embed=embed)


def get_game_list():
    variables = {"namespace": "epic", "country": "US", "locale": "en-US"}
    query = """
          query promotionsQuery($namespace: String!, $country: String!, $locale: String!) {
            Catalog {
              catalogOffers(namespace: $namespace, locale: $locale, params: {category: \"freegames\", country: $country, sortBy: \"effectiveDate\", sortDir: \"asc\"}) {
                elements {
                  title
                  description
                  promotions {
                    promotionalOffers {
                      promotionalOffers {
                        startDate
                        endDate
                      }
                    }
                    upcomingPromotionalOffers {
                      promotionalOffers {
                        startDate
                        endDate
                      }
                    }
                  }
                }
              }
            }
          }
        """

    res = (requests.post('https://graphql.epicgames.com/graphql', json={'query': query, 'variables': variables})).json()
    games = {
        "current": {},
        "upcomming": {}
    }

    for x in res['data']['Catalog']['catalogOffers']['elements']:
        if not x['promotions']:
            continue

        is_available_now = bool(x['promotions']['promotionalOffers'])
        promo_key = "promotionalOffers" if is_available_now else "upcomingPromotionalOffers"
        promo_type = "current" if is_available_now else "upcomming"
        promo_title = x['title']
        promo_time = datetime.strptime(
            x['promotions'][promo_key][0]['promotionalOffers'][0]['endDate'],
            "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%m/%d")

        if promo_time not in games[promo_type]:
            games[promo_type][promo_time] = []

        games[promo_type][promo_time].append(promo_title)

    return games


def setup(bot: commands.Bot):
    bot.add_cog(EGS(bot))
