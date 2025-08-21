from __future__ import annotations

"""
Discord Cog: randomize_cards (with embeds)

Usage (prefix command):
  !randomize_cards [event_slug]

Behavior:
  - If event_slug is provided, fetch participants for that event and group them.
  - If event_slug is omitted, look up events happening *today* for the configured league
    and use the first one found.

Configuration:
  - Pass the league URL slug when constructing the cog (default provided).
  - Optionally pass a timezone string for "today" comparisons.

This cog depends on the DiscGolfLeague scraper & grouping util.
"""

from typing import Optional, List
from datetime import datetime, date

import discord
from discord.ext import commands

# Import the scraper and util. Adjust the import to your project layout.
from udisc import DiscGolfLeague, group_participants, Participant  # type: ignore

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None  # type: ignore
import logging
logger = logging.getLogger(__name__)

EMBED_COLOR_DEFAULT = discord.Color.blurple()
EMBED_COLOR_UPCOMING = discord.Color.green()
EMBED_COLOR_PAST = discord.Color.red()


class RandomizeCards(commands.Cog):
    """Discord cog that fetches an event's participants and randomizes them into cards (groups)."""

    def __init__(self, bot: commands.Bot, *, league_slug: str = "brfx-4UTzW0", timezone: str = "America/New_York") -> None:
        self.bot = bot
        self.league_slug = league_slug
        self.timezone = timezone
        # Reuse the scraper with the same timezone logic.
        logger.info("Setting up")
        self.league = DiscGolfLeague(league_slug, timezone=timezone)

    # --------------- Helpers ---------------
    def _today(self) -> date:
        if ZoneInfo is not None:
            try:
                return datetime.now(ZoneInfo(self.timezone)).date()
            except Exception:
                pass
        return date.today()

    def _pick_today_event_slug(self) -> Optional[str]:
        """Find the first event happening *today* for this league and return its slug.
        Returns None if no such event exists.
        """
        # Pull some upcoming + some past to catch edge cases around today.
        events = self.league.get_events(num_upcoming=5, num_past=3)
        today = self._today()
        todays = [e for e in events if e.event_date == today]
        if not todays:
            return None
        # Prefer upcoming entries first if both sections contain the same date.
        todays.sort(key=lambda e: (not e.is_upcoming, e.name))
        return todays[0].event_slug

    def _build_groups_embed(self, *, event_slug: str, participants: List[Participant]) -> discord.Embed:
        """Build a nice-looking embed with one field per card."""
        url = f"https://udisc.com/events/{event_slug}/participants"
        count = len(participants)
        # Choose a thumbnail if any avatar is available
        thumb_url = next((p.avatar_url for p in participants if p.avatar_url), None)

        # If we can find the event in the league cache, color by status
        color = EMBED_COLOR_DEFAULT
        try:
            # Small lookahead to find the event and decide color by is_upcoming
            events = self.league.get_events(num_upcoming=5, num_past=5)
            match = next((e for e in events if e.event_slug == event_slug), None)
            if match is not None:
                color = EMBED_COLOR_UPCOMING if match.is_upcoming else EMBED_COLOR_PAST
        except Exception:
            pass

        embed = discord.Embed(
            title="Randomized Cards",
            description=(
                f"Event: `{event_slug}`\n"
                f"Players: **{count}**\n"
            ),
            url=url,
            color=color,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text="UDisc • Randomized by Bot")
        if thumb_url:
            embed.set_thumbnail(url=thumb_url)

        # Compute groups and add fields
        groups = group_participants(participants)
        for i, group in enumerate(groups, start=1):
            name = f"Card {i}"
            # Each field value max 1024 chars; join with newlines
            value_lines = []
            for p in group:
                handle = f" (@{p.username})" if p.username else ""
                value_lines.append(f"• {p.display_name}{handle}")
            value = "\n".join(value_lines) if value_lines else "(empty)"
            embed.add_field(name=name, value=value, inline=False)
        return embed

    # --------------- Command ---------------
    @commands.command(name="randomize_cards")
    @commands.guild_only()
    async def randomize_cards(self, ctx: commands.Context, event_slug: Optional[str] = None):
        """Randomly group participants for an event into cards (groups).

        Usage:
          `!randomize_cards`                 -> uses today's event for this league
          `!randomize_cards <event_slug>`    -> uses the specified event
        """
        # Determine event slug
        slug = event_slug or self._pick_today_event_slug()
        if not slug:
            await ctx.reply(
                embed=discord.Embed(
                    title="Randomized Cards",
                    description=(
                        "No event happening today for this league, and no `event_slug` was provided.\n"
                        f"League: `{self.league_slug}`"
                    ),
                    color=discord.Color.orange(),
                )
            )
            return

        # Fetch participants & group
        try:
            participants = self.league.get_event_participants(slug)
        except Exception as e:
            await ctx.reply(
                embed=discord.Embed(
                    title="Randomized Cards",
                    description=f"Failed to fetch participants for `{slug}`: {e}",
                    color=discord.Color.red(),
                )
            )
            return

        embed = self._build_groups_embed(event_slug=slug, participants=participants)
        await ctx.reply(embed=embed)


# --------------- Cog setup ---------------
async def setup(bot: commands.Bot):  # For discord.py 2.x with extensions
    await bot.add_cog(RandomizeCards(bot))

# If using older discord.py (<2.0), replace with:
# def setup(bot: commands.Bot):
#     bot.add_cog(RandomizeCards(bot))
