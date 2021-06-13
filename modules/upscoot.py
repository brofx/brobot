import random
import threading
import time
import os

import discord
import asyncio
from discord.ext import commands
import redis


class Upscoot(commands.Cog, name="Upscoot"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.redis = redis.Redis(host="localhost", port=6379, db=5, decode_responses=True, charset="utf-8")
        self.pubsub_thread = self.bot.loop.create_task(self.subscription_thread())

    def cog_unload(self):
        self.pubsub.close()
        self.pubsub = None

    async def subscription_thread(self):
        #print("Waiting...")
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(789152518202064916)
        pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe("upscoot_discord")
        #print("Ready!, closed: {}, subscribed: {}".format(self.bot.is_closed(), self.pubsub.subscribed))
        while not self.bot.is_closed() and pubsub.subscribed:
            #print("Getting message")
            msg = pubsub.get_message()
            #print("Msg: {}".format(msg))
            if msg:
                ext = os.path.splitext(msg["data"].lower())[-1]
                #print("Ext: {}".format(ext))
                embed: discord.Embed = discord.Embed()
                #if ext in [".mp4"]:
                #    pass
                if ext in [".png", ".gif", ".jpeg", ".jpg", ".svg"]:
                    #print("Sending...")
                    embed.set_image(url=msg["data"])
                    await channel.send(embed=embed)
                elif ext in [".mp4", ".avi", ".webm", ".webp", ".mov", ".ogg", ".mp3", ".wav"]:
                    await channel.send(msg["data"])
            else:
                #print("Sleeping...")
                await asyncio.sleep(1)
        #print("Exited loop!, closed: {}, subscribed: {}".format(self.bot.is_closed(), self.pubsub.subscribed))

def setup(bot: commands.Bot):
    bot.add_cog(Upscoot(bot))
