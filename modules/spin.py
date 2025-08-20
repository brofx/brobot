import os
import json
import math
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord.ext import commands
import redis.asyncio as redis

try:
    from zoneinfo import ZoneInfo
except ImportError:
    # Python < 3.9 fallback (if needed): pip install backports.zoneinfo
    from backports.zoneinfo import ZoneInfo  # type: ignore

NY_TZ = ZoneInfo("America/New_York")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

CONFIG_PATH = os.getenv("SLOTS_CONFIG_PATH", "slots_config.json")
# How many spins per user per NY-day
DAILY_SPINS = 5
# How many big wins to keep in feed
BIGWINS_FEED_LEN = 20
# Leaderboard length displayed in the channel message
LEADERBOARD_LEN = 10

# Redis keys
K_MESSAGE_ID = "slots:message_id"
K_CHANNEL_ID = "slots:channel_id"
K_LEADERBOARD = "slots:leaderboard"        # sorted set (score = total winnings)
K_BIGWINS = "slots:bigwins"                # list of JSON strings, newest on left
K_CONFIG_DATE = "slots:last_config_date"   # last date (NY) we loaded config (for visibility; not strictly required)

def ny_date_str(dt: Optional[datetime] = None) -> str:
    if dt is None:
        dt = datetime.now(tz=NY_TZ)
    return dt.astimezone(NY_TZ).date().isoformat()

def plays_key(user_id: int, date_str: Optional[str] = None) -> str:
    if date_str is None:
        date_str = ny_date_str()
    return f"slots:plays:{date_str}:{user_id}"

@dataclass
class Item:
    key: str
    emoji: str
    weight: float
    base_value: int
    is_wild: bool = False
    is_multiplier: bool = False
    multiplier: int = 1

@dataclass
class SlotsConfig:
    title: str
    instructions: str
    items: List[Item]
    # When a total spin result >= big_win_threshold, log to recent big wins
    big_win_threshold: int

class SlotsSpinView(discord.ui.View):
    def __init__(self, *, timeout: Optional[float] = None):
        # persistent view (no timeout)
        super().__init__(timeout=timeout)

    @discord.ui.button(label="🎰 Spin", style=discord.ButtonStyle.primary, custom_id="slots:spin")
    async def spin(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: "SlotsCog" = interaction.client.get_cog("SlotsCog")  # type: ignore
        if not cog:
            return await interaction.response.send_message("Slots are temporarily unavailable.", ephemeral=True)

        await cog.handle_spin(interaction)

class SlotsCog(commands.Cog):
    """A 5x5 emoji slots game with daily limits, a persistent channel message, leaderboard, and big-wins feed."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
        self._config: Optional[SlotsConfig] = None
        self._config_loaded_for_date: Optional[str] = None

    async def cog_load(self):
        # Ensure persistent view is registered on load/restart
        self.bot.add_view(SlotsSpinView())

    async def _ensure_config_for_today(self):
        today = ny_date_str()
        if self._config is None or self._config_loaded_for_date != today:
            self._config = await self._load_config()
            self._config_loaded_for_date = today
            # Store visible record of last load date
            await self.r.set(K_CONFIG_DATE, today)

    async def _load_config(self) -> SlotsConfig:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)

        items: List[Item] = []
        for it in raw["items"]:
            items.append(Item(
                key=it["key"],
                emoji=it["emoji"],
                weight=float(it.get("weight", 1)),
                base_value=int(it.get("base_value", 0)),
                is_wild=bool(it.get("is_wild", False)),
                is_multiplier=bool(it.get("is_multiplier", False)),
                multiplier=int(it.get("multiplier", 1)),
            ))

        return SlotsConfig(
            title=raw.get("title", "Slots"),
            instructions=raw.get("instructions", "Press **Spin** to play!"),
            items=items,
            big_win_threshold=int(raw.get("big_win_threshold", 1_000))
        )

    # ---- Commands ----

    @commands.command(name="slots_setup", description="Post/refresh the persistent Slots message in this channel (admin-only).")
    @commands.has_permissions(manage_guild=True)
    async def slots_setup(self, interaction: discord.Interaction):
        await self._ensure_config_for_today()

        # Create or refresh the persistent message in the current channel
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            return await interaction.response.send_message("Please run this in a text channel.", ephemeral=True)

        # Compose initial embed/content
        view = SlotsSpinView()
        embed = await self._compose_main_embed()

        msg_id = await self.r.get(K_MESSAGE_ID)
        chan_id = await self.r.get(K_CHANNEL_ID)
        posted: Optional[discord.Message] = None

        if msg_id and chan_id and int(chan_id) == channel.id:
            try:
                posted = await channel.fetch_message(int(msg_id))
                await posted.edit(embed=embed, view=view, content=None)
            except Exception:
                posted = None  # fall through to send a new one

        if posted is None:
            posted = await channel.send(embed=embed, view=view)

        await self.r.set(K_MESSAGE_ID, posted.id)
        await self.r.set(K_CHANNEL_ID, posted.channel.id)

        await interaction.response.send_message("Slots message is set up (or refreshed) here. 🎰", ephemeral=True)

    @commands.command(name="slots_reload", description="Reload the slots config file (admin-only).")
    @commands.has_permissions(manage_guild=True)
    async def slots_reload(self, interaction: discord.Interaction):
        await self._ensure_config_for_today()  # ensure we have something pre-loaded
        # Force reload regardless of date
        self._config = await self._load_config()
        self._config_loaded_for_date = ny_date_str()
        await self.r.set(K_CONFIG_DATE, self._config_loaded_for_date)

        # Try refreshing the persistent message
        await self._refresh_channel_message()

        await interaction.response.send_message("Slots config reloaded and message refreshed. ✅", ephemeral=True)

    # ---- Interaction handling ----

    async def handle_spin(self, interaction: discord.Interaction):
        await self._ensure_config_for_today()
        assert self._config is not None
        cfg = self._config

        user = interaction.user
        date_str = ny_date_str()
        pkey = plays_key(user.id, date_str)
        plays = int(await self.r.get(pkey) or 0)
        if plays >= DAILY_SPINS:
            return await interaction.response.send_message(
                f"You've used your **{DAILY_SPINS}** spins for today. Come back after midnight ET!",
                ephemeral=True
            )

        # Record play (pre-increment to avoid race on double-click)
        await self.r.incr(pkey)
        await self.r.expire(pkey, 60 * 60 * 48)  # expire in 48h to avoid clutter

        # Perform spin
        grid, total_win, breakdown, mult_used = self._spin_and_score(cfg)

        # Update leaderboard & big-wins feed
        if total_win > 0:
            await self.r.zincrby(K_LEADERBOARD, total_win, str(user.id))
            if total_win >= cfg.big_win_threshold:
                entry = {
                    "user_id": user.id,
                    "username": f"{user.name}#{user.discriminator}" if hasattr(user, "discriminator") else user.name,
                    "amount": total_win,
                    "date": date_str
                }
                await self.r.lpush(K_BIGWINS, json.dumps(entry))
                await self.r.ltrim(K_BIGWINS, 0, BIGWINS_FEED_LEN - 1)

        # Try refreshing the persistent message (not critical if it fails)
        try:
            await self._refresh_channel_message()
        except Exception:
            pass

        remaining = max(0, DAILY_SPINS - (plays + 1))

        # Build ephemeral result
        grid_str = self._render_grid(grid)
        desc_lines = []
        if total_win > 0:
            desc_lines.append(f"**You won:** {total_win:,} {'(multiplied!)' if mult_used else ''}")
        else:
            desc_lines.append("No win this time!")

        if breakdown:
            desc_lines += [f"- {line}" for line in breakdown]

        desc_lines.append(f"**Spins left today:** {remaining}/{DAILY_SPINS}")

        embed = discord.Embed(
            title="🎰 Your Spin Result",
            description="\n".join(desc_lines),
            color=discord.Color.green() if total_win > 0 else discord.Color.dark_gray()
        )
        embed.add_field(name="Grid", value=grid_str, inline=False)

        # Ephemeral response
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---- Core logic ----

    def _render_grid(self, grid: List[List[Item]]) -> str:
        # Render 5x5 emojis in a nice codeblock-like monospace table (Discord doesn't truly monospace emojis, but this is fine)
        lines = []
        for row in grid:
            lines.append(" ".join(cell.emoji for cell in row))
        return "\n".join(lines)

    def _spin_and_score(self, cfg: SlotsConfig) -> Tuple[List[List[Item]], int, List[str], bool]:
        # Build weighted population
        population = cfg.items
        weights = [max(0.0, it.weight) for it in population]

        # 5x5 independent draws
        grid: List[List[Item]] = []
        for _ in range(5):
            row = random.choices(population, weights=weights, k=5)
            grid.append(row)

        # Score:
        # - Consider lines: 5 rows + 5 columns = 10 lines
        # - In each line, find the best-paying non-multiplier symbol treating wilds as substitutes.
        # - If at least 3 matches (including wilds) for that symbol, line pays: base_value * count.
        # - Multipliers (2x, 5x, ..., 1000x) anywhere on the board multiply the TOTAL (product).
        breakdown: List[str] = []
        total = 0

        def score_line(items: List[Item]) -> Tuple[int, Optional[str]]:
            # exclude multipliers from being the anchor symbol
            symbols = [it for it in items if not it.is_multiplier]
            # count wilds
            wild_count = sum(1 for it in items if it.is_wild)
            # group by non-wild symbol key
            by_key: Dict[str, int] = {}
            for it in symbols:
                if not it.is_wild:
                    by_key[it.key] = by_key.get(it.key, 0) + 1

            best_key = None
            best_count = 0
            best_value = 0

            # If there are no non-multiplier symbols (edge case), no payout for this line
            if not by_key and wild_count < 3:
                return 0, None

            # Consider each symbol as anchor, add wilds
            # If no anchors but wilds >= 3, we can pay on the highest base_value symbol in config as a fallback
            candidates: List[Tuple[str, int, int]] = []  # (key, effective_count, base_value)
            if by_key:
                for k, cnt in by_key.items():
                    # find representative item for base_value by key
                    base_item = next((x for x in cfg.items if x.key == k), None)
                    if base_item is None:
                        continue
                    eff = cnt + wild_count
                    candidates.append((k, eff, base_item.base_value))
            else:
                # only wilds found; pay as "wild" if wild has base_value, else 0
                base_item = next((x for x in cfg.items if x.is_wild), None)
                if base_item and wild_count >= 3 and base_item.base_value > 0:
                    candidates.append((base_item.key, wild_count, base_item.base_value))

            for k, eff, base_val in candidates:
                if eff >= 3:
                    # basic linear payout: value * count
                    if eff > best_count or (eff == best_count and base_val > best_value):
                        best_count = eff
                        best_value = base_val
                        best_key = k

            if best_key is None:
                return 0, None

            line_win = best_value * best_count
            # Create a readable name/emoji for breakdown
            ref_item = next((x for x in cfg.items if x.key == best_key), None)
            name = ref_item.emoji if ref_item else best_key
            return line_win, f"{name} x{best_count} → {line_win:,}"

        # rows
        for r in range(5):
            amt, info = score_line(grid[r])
            total += amt
            if info and amt > 0:
                breakdown.append(f"Row {r+1}: {info}")
        # cols
        for c in range(5):
            col = [grid[r][c] for r in range(5)]
            amt, info = score_line(col)
            total += amt
            if info and amt > 0:
                breakdown.append(f"Col {c+1}: {info}")

        # Apply board multipliers
        mults = [it.multiplier for row in grid for it in row if it.is_multiplier and it.multiplier > 1]
        mult_product = 1
        for m in mults:
            mult_product *= m

        mult_used = mult_product > 1
        total *= mult_product

        return grid, total, breakdown, mult_used

    # ---- Channel message (embed) ----

    async def _compose_main_embed(self) -> discord.Embed:
        await self._ensure_config_for_today()
        assert self._config is not None
        cfg = self._config

        # Leaderboard top N
        top = await self.r.zrevrange(K_LEADERBOARD, 0, LEADERBOARD_LEN - 1, withscores=True)
        lb_lines: List[str] = []
        if top:
            for i, (uid_str, score) in enumerate(top, start=1):
                uid = int(uid_str)
                lb_lines.append(f"`{i:>2}.` <@{uid}> — **{int(score):,}**")
        else:
            lb_lines.append("_No entries yet._")

        # Big wins feed (most recent first)
        feed_raw = await self.r.lrange(K_BIGWINS, 0, 9)
        feed_lines: List[str] = []
        if feed_raw:
            for s in feed_raw:
                try:
                    obj = json.loads(s)
                    feed_lines.append(f"🎉 <@{obj['user_id']}> won **{int(obj['amount']):,}** on {obj.get('date', '')}")
                except Exception:
                    continue
        else:
            feed_lines.append("_No big wins yet._")

        last_cfg_date = await self.r.get(K_CONFIG_DATE)
        embed = discord.Embed(
            title=f"{cfg.title} — Daily limit: {DAILY_SPINS} spins/user",
            description=cfg.instructions,
            color=discord.Color.gold()
        )
        embed.add_field(name="Leaderboard (Top 10)", value="\n".join(lb_lines), inline=False)
        embed.add_field(name="Recent Big Wins", value="\n".join(feed_lines), inline=False)
        if last_cfg_date:
            embed.set_footer(text=f"Config last loaded for: {last_cfg_date} (ET)")
        return embed

    async def _refresh_channel_message(self):
        # Re-render main embed and edit the tracked message, if available
        msg_id = await self.r.get(K_MESSAGE_ID)
        chan_id = await self.r.get(K_CHANNEL_ID)
        if not (msg_id and chan_id):
            return

        channel = self.bot.get_channel(int(chan_id))
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            return

        try:
            msg = await channel.fetch_message(int(msg_id))
        except Exception:
            return

        embed = await self._compose_main_embed()
        await msg.edit(embed=embed, view=SlotsSpinView(), content=None)

async def setup(bot: commands.Bot):
    await bot.add_cog(SlotsCog(bot))