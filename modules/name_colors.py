from random import choice
from typing import List

import discord
from discord.ext import commands

VALID_COLORS: List[str] = ["green", "purple", "red", "blue", "yellow", "orange", "white", "pink", "cyan"]
COLOR_ROLES: List[str] = ["Team Green", "Team Purple", "Team Red", "Team Blue", "Team Yellow", "Team Orange",
                          "Team White", "Team Pink", "color-cyan"]


class NameColors(commands.Cog, name="Name Colors"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    @commands.has_any_role("Member", "Operator")
    async def color(self, ctx: commands.Context, color: str = None):
        color: str = None if not color else color.lower()

        # Verify that the color entered is a valid
        if not color or color not in VALID_COLORS:
            return await ctx.send(
                "Choose a nickname color by saying \"!color <color>\". Valid colors: {}".format(
                    ", ".join(VALID_COLORS)))

        member: discord.Member = ctx.author

        # TODO figure out how to cache the list of roles so this lookup doesn't need to happen every time
        roles_to_remove: List[discord.Role] = [role for role in member.roles if role.name in COLOR_ROLES]

        # Since the indexes for colors and their associated roles are identical, the role can be looked up using the
        # index of the provided color
        color_index: int = VALID_COLORS.index(color)
        role_to_add: discord.Role = [role for role in ctx.guild.roles if role.name == COLOR_ROLES[color_index]][0]

        # If a member is setting their own color, remove the auto granted team so that future resets won't affect them.
        auto_role = discord.utils.find(lambda role: role.name == "Auto Granted Team", ctx.guild.roles)

        # Only add the role if they don't have it.
        if role_to_add not in member.roles:
            await member.remove_roles(*roles_to_remove, auto_role, atomic=True)
            await member.add_roles(role_to_add, atomic=True)

    @commands.command(name="allcolor")
    @commands.guild_only()
    @commands.has_any_role("Operator")
    async def set_all_colors(self, ctx: commands.Context):
        # Used to determine all members who were automatically granted a team, used if we would like to undo.
        # auto_granted_members: List[discord.Member] = [member for member in ctx.guild.members if
        #                                               "Auto Granted Team" in [r.name for r in member.roles]]

        no_team_members = list(filter(lambda member: "Member" in [r.name for r in member.roles] and not any(
            role.name in COLOR_ROLES for role in member.roles), ctx.guild.members))

        all_team_roles: List[discord.Role] = [role for role in ctx.guild.roles if role.name in COLOR_ROLES]
        auto_role = discord.utils.find(lambda role: role.name == "Auto Granted Team", ctx.guild.roles)

        if True:
            for member in no_team_members:
                print("Updating: " + member.display_name)
                await member.add_roles(auto_role, choice(all_team_roles))
                # await member.remove_roles(*all_team_roles, auto_role)
                # await member.remove_roles(*all_team_roles)

        # Used to determine all members who were automatically granted a team, used if we would like to undo.
        # else:
        #     for member in auto_granted_members:
        #         member.remove_roles(*all_team_roles)

        return await ctx.send("Number of members without colors: {}, {}".format(len(no_team_members), ", ".join(
            [m.display_name for m in no_team_members])))


async def setup(bot: commands.Bot):
    await bot.add_cog(NameColors(bot))
