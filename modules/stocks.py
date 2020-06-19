import discord
import requests
from discord.ext import commands


class Stocks(commands.Cog, name="Stocks Module"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.key = "APIKEYGOESHERELOL"  # os.getenv("ALPHAVANTAGE_KEY")

    @commands.command()
    @commands.guild_only()
    async def stocks(self, ctx: commands.Context, symbol: str = None):
        """Returns the curent stock information for a given stock or defaults to DJI if no stock is provided."""
        symbol = "^DJI" if not symbol else symbol.upper()
        stock_lookup = requests.get(
            "https://finnhub.io/api/v1/quote?symbol={}&token={}".format(
                symbol, self.key))

        if stock_lookup.json().get('Error Message'):
            return await ctx.send('Please enter a valid stock symbol')
        name = symbol_lookup(symbol)

        start_value: float = float(stock_lookup.json()['o'])
        current_value: float = float(stock_lookup.json()['c'])
        change_dollars: float = current_value - start_value
        change_pct: float = (change_dollars / start_value) * 100

        color = 0x000000 if abs(change_pct) < .5 else 0x007d15 if change_dollars > 0 else 0x7d0000

        start = '$ {0:.2f}'.format(start_value)
        current = '$ {0:.2f}'.format(current_value)
        change = '$ {0:.2f} / {1:.2f} %'.format(change_dollars, change_pct)

        embed: discord.Embed = discord.Embed(title="{name} ({symbol})".format(
            name=name,
            symbol=symbol
        ), color=color)
        embed.add_field(name="Open", value=start, inline=False)
        embed.add_field(name="Now", value=current, inline=False)
        embed.add_field(name="Change ", value=change, inline=False)

        return await ctx.send(embed=embed)


def setup(bot: commands.Bot):
    bot.add_cog(Stocks(bot))


def symbol_lookup(sybol: str) -> str:
    s = requests.get("http://d.yimg.com/aq/autoc?query={}&region=US&lang=en-US".format(sybol)).json()
    return s['ResultSet']['Result'][0]['name']
