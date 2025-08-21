import asyncio
import os

import aiohttp
import discord
from discord.ext import commands

import logging
discord.utils.setup_logging(level=logging.INFO, root=True)
logger = logging.getLogger(__name__)

discord_key: str = os.getenv("DISCORD_KEY")

brobot_modules = ["modules.8ball", "modules.activity", "modules.backstreet_boys", "modules.base", "modules.choose",
                  "modules.egs", "modules.f1", "modules.game_tag", "modules.gdq", "modules.hltb", "modules.imdb",
                  "modules.kym", "modules.name_colors", "modules.nubeer", "modules.poll", "modules.roll",
                  "modules.silly", "modules.split", "modules.stocks", "modules.urbandict", "modules.spin", "modules.dg"]

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.emojis = True
intents.voice_states = True
intents.guild_messages = True
intents.message_content = True


class Brobot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, description="Brobot")

    async def setup_hook(self) -> None:
        self.session = aiohttp.ClientSession()
        await self.init_bot()

    async def on_ready(self):
        logger.info(f'Logged in as: {self.user.name} - {self.user.id}')
        logger.info(f'Version: {discord.__version__}')
        logger.info(f'Successfully logged in and booted...!')

    async def close(self):
        await super().close()
        await self.session.close()

    async def init_bot(self):
        for module in brobot_modules:
            try:
                await self.load_extension(module)
                logger.info("Loaded: {}".format(module))
            except commands.ExtensionError as error:
                logger.error(f"Error loading {module}: %s", error, exc_info=True)


if __name__ == '__main__':
    if not discord_key:
        print("You must set the DISCORD_KEY env variable.")
        exit()
    bot = Brobot()
    bot.run(discord_key, log_handler=None)
else:
    print("This class is not meant to be imported.")
    exit()
