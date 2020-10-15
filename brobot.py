import os

import discord
from discord.ext import commands

# import logging
# logging.basicConfig(level=logging.INFO)

discord_key: str = os.getenv("DISCORD_KEY")

brobot_modules = [
    "modules.8ball",
    "modules.activity",
    "modules.backstreet_boys",
    "modules.base",
    "modules.choose",
    "modules.egs",
    "modules.f1",
    "modules.game_tag",
    "modules.gdq",
    "modules.hltb",
    "modules.imdb",
    "modules.kym",
    "modules.name_colors",
    "modules.nubeer",
    "modules.poll",
    "modules.roll",
    "modules.silly",
    "modules.split",
    "modules.stocks",
    "modules.urbandict"]


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
