import discord
import requests
from discord.ext import commands

NEXT_RACE_URL = "http://ergast.com/api/f1/current/next.json"


class F1(commands.Cog, name="Formula1 Module"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    async def f1(self, ctx: commands.Context):
        """Returns the next F1 race information."""
        next_race = get_next_race()
        if not next_race:
            return await ctx.send("No upcomming race.")
        return await ctx.send(embed=next_race)


async def setup(bot: commands.Bot):
    await bot.add_cog(F1(bot))


def get_next_race():
    api_result = requests.get(NEXT_RACE_URL)

    if api_result.ok:
        root: dict = api_result.json()["MRData"]
        if int(root["total"]) > 0:
            race_table = root["RaceTable"]
            race = race_table["Races"][0]
            location_info = race["Circuit"]["Location"]

            ret_val: discord.Embed = discord.Embed(title="[#{race_num}] {season} **{race_name}**".format(
                race_num=race_table["round"],
                season=race_table["season"],
                race_name=race["raceName"],
            ))

            ret_val.add_field(name="Circuit", value=race["Circuit"]["circuitName"], inline=False)

            ret_val.add_field(name="Location", value="{locality}, {country}".format(
                locality=location_info["locality"],
                country=location_info["country"]), inline=False)

            ret_val.add_field(name="Time", value="{date} {time}".format(
                date=race["date"],
                time=race["time"]
            ), inline=False)

            return ret_val

    return None
