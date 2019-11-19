import discord
from discord.ext import commands

VALID_COLORS = ["green", "purple", "red", "blue", "yellow", "orange", "white"]
COLOR_ROLES = ["Team Green", "Team Purple", "Team Red", "Team Blue", "Team Yellow", "Team Orange", "Team White"]


class NameColors(commands.Cog, name="Name Colors"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # TODO: Require 'member' role
    @commands.command()
    @commands.guild_only()
    async def color(self, ctx: commands.Context, color=None):
        color = None if not color else color.lower()

        if not color or color not in VALID_COLORS:
            return await ctx.send(
                "Choose a nickname color by saying \"!color <color>\". Valid colors: {}".format(
                    ", ".join(VALID_COLORS)))

        member: discord.Member = ctx.author

        # TODO figure out how to cache the list of roles so this lookup doesn't need to happen every time
        roles_to_remove = [role for role in member.roles if role.name in COLOR_ROLES]

        color_index = VALID_COLORS.index(color)
        role_to_add = [role for role in ctx.guild.roles if role.name == COLOR_ROLES[color_index]][0]

        if role_to_add not in member.roles:
            await member.remove_roles(*roles_to_remove, atomic=True)
            await member.add_roles(role_to_add, atomic=True)


def setup(bot: commands.Bot):
    bot.add_cog(NameColors(bot))
