# slots_cog.py
# Discord.py (v2.3+) extension that adds a 5x5 emoji slots game with daily limits, leaderboard, and a single persistent channel message.
# Changes per request:
# - Use commands.command (prefix commands) for admin actions instead of app_commands
# - Add /slots_reset (prefix: !slots_reset) to reset daily plays for today
# - Daily spins: 5 per user (midnight America/New_York reset)
# - Track total spins per user; leaderboard displays total winnings, total spins, and avg per spin
#
# Setup:
# 1) pip install -U "discord.py>=2.3.2" "redis>=5.0.0"
# 2) Put a config file next to this script named "slots_config.json" (example below).
# 3) Load the extension in your bot: await bot.load_extension("slots_cog")
# 4) Run !slots_setup in the target channel (manage_guild required) to post/refresh the persistent message.
#
# Notes:
# - The Spin button uses interactions and returns an ephemeral result to prevent channel spam.
# - Persistent views survive restarts via bot.add_view(SlotsSpinView()) in cog_load().

import os
import json
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
    from backports.zoneinfo import ZoneInfo  # type: ignore

NY_TZ = ZoneInfo("America/New_York")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

CONFIG_PATH = os.getenv("SLOTS_CONFIG_PATH", "slots_config.json")
DAILY_SPINS = 5
BIGWINS_FEED_LEN = 20
LEADERBOARD_LEN = 10

# Redis keys
K_MESSAGE_ID = "slots:message_id"
K_CHANNEL_ID = "slots:channel_id"
K_LEADERBOARD = "slots:leaderboard"        # zset: score = total winnings
K_BIGWINS = "slots:bigwins"                # list of JSON entries (newest left)
K_CONFIG_DATE = "slots:last_config_date"   # date we last loaded config for (NY day)
K_STATS_SPINS = "slots:stats:spins"        # hash user_id -> total spins (all-time)
K_STATS_WINNINGS = "slots:stats:winnings"  # hash user_id -> total winnings (all-time)

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
    big_win_threshold: int

class SlotsSpinView(discord.ui.View):
    def __init__(self, *, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)

    @discord.ui.button(label="🎰 Spin", style=discord.ButtonStyle.primary, custom_id="slots:spin")
    async def spin(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: "SlotsCog" = interaction.client.get_cog("SlotsCog")  # type: ignore
        if not cog:
            return await interaction.response.send_message("Slots are temporarily unavailable.", ephemeral=True)
        await cog.handle_spin(interaction)

class SlotsCog(commands.Cog):
    """5x5 emoji slots with daily limits, persistent channel message, leaderboard, and big-wins feed."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
        self._config: Optional[SlotsConfig] = None
        self._config_loaded_for_date: Optional[str] = None

    async def cog_load(self):
        self.bot.add_view(SlotsSpinView())

    async def _ensure_config_for_today(self):
        today = ny_date_str()
        if self._config is None or self._config_loaded_for_date != today:
            self._config = await self._load_config()
            self._config_loaded_for_date = today
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

    # ---------------- Admin (prefix) commands ----------------

    @commands.command(name="slots_setup", help="Post/refresh the persistent Slots message in this channel. (manage_guild)")
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def slots_setup(self, ctx: commands.Context):
        await self._ensure_config_for_today()

        if not isinstance(ctx.channel, (discord.TextChannel, discord.Thread)):
            return await ctx.reply("Please run this in a text channel.", mention_author=False)

        view = SlotsSpinView()
        embed = await self._compose_main_embed()

        msg_id = await self.r.get(K_MESSAGE_ID)
        chan_id = await self.r.get(K_CHANNEL_ID)
        posted: Optional[discord.Message] = None

        if msg_id and chan_id and int(chan_id) == ctx.channel.id:
            try:
                posted = await ctx.channel.fetch_message(int(msg_id))
                await posted.edit(embed=embed, view=view, content=None)
            except Exception:
                posted = None

        if posted is None:
            posted = await ctx.channel.send(embed=embed, view=view)

        await self.r.set(K_MESSAGE_ID, posted.id)
        await self.r.set(K_CHANNEL_ID, posted.channel.id)

        await ctx.reply("Slots message is set up (or refreshed) here. 🎰", mention_author=False)

    @commands.command(name="slots_reload", help="Reload the slots config file and refresh the message. (manage_guild)")
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def slots_reload(self, ctx: commands.Context):
        await self._ensure_config_for_today()
        self._config = await self._load_config()
        self._config_loaded_for_date = ny_date_str()
        await self.r.set(K_CONFIG_DATE, self._config_loaded_for_date)
        await self._refresh_channel_message()
        await ctx.reply("Slots config reloaded and message refreshed. ✅", mention_author=False)

    @commands.command(name="slots_reset", help="Reset today's spin counters (NY day) so everyone can spin again. (manage_guild)")
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def slots_reset(self, ctx: commands.Context):
        # Delete all keys matching today's plays counters
        pattern = f"slots:plays:{ny_date_str()}:*"
        deleted = 0
        async for key in self.r.scan_iter(match=pattern):
            await self.r.delete(key)
            deleted += 1
        await ctx.reply(f"Reset today's spin counters. Cleared **{deleted}** entries.", mention_author=False)

    # ---------------- Spin handling (button interaction) ----------------

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

        # Pre-increment plays (prevents double-click race)
        await self.r.incr(pkey)
        await self.r.expire(pkey, 60 * 60 * 48)

        # Perform spin
        grid, total_win, breakdown, mult_used = self._spin_and_score(cfg)

        # Update stats (all-time)
        await self.r.hincrby(K_STATS_SPINS, str(user.id), 1)
        if total_win > 0:
            await self.r.hincrby(K_STATS_WINNINGS, str(user.id), total_win)
            await self.r.zincrby(K_LEADERBOARD, total_win, str(user.id))
            if total_win >= cfg.big_win_threshold:
                entry = {
                    "user_id": user.id,
                    "username": getattr(user, "global_name", None) or user.name,
                    "amount": total_win,
                    "date": date_str
                }
                await self.r.lpush(K_BIGWINS, json.dumps(entry))
                await self.r.ltrim(K_BIGWINS, 0, BIGWINS_FEED_LEN - 1)
        else:
            # ensure total winnings hash exists even if zero (optional)
            await self.r.hsetnx(K_STATS_WINNINGS, str(user.id), 0)

        # Refresh persistent message (best-effort)
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

        # Compute user's all-time stats for this footer
        total_spins = int(await self.r.hget(K_STATS_SPINS, str(user.id)) or 0)
        total_wins_accum = int(await self.r.hget(K_STATS_WINNINGS, str(user.id)) or 0)
        avg = (total_wins_accum / total_spins) if total_spins > 0 else 0.0

        desc_lines.append(f"**Spins left today:** {remaining}/{DAILY_SPINS}")
        desc_lines.append(f"**Your totals:** spins={total_spins}, winnings={total_wins_accum:,}, avg/spin={avg:.2f}")

        embed = discord.Embed(
            title="🎰 Your Spin Result",
            description="\n".join(desc_lines),
            color=discord.Color.green() if total_win > 0 else discord.Color.dark_gray()
        )
        embed.add_field(name="Grid", value=grid_str, inline=False)

        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------------- Core logic ----------------

    def _render_grid(self, grid: List[List[Item]]) -> str:
        return "\n".join(" ".join(cell.emoji for cell in row) for row in grid)

    def _spin_and_score(self, cfg: SlotsConfig) -> Tuple[List[List[Item]], int, List[str], bool]:
        population = cfg.items
        weights = [max(0.0, it.weight) for it in population]

        grid: List[List[Item]] = []
        for _ in range(5):
            row = random.choices(population, weights=weights, k=5)
            grid.append(row)

        breakdown: List[str] = []
        total = 0

        def score_line(items: List[Item]) -> Tuple[int, Optional[str]]:
            symbols = [it for it in items if not it.is_multiplier]
            wild_count = sum(1 for it in items if it.is_wild)
            by_key: Dict[str, int] = {}
            for it in symbols:
                if not it.is_wild:
                    by_key[it.key] = by_key.get(it.key, 0) + 1

            if not by_key and wild_count < 3:
                return 0, None

            candidates: List[Tuple[str, int, int]] = []
            if by_key:
                for k, cnt in by_key.items():
                    base_item = next((x for x in cfg.items if x.key == k), None)
                    if base_item is None:
                        continue
                    eff = cnt + wild_count
                    candidates.append((k, eff, base_item.base_value))
            else:
                base_item = next((x for x in cfg.items if x.is_wild), None)
                if base_item and wild_count >= 3 and base_item.base_value > 0:
                    candidates.append((base_item.key, wild_count, base_item.base_value))

            best_key = None
            best_count = 0
            best_value = 0
            for k, eff, base_val in candidates:
                if eff >= 3 and (eff > best_count or (eff == best_count and base_val > best_value)):
                    best_key, best_count, best_value = k, eff, base_val

            if best_key is None:
                return 0, None

            line_win = best_value * best_count
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

        # Multipliers anywhere multiply TOTAL (stacking)
        mults = [it.multiplier for row in grid for it in row if it.is_multiplier and it.multiplier > 1]
        mult_product = 1
        for m in mults:
            mult_product *= m
        mult_used = mult_product > 1
        total *= mult_product

        return grid, total, breakdown, mult_used

    # ---------------- Persistent channel message ----------------

    async def _compose_main_embed(self) -> discord.Embed:
        await self._ensure_config_for_today()
        assert self._config is not None
        cfg = self._config

        # Top by total winnings
        top = await self.r.zrevrange(K_LEADERBOARD, 0, LEADERBOARD_LEN - 1, withscores=True)

        lb_lines: List[str] = []
        if top:
            # Fetch spins & winnings hashes in one go
            spins_map = await self.r.hgetall(K_STATS_SPINS)
            win_map = await self.r.hgetall(K_STATS_WINNINGS)
            for i, (uid_str, score) in enumerate(top, start=1):
                uid = int(uid_str)
                spins = int(spins_map.get(uid_str, "0"))
                total_wins = int(win_map.get(uid_str, str(int(score))))  # fallback to zset score if hash missing
                avg = (total_wins / spins) if spins > 0 else 0.0
                lb_lines.append(f"`{i:>2}.` <@{uid}> — **{total_wins:,}** | spins: **{spins}** | avg: **{avg:.2f}**")
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
        msg_id = await self.r.get(K_MESSAGE_ID)
        chan_id = await self.r.get(K_CHANNEL_ID)
        if not (msg_id and chan_id):
            return

        channel = self.bot.get_channel(int(chan_id))
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return

        try:
            msg = await channel.fetch_message(int(msg_id))
        except Exception:
            return

        embed = await self._compose_main_embed()
        await msg.edit(embed=embed, view=SlotsSpinView(), content=None)

async def setup(bot: commands.Bot):
    await bot.add_cog(SlotsCog(bot))
