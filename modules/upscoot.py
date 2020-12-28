import asyncio
import os

import discord
import redis
from discord.ext import commands


class Upscoot(commands.Cog, name="Upscoot"):
    def __init__(self, bot: commands.Bot):
        self.pubsub = None
        self.bot = bot
        self.redis = redis.Redis(host="localhost", port=6379, db=5, decode_responses=True, charset="utf-8")
        self.pubsub_thread = self.bot.loop.create_task(self.subscription_thread())

    def cog_unload(self):
        self.pubsub.close()

    async def subscription_thread(self):
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(789152518202064916)
        pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe("upscoot")

        while not self.bot.is_closed() and pubsub.subscribed:
            msg = pubsub.get_message()
            if msg:
                ext = os.path.splitext(msg["data"].lower())[-1]
                embed: discord.Embed = discord.Embed()
                if ext in [".png", ".gif", ".jpeg", ".jpg", ".svg"]:
                    embed.set_image(url=msg["data"])
                    await channel.send(embed=embed)
                elif ext in [".mp4", ".avi", ".webm", ".webp", ".mov", ".ogg", ".mp3", ".wav"]:
                    await channel.send(msg["data"])
            else:
                await asyncio.sleep(1)


def setup(bot: commands.Bot):
    bot.add_cog(Upscoot(bot))
