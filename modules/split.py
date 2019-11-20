from typing import List
import random
import discord
from discord.ext import commands


class SplitModule(commands.Cog, name="Split Module"):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot

    # TODO? Only allow ops to use this? I wouldn't want it getting abused.
    @commands.command()
    @commands.guild_only()
    async def split(self, ctx: commands.Context, other_channel: str = None):
        """Splits the members from the channel the user is in into the :other channel"""

        if not other_channel:
            return await ctx.send("Syntax: !split <other voice channel to split to>")

        member: discord.Member = ctx.author
        current_voice_channel: discord.VoiceChannel = member.voice.channel

        # The user must be in a voice channel in order to split
        if not current_voice_channel:
            return await ctx.send("You must be in a voice channel to split")

        # TODO: Verify if all users can actually access that channel
        # Find the actual voice channel with the provided name so that users can be moved to it.
        second_voice_chanel = discord.utils.find(
            lambda channel: channel.name.lower() == other_channel.lower() and channel.type == discord.ChannelType.voice,
            self.bot.get_all_channels())

        # Voice channel must actually exist to move users there.
        if not second_voice_chanel:
            return await ctx.send("Unknown channel!")

        current_members: List[discord.Member] = current_voice_channel.members

        if len(current_members) <= 1:
            return await ctx.send("Need more than 1 user in order to split")

        # Splits the users by shuffling the list and then taking half of it.
        random.shuffle(current_members)
        split_index = len(current_members) // 2
        second_channel_users = current_members[split_index:]

        for member in second_channel_users:
            await member.move_to(second_voice_chanel)


def setup(bot: commands.Bot):
    bot.add_cog(SplitModule(bot))
