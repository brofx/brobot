import discord
import requests
from bs4 import BeautifulSoup
from discord.ext import commands

MAX_KYM_LEN = 400

class KYM(commands.Cog, name="Know Your Meme"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    async def kym(self, ctx: commands.Context, *, query=None):
        """Searches for a KYM result"""

        if not query:
            return await ctx.send("Please provide something to look up")

        result = kym(query)

        if not result:
            return await ctx.send("No result found")

        title, content, uri = result

        if len(content) > MAX_KYM_LEN:
            content = content[:MAX_KYM_LEN] + "..."

        embed: discord.Embed = discord.Embed(title=title)
        embed.add_field(name="Result", value=content, inline=False)
        embed.add_field(name="Reference", value=uri, inline=False)

        return await ctx.send(embed=embed)


def kym(query):
    x = requests.get("http://knowyourmeme.com/search?q={}".format(query), headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/40.0.2214.85 Safari/537.36'})
    bs = BeautifulSoup(x.content, 'html.parser')
    try:
        url2 = bs.findAll("tbody")[0].tr.td.a['href']
    except:
        return None

    x2 = requests.get("https://knowyourmeme.com{}".format(url2), headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/40.0.2214.85 Safari/537.36'})
    bs2 = BeautifulSoup(x2.content, 'html.parser')
    about = bs2.find('meta', attrs={"property": "og:description"})['content']
    uri = bs2.find('meta', attrs={"property": "og:url"})['content']
    title = bs2.find('meta', attrs={"property": "og:title"})['content']

    return title, about, uri


def setup(bot: commands.Bot):
    bot.add_cog(KYM(bot))
