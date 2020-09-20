from typing import List
import random
import discord
from discord import Role

from discord.ext import commands


class GameTag(commands.Cog, name="Game Tag"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="addgroup")
    @commands.guild_only()
    @commands.has_any_role("Operator")
    async def add_group(self, ctx: commands.Context, *, group: str = None):
        """Create a game role to tag a group of players"""
        if not group:
            return await ctx.send("Syntax: !addgroup <group name>")

        # Check to see if the role already exists
        role_result = discord.utils.find(
            lambda role: role.name.replace("^", "").lower() == group.replace("^", "").lower(), ctx.guild.roles)

        if role_result:
            return await ctx.send("That group already exists")

        # Create the role
        new_role: Role = await ctx.guild.create_role(name=group + "^", mentionable=True)
        return await ctx.send("Created {}".format(new_role.mention))

    @commands.command(name="joingroup")
    @commands.guild_only()
    async def join_group(self, ctx: commands.Context, *, group: str = None):
        """Adds the user to the specified group if it exists"""
        if not group:
            return await ctx.send("Syntax: !joingroup <group name>")

        role_result: Role = discord.utils.find(
            lambda role: role.name.replace("^", "").lower() == group.replace("^", "").lower(), ctx.guild.roles)
        if not role_result:
            return await ctx.send("That group doesn't exist yet.")
        member: discord.Member = ctx.author

        if discord.utils.find(lambda role: role_result.id == role.id, member.roles):
            return await ctx.send("You are already in that group.")

        if not role_result.name.endswith("^"):
            return await ctx.send("You can't join that group.")

        await member.add_roles(role_result, atomic=True)
        return await ctx.send("You will now be notified when `@{}` is tagged.".format(role_result.name))

    @commands.command(name="leavegroup")
    @commands.guild_only()
    @commands.has_any_role("Member")
    async def leave_group(self, ctx: commands.Context, *, group: str = None):
        """Removes the user from the specified group if it exists"""
        if not group:
            return await ctx.send("Syntax: !leavegroup <group name>")

        role_result: Role = discord.utils.find(
            lambda role: role.name.replace("^", "").lower() == group.replace("^", "").lower(), ctx.guild.roles)
        if role_result:
            return await ctx.send("That group doesn't exist.")

        member: discord.Member = ctx.author

        if discord.utils.find(lambda role: role_result.id == role.id, member.roles):
            await member.remove_roles(role_result, atomic=True)
            return await ctx.send("You have been removed from `@{}`.".format(role_result.name))


def setup(bot: commands.Bot):
    bot.add_cog(GameTag(bot))
