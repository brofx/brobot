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
        symbol = "DJI" if not symbol else symbol.upper()
        stock_lookup = requests.get(
            "https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={}&interval=1min&apikey={}".format(
                symbol, self.key))

        if stock_lookup.json().get('Error Message'):
            return await ctx.send('Please enter a valid stock symbol')
        name = symbol_lookup(symbol)
        dates = sorted(stock_lookup.json()['Time Series (Daily)'].keys(), reverse=True)
        start = '{0:.2f}'.format(float(stock_lookup.json()['Time Series (Daily)'][dates[1]]['4. close']))
        current = '{0:.2f}'.format(float(stock_lookup.json()['Time Series (Daily)'][dates[0]]['4. close']))
        change = '{0:.2f}'.format(float(current) - float(start))
        percent = '{0:.2f}'.format((float(change) / float(start)) * 100)

        result = "\n**{}({})**\nOpen: ${}\nNow: ${}\n∆$ {}\n∆% {}".format(name, symbol, start, current, change, percent)

        return await ctx.send(result)


def setup(bot: commands.Bot):
    bot.add_cog(Stocks(bot))


def symbol_lookup(sybol: str) -> str:
    s = requests.get("http://d.yimg.com/aq/autoc?query={}&region=US&lang=en-US".format(sybol)).json()
    return s['ResultSet']['Result'][0]['name']
