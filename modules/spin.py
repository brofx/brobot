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

# Saved for future use maybe
# { "key": "badscott",  "emoji_id": 761669328356507658, "emoji_name": "scuffedBabish", "emoji_animated": false, "weight": 5,  "base_value": 15 },
# { "key": "badmark",  "emoji_id": 806942508268519444, "emoji_name": "kawaii", "emoji_animated": false, "weight": 5,  "base_value": 15 },
# { "key": "badpelly",  "emoji_id": 806605653510193162, "emoji_name": "hitormiss", "emoji_animated": false, "weight": 5,  "base_value": 15 },

import os
import json
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import time
import logging

import discord
from discord.ext import commands
import redis.asyncio as redis

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

logger = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
SHARE_THREAD_ID = int(os.getenv("SLOTS_SHARE_THREAD_ID", "1407752230425067653"))  # Target thread id for sharing spin results
CONFIG_PATH = os.getenv("SLOTS_CONFIG_PATH", "slots_config.json")

BIGWINS_FEED_LEN = 20
LEADERBOARD_LEN = 10
COOLDOWN_SECONDS = 300  # 5 minutes
MEGA_SPINS_PER_DAY = 3
MEGA_MIN_POINTS = 1000
MEGA_COST_FRACTION = 0.10
MEGA_PAYOUT_MULT = 3.69  # global multiplier applied to the spin total when using MEGA
JACKPOT_MIN_MATCHES = 20
COOLDOWN_SECONDS = 300  # 5 minutes
NORMAL_TOKENS_CAP = 5   # up to 5 stored normal spins

# Redis keys
K_MESSAGE_ID = "slots:message_id"
K_CHANNEL_ID = "slots:channel_id"
K_LEADERBOARD = "slots:leaderboard"        # zset: score = total winnings
K_BIGWINS = "slots:bigwins"                # list of JSON entries (newest left)
K_CONFIG_DATE = "slots:last_config_date"   # date we last loaded config for (NY day)
K_STATS_SPINS = "slots:stats:spins"        # hash user_id -> total spins (all-time)
K_STATS_WINNINGS = "slots:stats:winnings"  # hash user_id -> total winnings (all-time)
K_JACKPOT_POOL = "slots:jackpot:pool"
K_NORMAL_TOKENS = "slots:ntokens:{user_id}"  # int 0..3
K_NORMAL_LAST   = "slots:nlast:{user_id}"    # epoch seconds of last refill calc

# Optional: track mega spins separately
K_STATS_SPINS_MEGA = "slots:stats:spins_mega"      # hash user_id -> total mega spins

K_NORMAL_CD = "slots:cd:{user_id}"                 # string key with TTL=COOLDOWN_SECONDS
# Keep old per-day plays keys for backward compatibility (not used for normal now)
# We'll introduce mega-per-day counter:
def mega_plays_key(user_id: int, date_str: str) -> str:
    return f"slots:megaplays:{date_str}:{user_id}"

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
    weight: float
    base_value: int
    is_wild: bool = False
    is_multiplier: bool = False
    multiplier: int = 1

    # emoji can be a plain Unicode emoji OR a literal Discord mention "<:name:id>" / "<a:name:id>"
    emoji: Optional[str] = None

    # OR specify Discord custom emoji parts directly (preferred if you have the id)
    emoji_id: Optional[int] = None
    emoji_name: Optional[str] = None
    emoji_animated: bool = False

    def token(self) -> str:
        if self.emoji_id and self.emoji_name:
            prefix = "a" if self.emoji_animated else ""
            return f"<{prefix}:{self.emoji_name}:{self.emoji_id}>"
        return self.emoji or ""

@dataclass
class SlotsConfig:
    title: str
    instructions: str
    items: List[Item]
    big_win_threshold: int

class SlotsSpinView(discord.ui.View):
    def __init__(self, *, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)

    @discord.ui.button(label="🎰 Spin", style=discord.ButtonStyle.primary, custom_id="slots:spin:normal")
    async def spin_normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: "SlotsCog" = interaction.client.get_cog("SlotsCog")  # type: ignore
        if not cog:
            return await interaction.response.send_message("Slots are temporarily unavailable.", ephemeral=True)
        await cog.handle_spin(interaction, mega=False)

    @discord.ui.button(label="💥 MEGA Spin", style=discord.ButtonStyle.danger, custom_id="slots:spin:mega")
    async def spin_mega(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: "SlotsCog" = interaction.client.get_cog("SlotsCog")  # type: ignore
        if not cog:
            return await interaction.response.send_message("Slots are temporarily unavailable.", ephemeral=True)
        await cog.handle_spin(interaction, mega=True)

class ResultShareView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        thread_id: int,
        author_id: int,
        share_title: str,
        share_description: str,
        grid_str: str,
        color: discord.Color,
        spin_time: datetime,
    ):
        super().__init__(timeout=180)
        self.bot = bot
        self.thread_id = thread_id
        self.author_id = author_id
        self.share_title = share_title
        self.share_description = share_description
        self.grid_str = grid_str
        self.color = color
        self.spin_time = spin_time

    @discord.ui.button(label="📣 Share to thread", style=discord.ButtonStyle.secondary, custom_id="slots:share_result")
    async def share(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Only the original spinner can share this result.", ephemeral=True)
        if not self.thread_id:
            return await interaction.response.send_message("Share thread is not configured.", ephemeral=True)

        channel = self.bot.get_channel(self.thread_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(self.thread_id)
            except Exception:
                channel = None

        if channel is None or not isinstance(channel, discord.Thread):
            return await interaction.response.send_message("Configured share target is not a valid thread.", ephemeral=True)

        embed = discord.Embed(
            title=self.share_title,
            description=self.share_description,
            color=self.color
        )
        embed.add_field(name="Summary", value=self.grid_str, inline=False)
        embed.timestamp = self.spin_time

        try:
            await channel.send(content=f"Spin by <@{self.author_id}>", embed=embed)
            await interaction.response.send_message("Shared to the thread. 📣", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Couldn't post to the thread (permissions/archived?).", ephemeral=True)

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
                weight=float(it.get("weight", 1)),
                base_value=int(it.get("base_value", 0)),
                is_wild=bool(it.get("is_wild", False)),
                is_multiplier=bool(it.get("is_multiplier", False)),
                multiplier=int(it.get("multiplier", 1)),
                # emoji may be Unicode or a literal custom-emoji mention string
                emoji=it.get("emoji"),
                # or provide parts for a custom emoji
                emoji_id=(int(it["emoji_id"]) if "emoji_id" in it else None),
                emoji_name=it.get("emoji_name"),
                emoji_animated=bool(it.get("emoji_animated", False)),
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

    @commands.command(name="refill_spins", help="Refill NORMAL spins to max (3) for all tracked users and reset today's MEGA spin usage. (manage_guild)")
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def refill_spins(self, ctx: commands.Context):
        now = int(time.time())
        today = ny_date_str()

        # 1) NORMAL spins: set all existing token keys to cap and bump their last timestamps
        set_count = 0
        pipe = self.r.pipeline()
        async for tkey in self.r.scan_iter(match="slots:ntokens:*"):
            uid_part = tkey.rsplit(":", 1)[-1]
            lkey = f"slots:nlast:{uid_part}"
            pipe.set(tkey, NORMAL_TOKENS_CAP)
            pipe.set(lkey, now)
            set_count += 1
            # execute in batches to avoid huge pipelines
            if set_count % 500 == 0:
                await pipe.execute()
                pipe = self.r.pipeline()
        await pipe.execute()

        # 2) MEGA spins: clear today's per-user counters
        cleared_mega = 0
        async for mkey in self.r.scan_iter(match=f"slots:megaplays:{today}:*"):
            cleared_mega += await self.r.delete(mkey)

        await ctx.reply(
            f"Refilled NORMAL spins for **{set_count}** users to {NORMAL_TOKENS_CAP} and "
            f"reset today's MEGA usage (**{cleared_mega}** entries cleared).",
            mention_author=False
        )

    @commands.command(name="slots_hard_reset", help="Hard reset: clears ALL plays, leaderboard, total spins, total winnings, big-wins feed, and jackpot. (manage_guild)")
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def slots_hard_reset(self, ctx: commands.Context):
        deleted_plays = 0
        async for key in self.r.scan_iter(match="slots:plays:*"):
            deleted_plays += await self.r.delete(key)
        async for key in self.r.scan_iter(match="slots:megaplays:*"):
            deleted_plays += await self.r.delete(key)

        del_other = await self.r.delete(
            K_LEADERBOARD,
            K_STATS_SPINS,
            K_STATS_SPINS_MEGA,
            K_STATS_WINNINGS,
            K_BIGWINS,
            K_JACKPOT_POOL
        )

        try:
            await self._refresh_channel_message()
        except Exception:
            pass

        await ctx.reply(
            f"**Hard reset complete.** Cleared `{deleted_plays}` per-day keys and `{del_other}` global keys (incl. jackpot).",
            mention_author=False
        )

    # ---------------- Spin handling (button interaction) ----------------

    async def handle_spin(self, interaction: discord.Interaction, *, mega: bool):
        await self._ensure_config_for_today()
        assert self._config is not None
        cfg = self._config

        user = interaction.user
        user_id = str(user.id)
        spin_time = datetime.now(tz=NY_TZ)
        spin_time_utc_sec = int(spin_time.timestamp())
        date_str = ny_date_str()

        # NORMAL spin: enforce cooldown
        if not mega:
            # token-bucket check
            tokens, next_in = await self._refill_normal_tokens(user.id)
            if tokens <= 0:
                #mins, secs = divmod(next_in, 60)
                return await interaction.response.send_message(
                    f"No normal spins available. Next charge in **<t:{spin_time_utc_sec + next_in}:R>** "
                    f"(you can store up to **{NORMAL_TOKENS_CAP}**).",
                    ephemeral=True
                )
            # consume one token
            await self.r.decr(K_NORMAL_TOKENS.format(user_id=user.id))
        else:
            # MEGA spin: enforce per-day count and cost
            mkey = mega_plays_key(user.id, date_str)
            used = int(await self.r.get(mkey) or 0)
            if used >= MEGA_SPINS_PER_DAY:
                return await interaction.response.send_message(
                    f"You've used your **{MEGA_SPINS_PER_DAY}** MEGA spins for today. Come back after midnight ET!",
                    ephemeral=True
                )

            total_points = int(await self.r.hget(K_STATS_WINNINGS, user_id) or 0)
            if total_points <= MEGA_MIN_POINTS:
                return await interaction.response.send_message(
                    f"MEGA spins require **> {MEGA_MIN_POINTS:,}** points. You currently have **{total_points:,}**.",
                    ephemeral=True
                )
            cost = max(1, int(total_points * MEGA_COST_FRACTION))

            # Deduct cost up-front and add to the progressive jackpot
            pipe = self.r.pipeline()
            pipe.hincrby(K_STATS_WINNINGS, user_id, -cost)
            pipe.zincrby(K_LEADERBOARD, -cost, user_id)
            pipe.incrby(K_JACKPOT_POOL, cost)
            await pipe.execute()

            # Record today's MEGA usage
            mkey = mega_plays_key(int(user_id), date_str)
            await self.r.incr(mkey)
            await self.r.expire(mkey, 60 * 60 * 48)


        # Perform spin
        bonus_mult = MEGA_PAYOUT_MULT if mega else 1.0
        board_size = 7 if mega else 5
        grid, spin_total, breakdown, mult_used, grid_mult, total_mult = self._spin_and_score(
            cfg, bonus_multiplier=bonus_mult, size=board_size
        )
        # %-I to remove the leading zero is unix specific, %#I works on windows.
        
        spin_time_str = spin_time.strftime("%B %d, %Y at %-I:%M %p %Z")

        # --- Progressive Jackpot check (applies to ALL spins) ---
        jackpot_award = 0
        jp = self._jackpot_trigger(grid, cfg)
        if jp:
            async with self.r.pipeline(transaction=True) as p:
                p.get(K_JACKPOT_POOL)
                p.set(K_JACKPOT_POOL, 0)
                res = await p.execute()
            try:
                jackpot_award = int(res[0] or 0)
            except Exception:
                jackpot_award = 0
            if jackpot_award > 0:
                _, eff, token = jp
                breakdown.append(f"💰 **JACKPOT!** {token} reached {eff} (incl. wilds) → +{jackpot_award:,}")

        gross_total = spin_total + jackpot_award

        net_delta = gross_total - (cost if mega else 0)

        await self.r.hincrby(K_STATS_SPINS, user_id, 1)
        if mega:
            await self.r.hincrby(K_STATS_SPINS_MEGA, user_id, 1)
        if gross_total:
            await self.r.hincrby(K_STATS_WINNINGS, user_id, gross_total)
            await self.r.zincrby(K_LEADERBOARD, gross_total, user_id)

        user_name = getattr(interaction.user, "global_name", None) or interaction.user.name

        # Big-wins feed uses net
        if net_delta >= cfg.big_win_threshold or jackpot_award > 0:
            entry = {
                "user_id": int(user_id),
                "username": user_name,
                "amount": net_delta,
                "date": date_str,
                "mega": mega,
                "jackpot": jackpot_award
            }
            await self.r.lpush(K_BIGWINS, json.dumps(entry))
            await self.r.ltrim(K_BIGWINS, 0, BIGWINS_FEED_LEN - 1)

        # Refresh persistent message (best-effort)
        try:
            await self._refresh_channel_message()
        except Exception:
            pass

        # Build ephemeral result
        grid_str = self._render_grid(grid)

        total_spins = int(await self.r.hget(K_STATS_SPINS, user_id) or 0)
        total_wins_accum = int(await self.r.hget(K_STATS_WINNINGS, user_id) or 0)
        avg = (total_wins_accum / total_spins) if total_spins > 0 else 0.0

        desc_lines = []
        title = "🎰 Your Spin Result" if not mega else "💥 MEGA Spin Result"

        if not mega:
            if net_delta > 0:
                desc_lines.append(f"**You won:** {net_delta:,}")
            else:
                desc_lines.append("No win this time!")

            # show remaining tokens and next refill
            tok_left, next_in = await self._refill_normal_tokens(user.id)
            if tok_left < NORMAL_TOKENS_CAP and next_in > 0:
                # mins, secs = divmod(next_in, 60)
                desc_lines.append(f"**Remaining spins:** {tok_left}/{NORMAL_TOKENS_CAP} (+1 <t:{spin_time_utc_sec + next_in}:R>)")
            else:
                desc_lines.append(f"**Remaining spins:** {tok_left}/{NORMAL_TOKENS_CAP}")
        else:
            # MEGA info block
            used_after = int(await self.r.get(mega_plays_key(user.id, date_str)) or 0)
            remaining = max(0, MEGA_SPINS_PER_DAY - used_after)
            # Present gross, cost, net
            gross_line = f"Gross win (incl. MEGA x{MEGA_PAYOUT_MULT:.1f}): **{gross_total:,}**"
            cost_line = f"MEGA cost (10%): **-{cost:,}**"
            net_line = f"**Net change:** **{net_delta:,}**"
            desc_lines.extend([gross_line, cost_line, net_line, f"**MEGA spins left today:** {remaining}/{MEGA_SPINS_PER_DAY}"])

        if breakdown:
            desc_lines += [f"- {line}" for line in breakdown]

        desc_lines.append(f"**Total multiplier:** {total_mult:g}×")
        desc_lines.append(f"**Your totals:** spins={total_spins}, points={total_wins_accum:,}, avg/spin={avg:,.2f}")

        embed = discord.Embed(
            title=title,
            description=grid_str,
            color=discord.Color.orange() if mega else (discord.Color.green() if net_delta > 0 else discord.Color.dark_gray())
        )
        if jackpot_award > 0:
            desc_lines.append(f"💰 **Jackpot paid:** +{jackpot_award:,}")
        
        embed.add_field(name="Summary", value="\n".join(desc_lines), inline=False)
        embed.timestamp = spin_time

        logger.info("\n\t".join([user_name] + desc_lines))

        view = ResultShareView(
            bot=self.bot,
            thread_id=SHARE_THREAD_ID,
            author_id=user.id,
            share_title=title,
            share_description=grid_str,
            grid_str="\n".join(desc_lines),
            color=embed.color,
            spin_time=spin_time_str
        )

        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True, view=view)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True, view=view)

    # ---------------- Core logic ----------------

    async def _refill_normal_tokens(self, user_id: int) -> tuple[int, int]:
        """
        Refill the user's normal-spin tokens (capacity NORMAL_TOKENS_CAP,
        1 token every COOLDOWN_SECONDS). Returns (tokens_after_refill, seconds_until_next_token).
        """
        now = int(time.time())
        tkey = K_NORMAL_TOKENS.format(user_id=user_id)
        lkey = K_NORMAL_LAST.format(user_id=user_id)

        pipe = self.r.pipeline()
        pipe.get(tkey)
        pipe.get(lkey)
        cur_tokens_s, last_ts_s = await pipe.execute()

        # Initialize if absent
        if cur_tokens_s is None or last_ts_s is None:
            tokens = NORMAL_TOKENS_CAP
            last_ts = now
            pipe = self.r.pipeline()
            pipe.set(tkey, tokens)
            pipe.set(lkey, last_ts)
            await pipe.execute()
            return tokens, 0

        tokens = int(cur_tokens_s or 0)
        last_ts = int(last_ts_s or now)

        if tokens < NORMAL_TOKENS_CAP:
            elapsed = max(0, now - last_ts)
            gained = elapsed // COOLDOWN_SECONDS
            if gained > 0:
                tokens = min(NORMAL_TOKENS_CAP, tokens + gained)
                # advance last_ts by whole refill steps actually used
                last_ts = last_ts + gained * COOLDOWN_SECONDS
                pipe = self.r.pipeline()
                pipe.set(tkey, tokens)
                pipe.set(lkey, last_ts)
                await pipe.execute()
        else:
            # at cap: keep clock anchored to now to avoid huge deltas
            last_ts = now
            await self.r.set(lkey, last_ts)

        # seconds until next token (0 if at cap)
        if tokens >= NORMAL_TOKENS_CAP:
            next_in = 0
        else:
            elapsed = max(0, now - last_ts)
            next_in = COOLDOWN_SECONDS - (elapsed % COOLDOWN_SECONDS)

        return tokens, next_in

    def _jackpot_trigger(self, grid: List[List[Item]], cfg: SlotsConfig) -> Optional[Tuple[str, int, str]]:
        """
        Returns (symbol_key, effective_count_including_wilds, display_token) if any non-multiplier symbol
        reaches JACKPOT_MIN_MATCHES across the entire 5x5 board when counting wilds as that symbol.
        Otherwise returns None.
        """
        # Count across entire board
        wild_count = sum(1 for row in grid for it in row if getattr(it, "is_wild", False))
        counts: Dict[str, int] = {}
        for row in grid:
            for it in row:
                if it.is_multiplier or it.is_wild:
                    continue
                counts[it.key] = counts.get(it.key, 0) + 1

        # Choose the best candidate: highest effective count, break ties by base_value
        best: Optional[Tuple[str, int, int, str]] = None  # (key, eff, base_value, token)
        for k, base_cnt in counts.items():
            eff = base_cnt + wild_count
            if eff >= JACKPOT_MIN_MATCHES:
                ref = next((x for x in cfg.items if x.key == k), None)
                if not ref:
                    continue
                base_val = ref.base_value
                token = ref.token() if hasattr(ref, "token") else (ref.emoji if hasattr(ref, "emoji") else k)
                if best is None or eff > best[1] or (eff == best[1] and base_val > best[2]):
                    best = (k, eff, base_val, token)

        if best:
            k, eff, _, token = best
            return (k, eff, token)
        return None

    def _render_grid(self, grid: List[List[Item]]) -> str:
        return "\n".join(" ".join(cell.token() for cell in row) for row in grid)

    def _spin_and_score(
        self,
        cfg: SlotsConfig,
        *,
        bonus_multiplier: float = 1.0,
        size: int = 5
    ) -> Tuple[List[List[Item]], int, List[str], bool, int, float]:
        """
        Returns:
        grid,
        total_after_multipliers (int, excludes jackpot),
        breakdown (list[str]),
        mult_used (bool),
        grid_multiplier (int, product of in-grid multipliers),
        total_multiplier (float, grid_multiplier * bonus_multiplier)
        """
        population = cfg.items
        weights = [max(0.0, it.weight) for it in population]

        # draw grid
        grid: List[List[Item]] = []
        for _ in range(size):
            row = random.choices(population, weights=weights, k=size)
            grid.append(row)

        breakdown: List[str] = []
        total_base = 0

        def score_line(items: List[Item]) -> Tuple[int, Optional[str]]:
            symbols = [it for it in items if not it.is_multiplier]
            wild_count = sum(1 for it in items if getattr(it, "is_wild", False))
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
                base_item = next((x for x in cfg.items if getattr(x, "is_wild", False)), None)
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
            name = ref_item.token() if ref_item and hasattr(ref_item, "token") else (ref_item.emoji if ref_item else best_key)
            return line_win, f"{name} x{best_count} → {line_win:,}"

        # rows
        for r in range(size):
            amt, info = score_line(grid[r])
            total_base += amt
            if info and amt > 0:
                breakdown.append(f"Row {r+1}: {info}")
        # cols
        for c in range(size):
            col = [grid[r][c] for r in range(size)]
            amt, info = score_line(col)
            total_base += amt
            if info and amt > 0:
                breakdown.append(f"Col {c+1}: {info}")

        # Multipliers in-grid
        grid_mult = 1
        for it in (cell for row in grid for cell in row):
            if getattr(it, "is_multiplier", False) and it.multiplier > 1:
                grid_mult *= it.multiplier

        total_mult = grid_mult * (bonus_multiplier if bonus_multiplier else 1.0)
        mult_used = total_mult > 1.0
        total_after = int(total_base * total_mult)

        return grid, total_after, breakdown, mult_used, grid_mult, total_mult

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
                lb_lines.append(f"`{i:>2}.` <@{uid}> — **{total_wins:,}** | spins: **{spins}** | avg: **{avg:,.2f}**")
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
        pool_val = int(await self.r.get(K_JACKPOT_POOL) or 0)
        embed = discord.Embed(
            title=f"{cfg.title} — Daily limit: {MEGA_SPINS_PER_DAY} MEGA spins/user",
            description=cfg.instructions,
            color=discord.Color.gold()
        )
        embed.add_field(name="Progressive Jackpot (20+ Matching Symbols)", value=f"{pool_val:,}", inline=True)
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
