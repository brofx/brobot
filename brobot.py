import discord
import asyncio
import random
import os

from discord import ChannelType

client = discord.Client()


@client.event
@asyncio.coroutine
def on_ready():
    print("Logged in as: {} {}".format(client.user.name, client.user.id))


@client.event
@asyncio.coroutine
def on_message(message):
    print("HereX")
    if message.content.lower() == "hi brobot":
        yield from client.send_message(message.channel, "hi {}".format(message.author.name))
    elif message.content.lower().startswith("!split"):
        first_channel = message.author.voice.voice_channel
        if first_channel is None:
            yield from client.send_message(message.channel, "You must be in a channel to split.".format(message.author.name))
            return

        second_channel_name = message.content.split("!split")[1].strip()
        if second_channel_name is None:
            yield from client.send_message(message.channel, "Syntax: !split <channel>; This will split users from the channel you're in into the provided channel.")
            return

        second_channel = discord.utils.find(lambda c: c.name.lower() == second_channel_name.lower() and c.type == ChannelType.voice, client.get_all_channels())
        if second_channel is None:
            yield from client.send_message(message.channel, "I couldn't find that channel.")
            return
        # Get a list of all users in the channel the user is in
        users_to_split = first_channel.voice_members
        if len(users_to_split) <= 1:
            yield from client.send_message(message.channel, "Not enough people to split.")
            return

        # shuffle and split
        random.shuffle(users_to_split)
        split_index = len(users_to_split) // 2
        second_channel_users = users_to_split[split_index:]

        # move other members to second channel
        for user in second_channel_users:
            print("Moving {} to {}".format(user.name, second_channel.name))
            yield from client.move_member(user, second_channel)

        yield from client.send_message(message.channel, "{} -> {}".format(", ".join([u.name for u in second_channel_users]), second_channel.name))


if __name__ == "__main__":
    key = os.environ.get('DISCORD_KEY')
    if key is None:
        print("Please set the DISCORD_KEY env var.")
    else:
        client.run(key)

