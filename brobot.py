import os

import discord
from discord.ext import commands

# import logging
# logging.basicConfig(level=logging.INFO)

discord_key: str = os.getenv("DISCORD_KEY")

brobot_modules = [
    "modules.base",
    "modules.name_colors",
    "modules.roll",
    "modules.stocks",
    "modules.silly",
    "modules.f1",
    "modules.urbandict",
    "modules.choose",
    "modules.split",
    "modules.8ball",
    "modules.activity",
    "modules.gdq",
    "modules.egs",
    "modules.kym",
    "modules.hltb",
    "modules.game_tag",
    "modules.backstreet_boys",
    "modules.nubeer",
]


def init_bot(bot: commands.Bot):
    for module in brobot_modules:
        try:
            bot.load_extension(module)
            print("Loaded: {}".format(module))
        except commands.ExtensionError as error:
            print("Error loading {}: {}".format(module, error))
    return bot


intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.emojis = True
intents.voice_states = True
intents.guild_messages = True

brobot = commands.Bot(command_prefix="!", description='Brobot', intents=intents)

if __name__ == '__main__':
    if not discord_key:
        print("You must set the DISCORD_KEY env variable.")
        exit()

    init_bot(brobot)
else:
    print("This class is not meant to be imported.")
    exit()


@brobot.event
async def on_ready():
    print(f'\n\nLogged in as: {brobot.user.name} - {brobot.user.id}\nVersion: {discord.__version__}\n')
    print(f'Successfully logged in and booted...!')


brobot.run(discord_key, bot=True)
