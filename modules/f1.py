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
        return await ctx.send(next_race)


def setup(bot: commands.Bot):
    bot.add_cog(F1(bot))


def get_next_race():
    ret_val = None

    result = requests.get(NEXT_RACE_URL)

    if result.ok:
        root = result.json()["MRData"]
        if int(root["total"]) > 0:
            raceTable = root["RaceTable"]
            race = raceTable["Races"][0]
            ret_val = "[#{race_num}] {season} **{race_name}**, {race_loc} @ {date} {time}".format(
                race_num=raceTable["round"],
                season=raceTable["season"],
                race_name=race["raceName"],
                race_loc=race["Circuit"]["circuitName"],
                date=race["date"],
                time=race["time"]
            )

    return ret_val
