import random
import re
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

import discord
import requests
from bs4 import BeautifulSoup
from discord.ext import commands


class GDQ(commands.Cog, name="GDQ Information"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    async def gdq(self, ctx: commands.Context, *, question=None):
        """Gets information about the current or next GDQ"""
        embed: discord.Embed = discord.Embed(title="Games Done Quick")
        # embed.add_field(name="", value=random.choice(messages), inline=False)

        gdq_info: List[Tuple[str, str]] = get_gdq_info()

        image_url = "https://static-cdn.jtvnw.net/previews-ttv/live_user_gamesdonequick-1280x720.jpg?x={}".format(
            random.randint(1, 1000))

        embed.set_image(url=image_url)

        for field_name, data in gdq_info:
            embed.add_field(name=field_name, value=data, inline=False)
        return await ctx.send(embed=embed)


def setup(bot: commands.Bot):
    bot.add_cog(GDQ(bot))


def GDQdatetime():
    # From https://github.com/dasu/syrup-sopel-modules/blob/master/gdq.py
    now = datetime.utcnow()
    now = now.replace(tzinfo=timezone.utc)
    try:
        url = "https://gamesdonequick.com"
        req = requests.get(url).content
        bs = BeautifulSoup(req, "html.parser")
        dtext = bs.h5.findNext("p").text
    except:
        if datetime.now().month >= 5:
            nextgdqstartest = "Early January"
        else:
            nextgdqstartest = "Early June"
        delta = None
        return now, delta, nextgdqstartest
    begdtext = re.sub(r' ?- ?.*?,', ',', dtext)
    fdtext = re.sub(r'(?<=\d)(st|nd|rd|th)', '', begdtext)
    try:
        gdqs = (datetime.strptime(fdtext, "%B %d, %Y")).replace(tzinfo=timezone.utc)
        delta = gdqs - now
        nextgdqstartest = fdtext.split(',')[0]
    except:
        nextgdqstartest = fdtext
        delta = None
    return now, delta, nextgdqstartest


def getinfo(run, now):
    # From https://github.com/dasu/syrup-sopel-modules/blob/master/gdq.py
    schedule = run.find_all('tr', attrs={'class': None})
    game, runner, console, comment, eta, nextgame, nextrunner, nextconsole, nexteta, nextcomment = '', '', '', '', '', '', '', '', '', ''
    for item in schedule:
        group = item.find_all('td')
        try:
            group2 = item.find_next_sibling().find_all('td')
        except:
            nextgame = False
            return (game, runner, console, comment, eta, nextgame, nextrunner, nexteta, nextconsole, nextcomment)
        st = group[0].getText()
        # estfix = timedelta(hours=-5)
        starttime = datetime.strptime(st, '%Y-%m-%dT%H:%M:%SZ')
        starttime = starttime.replace(tzinfo=timezone.utc)
        # starttime = starttime + estfix
        try:
            offset = datetime.strptime(group2[0].getText().strip(), "%H:%M:%S")
            endtime = starttime + timedelta(hours=offset.hour, minutes=offset.minute, seconds=offset.second)
        except:
            endtime = datetime(2011, 1, 1, 12, 00)
        if starttime < now and endtime > now:
            game = group[1].getText()
            runner = group[2].getText()
            # console = group[3].getText()
            comment = group2[1].getText()
            eta = group2[0].getText().strip()
        if starttime > now:
            nextgame = group[1].getText()
            nextrunner = group[2].getText()
            # nextconsole = group[3].getText()
            nexteta = group2[0].getText().strip()
            nextcomment = group2[1].getText()
            break
        else:
            nextgame = 'done'
            nextrunner = 'done'
    return (game, runner, console, comment, eta, nextgame, nextrunner, nexteta, nextconsole, nextcomment)


def get_gdq_info():
    # Adapted from https://github.com/dasu/syrup-sopel-modules/blob/master/gdq.py
    now, delta, textdate = GDQdatetime()
    url = 'https://gamesdonequick.com/schedule'

    next_gdq_item = ("Next GDQ", textdate)
    days_delta_item = ("Days Until", delta.days if delta else "?")
    schedule_url_item = ("Schedule", "https://gamesdonequick.com/schedule")
    twitch_url_item = ("TTV", "http://www.twitch.tv/gamesdonequick")

    try:
        x = requests.get(url).content
        bs = BeautifulSoup(x)
        run = bs.find("table", {"id": "runTable"}).tbody
        gdqstart = datetime.strptime(run.td.getText(), '%Y-%m-%dT%H:%M:%SZ')
        gdqstart = gdqstart.replace(tzinfo=timezone.utc)
        (game, runner, console, comment, eta, nextgame, nextrunner, nexteta, nextconsole, nextcomment) = getinfo(run,
                                                                                                                 now)
    except:
        return [next_gdq_item + days_delta_item]

    if not nextgame:
        return [next_gdq_item + days_delta_item]
    if now < gdqstart:
        tts = gdqstart - now
        return [next_gdq_item + days_delta_item, schedule_url_item]

    if nextgame == 'done':
        return [next_gdq_item + days_delta_item]

    items = [
        ("Current Game", "setup??" if not game else game + ("" if not comment else " ({})".format(comment))),
        ("Runner", runner),
        ("ETA", eta),
        ("Next Game", nextgame),
        ("Next Runner", nextrunner)
    ]

    return items + [twitch_url_item, schedule_url_item]
