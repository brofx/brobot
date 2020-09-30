import asyncio
import itertools
import random
import re
from pathlib import Path
from typing import List, Optional

import discord
from discord.ext import commands

NON_TEXT_MATCH = re.compile(r"[^a-z]")
BACKSTREET_BOYS_OPUS_PATH = (
    Path(__file__).parent / "../assets/backstreet_boys_everybody.opus"
)


class BackstreetBoys(commands.Cog, name="Choose Module"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """You know what it is"""
        channel: discord.TextChannel = message.channel

        if (
            simple_message_compare(message, "everybody")
            or simple_message_compare(message, "rock your body")
            or simple_message_compare(message, "am I original?")
            or simple_message_compare(message, "am I the only one?")
            or simple_message_compare(message, "am I sexual?")
        ):
            await channel.send("yeaaaaaaahh :raised_hands:")
            return

        if simple_message_compare(
            message, "backstreet's back"
        ) or simple_message_compare(message, "backstreet's back alright"):
            message_futures = asyncio.gather(
                channel.send("ALRIGHT!!!"),
                channel.send(
                    "https://tenor.com/view/backstreet-boys-bsb-dance-gif-15271760"
                ),
            )

            # they're not in a voice channel, just await the messages, since we have no where to play music to
            if message.author.voice is None:
                await message_futures
                return

            # create a voice client if it doesn't exist
            vc: Optional[discord.VoiceClient] = discord.utils.find(
                lambda vc: vc.channel == message.author.voice.channel,
                self.bot.voice_clients,
            )
            if vc is None:
                vc = await message.author.voice.channel.connect()

            # play!!!  also the song shouldn't restart if it's already playing, so people can sing along :)
            if not vc.is_playing():
                vc.play(
                    discord.FFmpegOpusAudio(BACKSTREET_BOYS_OPUS_PATH),
                    after=after_disconnect_voice_client(vc, loop=self.bot.loop),
                )

            # and don't forget to wait the messages!  I didn't await earlier, because I want it all triggers ASAP
            await message_futures
            return

        # if anyone in the channel says stop, then stop playing music!
        if (
            simple_message_compare(message, "stop")
            or simple_message_compare(message, "stop please")
            or simple_message_compare(message, "please stop")
        ):
            for vc in self.bot.voice_clients:
                if vc.is_playing():
                    vc.stop()
            await asyncio.gather(*(vc.disconnect() for vc in self.bot.voice_clients))
            return


def simple_message_compare(message: discord.Message, text: str) -> bool:
    if len(message.content) > (len(text) * 5 + len(message.raw_mentions) * 30):
        # performance optimization
        # incase someone posts a lot of text that's obviously not the same as what we're comparing
        return False
    return simplify_text(message.content) == simplify_text(text)


def simplify_text(text: str):
    text = NON_TEXT_MATCH.sub("", text.lower())
    return "".join(c for c, _ in itertools.groupby(text))


def after_disconnect_voice_client(vc: discord.VoiceClient, *, loop=None):
    """This will leave the voice channel when the song is done"""
    loop = loop or asyncio.get_event_loop()

    async def _cleanup(e: Optional[Exception]):
        if vc.is_connected():
            await vc.disconnect()

    def _wrapper(e: Optional[Exception]):
        loop.create_task(_cleanup(e))

    return _wrapper


def setup(bot: commands.Bot):
    bot.add_cog(BackstreetBoys(bot))
