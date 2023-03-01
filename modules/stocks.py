import os
from typing import Optional, Tuple

import discord
import requests
from discord.ext import commands


class Stocks(commands.Cog, name="Stocks Module"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.key = os.getenv("FINNHUB_KEY")

    @commands.command()
    @commands.guild_only()
    async def stocks(self, ctx: commands.Context, entered_symbol: str = None):
        """Returns the curent stock information for a given stock or defaults to DJI if no stock is provided."""

        entered_symbol = "SPY" if not entered_symbol else entered_symbol.upper()
        name, symbol = symbol_lookup(entered_symbol)

        if not name:
            return await ctx.send("Not found")

        stock_lookup = requests.get(
            "https://finnhub.io/api/v1/quote?symbol={}&token={}".format(
                entered_symbol, self.key))

        if stock_lookup.json().get('Error Message'):
            return await ctx.send('Please enter a valid stock symbol')

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


async def setup(bot: commands.Bot):
    await bot.add_cog(Stocks(bot))


def symbol_lookup(symb: str) -> Tuple[Optional[str], Optional[str]]:
    s = requests.get(
        "https://query2.finance.yahoo.com/v1/finance/search?q={}&lang=en-US&region=US&quotesCount=3&newsCount=0".format(
            symb), headers={'User-Agent': 'brobot/discord.bot'}).json()
    if not s['quotes']:
        return None, None
    return (s['quotes'][0].get('shortname') or s['quotes'][0]['longname']), s['quotes'][0]['symbol']
