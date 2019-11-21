from typing import List
import discord
from discord.ext import commands

VALID_COLORS: List[str] = ["green", "purple", "red", "blue", "yellow", "orange", "white"]
COLOR_ROLES: List[str] = ["Team Green", "Team Purple", "Team Red", "Team Blue", "Team Yellow", "Team Orange", "Team White"]


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
        color_index: str = VALID_COLORS.index(color)
        role_to_add: discord.Role = [role for role in ctx.guild.roles if role.name == COLOR_ROLES[color_index]][0]

        # Only add the role if they don't have it.
        if role_to_add not in member.roles:
            await member.remove_roles(*roles_to_remove, atomic=True)
            await member.add_roles(role_to_add, atomic=True)


def setup(bot: commands.Bot):
    bot.add_cog(NameColors(bot))
