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
from datetime import datetime, timedelta, timezone, time as dtime
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

BIGWINS_FEED_LEN = 5
LEADERBOARD_LEN = 10
COOLDOWN_SECONDS = 300  # 5 minutes
MEGA_SPINS_PER_DAY = 5
MEGA_MIN_POINTS = 1000
MEGA_COST_FRACTION = 0.10
MEGA_PAYOUT_MULT = 4.20  # global multiplier applied to the spin total when using MEGA
JACKPOT_NORMAL_INC_FRACTION = 0.015 # 1.5%
JACKPOT_MIN_MATCHES = 20
COOLDOWN_SECONDS = 300  # 5 minutes
NORMAL_TOKENS_CAP = 6   # up to 5 stored normal spins
BIGGEST_SPINS_LEN = 5
DUEL_TIMEOUT_SECONDS = 60 * 30 # 30 minutes
DUEL_FEE_FRACTION = 0.10  # 10%
DUEL_LEADERBOARD_LEN = 5
REFRESH_THROTTLE_SECONDS = 10
MEGA_LOSS_BONUS_INITIAL = 5   # first bonus multiplier after 1 consecutive net-loss
MEGA_LOSS_BONUS_SCALE   = 5   # geometric growth factor (5 -> 5,25,125,...)
MEGA_LOSS_STREAK_LB_LEN = 5

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
K_BIGGEST_SPINS = "slots:biggest_spins"
K_BIGGEST_SPINS_MEGA = "slots:biggest_spins:mega"
K_BIGGEST_SPINS_NORMAL = "slots:biggest_spins:normal"
K_DUEL_REQ = "slots:duel:req:{message_id}"      # JSON: open duel request
K_DUEL_ACTIVE_BY_USER = "slots:duel:active_by_user"  # hash user_id -> message_id
K_DUEL_LOCK = "slots:duel:lock:{message_id}"    # simple accept lock
K_DUEL_WINS = "slots:duel:wins"                 # hash user_id -> wins
K_DUEL_LOSSES = "slots:duel:losses"             # hash user_id -> losses
K_SIGMA_TOKENS = "slots:sigma:tokens:{user_id}"
K_SIGMA_LAST   = "slots:sigma:last:{user_id}"
K_SIGMA_LOCK   = "slots:sigma:lock:{user_id}"   # short TTL lock to prevent double submits
K_MAINMSG_LAST_REFRESH = "slots:mainmsg:last_refresh"
K_MAINMSG_REFRESH_LOCK = "slots:mainmsg:refresh_lock"
K_MEGA_LOSS_STREAK = "slots:mega:loss_streak"  # hash user_id -> consecutive net-loss count
K_MEGA_LOSS_STREAK_BEST    = "slots:mega:loss_streak:best"     # hash user_id -> best-ever consecutive net-loss count
K_MEGA_LOSS_STREAK_BEST_TS = "slots:mega:loss_streak:best_ts"  # hash user_id -> epoch seconds when best was last achieved

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

def next_midnight_et_epoch() -> int:
    now = datetime.now(NY_TZ)
    next_day = (now + timedelta(days=1)).date()
    next_midnight = datetime.combine(next_day, dtime(0, 0, 0), tzinfo=NY_TZ)
    return int(next_midnight.timestamp())

def fmt_spin_value(spin_value: int, force: bool = False):
    return f"{spin_value:.3e}" if (spin_value > 1_000_000_000_000 or force) else f"{spin_value:,}"

def self_destruct_text(timeout: int) -> str:
    now_utc = datetime.now(timezone.utc)
    return f"*This message should self-destruct <t:{now_utc.timestamp() + timeout}:R>*"

def ordinal(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return str(n)
    if 10 <= (n % 100) <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"

# Test version
# def fmt_spin_value(spin_value: int, orig=False):
#     prefix = ""
#     if orig:
#         prefix = f"{spin_value:,}"

#     return prefix + (f"{spin_value:.3e}" if (spin_value > 1_000_000_000_000 or orig) else ("" if prefix else f"{spin_value:,}"))

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
class SigmaOutcome:
    id: str
    label: str
    weight: float
    params: Dict[str, Any]

@dataclass
class SigmaConfig:
    enabled: bool
    cost_fraction: float
    min_points: int
    cooldown_seconds: int
    tokens_cap: int
    wheel: List[SigmaOutcome]

@dataclass
class SlotsConfig:
    title: str
    instructions: str
    items: List[Item]
    big_win_threshold: int
    sigma: Optional[SigmaConfig] = None

class SlotsSpinView(discord.ui.View):
    def __init__(self, *, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)

    @discord.ui.button(label="🎰 Spin", style=discord.ButtonStyle.primary, custom_id="slots:spin:normal")
    async def spin_normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: "SlotsCog" = interaction.client.get_cog("SlotsCog")  # type: ignore
        if not cog:
            return await interaction.response.send_message("Slots are temporarily unavailable.", ephemeral=True)
        await cog.handle_spin(interaction, mega=False)

    @discord.ui.button(label="🤖 MEGA Spin", style=discord.ButtonStyle.success, custom_id="slots:spin:mega")
    async def spin_mega(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: "SlotsCog" = interaction.client.get_cog("SlotsCog")  # type: ignore
        if not cog:
            return await interaction.response.send_message("Slots are temporarily unavailable.", ephemeral=True)
        await cog.handle_spin(interaction, mega=True)

    @discord.ui.button(label="Σ Sigma", style=discord.ButtonStyle.secondary, custom_id="slots:sigma:open")
    async def sigma_open(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: "SlotsCog" = interaction.client.get_cog("SlotsCog")  # type: ignore
        if not cog:
            return await interaction.response.send_message("Slots are temporarily unavailable.", ephemeral=True)
        await cog.sigma_open_confirm(interaction)

    @discord.ui.button(label="🗡️ 1v1", style=discord.ButtonStyle.secondary, custom_id="slots:duel:new")
    async def duel_new(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: "SlotsCog" = interaction.client.get_cog("SlotsCog")  # type: ignore
        if not cog:
            return await interaction.response.send_message("Slots are temporarily unavailable.", ephemeral=True)
        await cog.start_duel(interaction)


class SigmaConfirmView(discord.ui.View):
    def __init__(self, cog: "SlotsCog", user_id: int, est_cost: int, expires_at: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.user_id = user_id
        self.est_cost = est_cost
        self.expires_at = expires_at

    async def on_timeout(self):
        # silently disable buttons when the ephemeral confirm expires
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="Spin Sigma", style=discord.ButtonStyle.primary, custom_id="slots:sigma:confirm")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_sigma_spin(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="slots:sigma:cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        try:
            await interaction.response.edit_message(content=f"Σ Sigma cancelled.\n{self_destruct_text(5)}", view=self, delete_after=5)
        except Exception:
            try:
                await interaction.response.send_message(f"Σ Sigma cancelled.\n{self_destruct_text(5)}", ephemeral=True, delete_after=5)
            except Exception:
                pass


class DuelAcceptView(discord.ui.View):
    def __init__(self, cog: "SlotsCog", *, message_id: int, channel_id: int, duel_key: str, initiator_id: int, initiator_fee: int, expires_at: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.message_id = message_id
        self.channel_id = channel_id
        self.duel_key = duel_key
        self.initiator_id = initiator_id
        self.initiator_fee = initiator_fee
        self.expires_at = expires_at

    async def on_timeout(self):
        # If still open, refund the initiator and mark expired
        try:
            data = await self.cog.r.get(self.duel_key)
            if not data:
                return
            obj = json.loads(data)
            if obj.get("state") != "open":
                return
            # mark expired
            obj["state"] = "expired"
            await self.cog.r.set(self.duel_key, json.dumps(obj), ex=60)

            # refund initiator fee
            uid = str(self.initiator_id)
            fee = int(self.initiator_fee)
            if fee > 0:
                pipe = self.cog.r.pipeline()
                pipe.hincrbyfloat(K_STATS_WINNINGS, uid, fee)
                pipe.zincrby(K_LEADERBOARD, fee, uid)
                pipe.hdel(K_DUEL_ACTIVE_BY_USER, uid)
                await pipe.execute()

            # disable button on message
            ch = self.cog.bot.get_channel(self.channel_id) or await self.cog.bot.fetch_channel(self.channel_id)
            if isinstance(ch, (discord.TextChannel, discord.Thread)):
                try:
                    msg = await ch.fetch_message(self.message_id)
                    for item in self.children:
                        item.disabled = True
                    await msg.edit(view=self, content="⏲️ 1v1 challenge expired.")
                except Exception:
                    pass
        except Exception:
            pass

    @discord.ui.button(label="Accept 1v1", style=discord.ButtonStyle.success, custom_id="slots:duel:accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.accept_duel(interaction, self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, custom_id="slots:duel:cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.cancel_duel(interaction, self)

class ResultShareView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        thread_id: int,
        author_id: int,
        share_title: str,
        share_description: str,
        summary: str,
        color: discord.Color,
        spin_time: datetime,
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.thread_id = thread_id
        self.author_id = author_id
        self.share_title = share_title
        self.share_description = share_description
        self.summary = summary
        self.color = color
        self.spin_time = spin_time

    @discord.ui.button(label="🎰 Spin", style=discord.ButtonStyle.primary, custom_id="slots:result:spin_again")
    async def spin_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Only the original spinner can use these buttons.", ephemeral=True)
        cog: "SlotsCog" = interaction.client.get_cog("SlotsCog")  # type: ignore
        if not cog:
            return await interaction.response.send_message("Slots are temporarily unavailable.", ephemeral=True)
        await cog.handle_spin(interaction, mega=False, edit_in_place=True)

    @discord.ui.button(label="🤖 MEGA Spin", style=discord.ButtonStyle.success, custom_id="slots:result:mega_again")
    async def mega_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Only the original spinner can use these buttons.", ephemeral=True)
        cog: "SlotsCog" = interaction.client.get_cog("SlotsCog")  # type: ignore
        if not cog:
            return await interaction.response.send_message("Slots are temporarily unavailable.", ephemeral=True)
        await cog.handle_spin(interaction, mega=True, edit_in_place=True)

    @discord.ui.button(label="📣 Share to thread", style=discord.ButtonStyle.secondary, custom_id="slots:share_result")
    async def share(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            logger.warning(f"!!! Share user mismatch !!! interaction.user.id: {interaction.user.id}, self.author_id: {self.author_id}")
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
        if self.summary:
            embed.add_field(name="Summary", value=self.summary, inline=False)
        embed.timestamp = self.spin_time

        try:
            await channel.send(content=f"Spin by <@{self.author_id}>", embed=embed)
            await interaction.response.send_message(f"Shared to the thread. 📣\n{self_destruct_text(5)}", ephemeral=True, delete_after=5)
        except Exception as error:
            logger.error(f"Error sharing: %s", error, exc_info=True)
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
        raw_sigma = raw.get("sigma") or {}
        wheel = []
        for w in raw_sigma.get("wheel", []):
            wheel.append(SigmaOutcome(
                id=w["id"],
                label=w.get("label", w["id"]),
                weight=float(w.get("weight", 1)),
                params={k:v for k,v in w.items() if k not in ("id","label","weight")}
            ))
        sigma_cfg = SigmaConfig(
            enabled=bool(raw_sigma.get("enabled", True)),
            cost_fraction=float(raw_sigma.get("cost_fraction", 0.25)),
            min_points=int(raw_sigma.get("min_points", 1000)),
            cooldown_seconds=int(raw_sigma.get("cooldown_seconds", 300)),
            tokens_cap=int(raw_sigma.get("tokens_cap", 1)),
            wheel=wheel or [
                SigmaOutcome("refund_refill_mega","Refund cost + refill MEGA",16,{}),
                SigmaOutcome("refund_plus_half","Refund cost + 50%",16,{"bonus_fraction":0.5}),
                SigmaOutcome("refund_double","Refund cost ×2",8,{}),
                SigmaOutcome("spread_cost_others","Spread the cost among all other players",6,{}),
                SigmaOutcome("share_entire_bal","Share entire balance (cost refunded)",2,{})
            ]
        )
        return SlotsConfig(
            title=raw.get("title", "Slots"),
            instructions=raw.get("instructions", "Press **Spin** to play!"),
            items=items,
            big_win_threshold=int(raw.get("big_win_threshold", 1_000)),
            sigma=sigma_cfg
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

    @commands.command(name="refill_spins", help="Refill NORMAL spins to max for all tracked users and reset today's MEGA spin usage. (manage_guild)")
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
            K_JACKPOT_POOL,
            K_DUEL_WINS, 
            K_DUEL_LOSSES,
            K_BIGGEST_SPINS,          # legacy
            K_BIGGEST_SPINS_MEGA,     # new
            K_BIGGEST_SPINS_NORMAL,
            K_MEGA_LOSS_STREAK_BEST,
            K_MEGA_LOSS_STREAK_BEST_TS
        )

        try:
            await self._refresh_channel_message()
        except Exception:
            pass

        await ctx.reply(
            f"**Hard reset complete.** Cleared `{deleted_plays}` per-day keys and `{del_other}` global keys (incl. jackpot).",
            mention_author=False
        )

    @commands.command(name="duels_refund_all",
    help="Admin: clear ALL pending 1v1 duels (open/accepted) and refund any deducted fees. Also deletes challenge messages. (manage_guild)")
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def duels_refund_all(self, ctx: commands.Context):
        """
        Scans all duel requests:
        - If state == 'open': refund initiator's fee (only if still mapped as active), close & delete.
        - If state == 'accepted': refund initiator & opponent fees (only if still mapped as active), close & delete.
        Also removes accept locks and tries to delete the challenge message if it still exists.
        """
        pattern = "slots:duel:req:*"
        refunded_initiators = 0
        refunded_opponents = 0
        closed = 0
        skipped = 0

        # gather keys first (avoid modifying while scanning)
        duel_keys = []
        async for k in self.r.scan_iter(match=pattern):
            duel_keys.append(k)

        for dkey in duel_keys:
            data = await self.r.get(dkey)
            if not data:
                continue

            try:
                obj = json.loads(data)
            except Exception:
                # can't parse; delete broken key
                await self.r.delete(dkey)
                closed += 1
                continue

            state = obj.get("state", "open")
            initiator_id = int(obj.get("initiator_id", 0) or 0)
            initiator_fee = int(obj.get("initiator_fee", 0) or 0)
            opponent_id = int(obj.get("opponent_id", 0) or 0)
            channel_id = int(obj.get("channel_id", 0) or 0)
            message_id = int(obj.get("message_id", 0) or 0)

            # Only refund if this duel still shows as active for the initiator (prevents double refunds)
            active_mid = await self.r.hget(K_DUEL_ACTIVE_BY_USER, str(initiator_id))
            is_active = (active_mid is not None) and (message_id and str(message_id) == str(active_mid))

            if state not in ("open", "accepted") or not is_active:
                # Not a pending duel (or mapping is gone) — skip to avoid double refunds
                skipped += 1
                # but still clean up stale lock and possibly delete key if it lingers in weird state
                try:
                    if message_id:
                        await self.r.delete(K_DUEL_LOCK.format(message_id=message_id))
                except Exception:
                    pass
                continue

            pipe = self.r.pipeline()

            # Refund initiator fee
            if initiator_id and initiator_fee > 0:
                pipe.hincrbyfloat(K_STATS_WINNINGS, str(initiator_id), initiator_fee)
                pipe.zincrby(K_LEADERBOARD, initiator_fee, str(initiator_id))
                refunded_initiators += 1

            # If accepted, also refund opponent (same fee as initiator)
            if state == "accepted" and opponent_id and initiator_fee > 0:
                pipe.hincrbyfloat(K_STATS_WINNINGS, str(opponent_id), initiator_fee)
                pipe.zincrby(K_LEADERBOARD, initiator_fee, str(opponent_id))
                refunded_opponents += 1

            # Clear mappings/locks and delete duel key
            pipe.hdel(K_DUEL_ACTIVE_BY_USER, str(initiator_id))
            if message_id:
                pipe.delete(K_DUEL_LOCK.format(message_id=message_id))
            pipe.delete(dkey)

            await pipe.execute()
            closed += 1

            # Try to delete the original challenge message (if it still exists)
            if channel_id and message_id:
                try:
                    ch = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                    if isinstance(ch, (discord.TextChannel, discord.Thread)):
                        msg = await ch.fetch_message(message_id)
                        await msg.delete()
                except Exception:
                    pass  # it's fine if it's already gone

        await ctx.reply(
            f"✅ Cleared stuck duels.\n"
            f"- Closed: **{closed}**\n"
            f"- Refunded initiators: **{refunded_initiators}**\n"
            f"- Refunded opponents: **{refunded_opponents}**\n"
            f"- Skipped (already resolved/not active): **{skipped}**",
            mention_author=False
        )

    async def sigma_open_confirm(self, interaction: discord.Interaction):
        """Show an ephemeral confirmation with the outcomes & a Spin button."""
        await self._ensure_config_for_today()
        user = interaction.user
        user_name = getattr(interaction.user, "global_name", None) or interaction.user.name
        uid = str(user.id)
        cfg = self._config

        if not cfg.sigma or not cfg.sigma.enabled or not cfg.sigma.wheel:
            return await interaction.response.send_message("Sigma is currently disabled.", ephemeral=True)

        # Refill/check Sigma token
        tokens, next_in = await self._refill_sigma_tokens(user.id)
        if tokens <= 0:
            now = int(datetime.now(tz=NY_TZ).timestamp())
            logger.info(f"[{user_name}] No Σ Sigma spins available.")
            return await interaction.response.send_message(
                f"No Σ Sigma available. Next charge **<t:{now + next_in}:R>**.\n{self_destruct_text(60)}",
                ephemeral=True, delete_after=60
            )

        # Compute *estimated* cost (we will recompute on confirm)
        points = int(await self.r.hget(K_STATS_WINNINGS, uid) or 0)
        est_cost = max(cfg.sigma.min_points, int(points * cfg.sigma.cost_fraction))
        if points < est_cost or est_cost <= 0:
            logger.info(f"[{user_name}] No Σ Sigma spins available, not enough points.")
            return await interaction.response.send_message(
                f"You need **≥ {cfg.sigma.min_points:,}** points and will be charged **25%** of your balance to spin.\n{self_destruct_text(30)}",
                ephemeral=True, delete_after=30
            )

        # Outcomes (weights: medium/lowish/low/very low → 16/8/6/2 mapping)
        outcomes_hints = [x.label for x in cfg.sigma.wheel]

        desc = (
            f"Sigma Fee: **{int(cfg.sigma.cost_fraction * 100)}%**\n"
            f"Total Cost: **{est_cost:g}**\n"
            f"Cooldown: 5 minutes\n\n"
            "**Possible outcomes:**\n" + "\n".join(outcomes_hints) + "\n\n"
            f"{self_destruct_text(30)}\n"
        )

        embed = discord.Embed(title="Σ Sigma Spin — Confirm", description=desc, color=discord.Color.dark_gold())
        expires_at = int(datetime.now(tz=NY_TZ).timestamp()) + 60
        view = SigmaConfirmView(self, user.id, est_cost, expires_at)
        await interaction.response.send_message(embed=embed, ephemeral=True, view=view, delete_after=30)

    async def handle_sigma_spin(self, interaction: discord.Interaction):
        """Resolve Sigma spin after user confirms."""
        await self._ensure_config_for_today()
        user = interaction.user
        user_name = getattr(interaction.user, "global_name", None) or interaction.user.name
        uid = str(user.id)
        now = int(datetime.now(tz=NY_TZ).timestamp())
        cfg = self._config
        if not cfg.sigma or not cfg.sigma.enabled or not cfg.sigma.wheel:
            return await interaction.response.send_message("Sigma is currently disabled.", ephemeral=True)

        # Lock to prevent double submits
        lock_key = K_SIGMA_LOCK.format(user_id=user.id)
        if not await self.r.set(lock_key, "1", ex=10, nx=True):
            logger.info(f"[{user_name}] Another Sigma is already processing.")
            return await interaction.response.send_message("Another Sigma is already processing.", ephemeral=True)

        try:
            # Token check/consume
            tokens, _ = await self._refill_sigma_tokens(user.id)
            if tokens <= 0:
                logger.info(f"[{user_name}] No Σ Sigma spins available.")
                return await interaction.response.send_message(f"No Σ Sigma available right now.\n{self_destruct_text(10)}", ephemeral=True, delete_after=10)
            await self.r.decr(K_SIGMA_TOKENS.format(user_id=user.id))

            # Recompute cost and verify eligibility
            points = int(await self.r.hget(K_STATS_WINNINGS, uid) or 0)
            cost = max(cfg.sigma.min_points, int(points * cfg.sigma.cost_fraction))
            if points < cost or cost <= 0:
                # give token back (gracefully) if they lost points meanwhile
                logger.info(f"[{user_name}] No Σ Sigma spins available, not enough points.")
                await self.r.incr(K_SIGMA_TOKENS.format(user_id=user.id))
                return await interaction.response.send_message(
                    f"Balance changed — you need **≥ {cfg.sigma.min_points:,}** and 25% cost available.\n{self_destruct_text(30)}",
                    ephemeral=True, delete_after=30
                )

            # Deduct escrow
            pipe = self.r.pipeline()
            pipe.hincrbyfloat(K_STATS_WINNINGS, uid, -cost)
            pipe.zincrby(K_LEADERBOARD, -cost, uid)
            await pipe.execute()
            escrow = cost

            # Choose outcome (weights: 16,16,8,6,2)
            wheel_ids = [o.id for o in cfg.sigma.wheel]
            wheel_wts = [o.weight for o in cfg.sigma.wheel]
            choice_id = random.choices(wheel_ids, weights=wheel_wts, k=1)[0]
            chosen = next(o for o in cfg.sigma.wheel if o.id == choice_id)
            
            # Apply outcome
            summary_lines: List[str] = []
            share_thread_note: Optional[str] = None

            if choice_id == "refund_refill_mega":
                mega_refund = chosen.params.get("bonus_fraction", 0.5)
                # refund escrow
                pipe = self.r.pipeline()
                pipe.hincrbyfloat(K_STATS_WINNINGS, uid, escrow)
                pipe.zincrby(K_LEADERBOARD, escrow, uid)
                await pipe.execute()
                escrow = 0

                mega_refund = int(chosen.params.get("mega_refund", 1))
                actually_refunded = await self._refund_mega_usage(int(uid), mega_refund)

                if actually_refunded > 0:
                    summary_lines.append(
                        f"Outcome: **Refund cost + refund {actually_refunded} MEGA use(s)** (+{cost:g} returned)."
                    )
                else:
                    summary_lines.append(
                        f"Outcome: **Refund** {cost:g}; you hadn't used any MEGA spins to refund."
                    )                
            elif choice_id == "nothing":
                pass
            elif choice_id in ("refund_plus_half", "refund_double", "refund_triple", "refund_quad", "refund_quin"):
                bonus_fraction = chosen.params.get("bonus_fraction", 0.5)
                bonus = int(escrow * bonus_fraction)
                pipe = self.r.pipeline()
                pipe.hincrbyfloat(K_STATS_WINNINGS, uid, escrow + bonus)
                pipe.zincrby(K_LEADERBOARD, escrow + bonus, uid)
                await pipe.execute()
                summary_lines.append(f"Outcome: Win **{(1 + bonus_fraction):.1f}x** = {escrow + bonus:g}!")
                escrow = 0  # fully returned to user (and more)

            elif choice_id == "spread_cost_others":
                distributed, recipients = await self._sigma_spread_to_all_others(escrow, initiator_id=int(uid))
                escrow = 0  # fully used for spread (remainder handled inside helper)
                if recipients:
                    per = distributed // len(recipients)
                    summary_lines.append(f"Outcome: **Spread cost** — {distributed:g} points shared to **{len(recipients)}** others.")
                    share_thread_note = f"Σ Sigma: <@{uid}> spread **{int(cfg.sigma.cost_fraction * 100)}%** of their balance: **{distributed:g}** to **{len(recipients)}** everyone. Each player receives **{per:g}**."
                else:
                    # no one else to share with → refund
                    pipe = self.r.pipeline()
                    pipe.hincrbyfloat(K_STATS_WINNINGS, uid, cost)
                    pipe.zincrby(K_LEADERBOARD, cost, uid)
                    await pipe.execute()
                    summary_lines.append("Outcome: **No recipients** — cost refunded.")

            elif choice_id == "share_entire_bal":
                # Refund escrow to initiator, then distribute their entire remaining balance to others.
                # Get current balance (post-escrow)
                bal_after = int(await self.r.hget(K_STATS_WINNINGS, uid) or 0)
                # Refund escrow
                pipe = self.r.pipeline()
                pipe.hincrbyfloat(K_STATS_WINNINGS, uid, escrow)
                pipe.zincrby(K_LEADERBOARD, escrow, uid)
                await pipe.execute()
                escrow = 0

                # Re-read (refund just applied)
                bal_total = int(await self.r.hget(K_STATS_WINNINGS, uid) or 0)
                if bal_total > 0:
                    # Set to zero, and distribute bal_total to others
                    pipe = self.r.pipeline()
                    pipe.hincrbyfloat(K_STATS_WINNINGS, uid, -bal_total)
                    pipe.zincrby(K_LEADERBOARD, -bal_total, uid)
                    await pipe.execute()

                    distributed, recipients = await self._sigma_spread_to_all_others(bal_total, initiator_id=int(uid))
                    summary_lines.append(
                        f"Outcome: **Share entire balance** — distributed {distributed:g} to {len(recipients)} others. "
                        f"(Your cost was refunded.)"
                    )
                    share_thread_note = f"Σ Sigma: <@{uid}> shared their entire balance of **{distributed:g}** to others."
                else:
                    summary_lines.append("Outcome: **Share entire balance** — nothing to share (balance was 0). Cost was refunded.")

            # Any remaining escrow not refunded or shared → jackpot
            if escrow > 0:
                await self.r.incrbyfloat(K_JACKPOT_POOL, escrow)
                summary_lines.append(f"***{escrow:g}** added to jackpot.*")

            # Compose ephemeral result
            tokens_after, next_in = await self._refill_sigma_tokens(user.id)
            next_line = ("Ready now" if tokens_after > 0 else f"Next Sigma **<t:{now + next_in}:R>**")

            embed = discord.Embed(
                title="Σ Sigma Result",
                description="\n".join(summary_lines + [f"\n**Cooldown:** {next_line}\n{self_destruct_text(5)}"]),
                color=discord.Color.dark_gold(),
                timestamp=datetime.now(tz=NY_TZ)
            )
            logger.info("\n\t".join([f"{user_name} Sigma"] + summary_lines))

            # Announce to thread for global effects
            if share_thread_note:
                target = self.bot.get_channel(SHARE_THREAD_ID) or await self.bot.fetch_channel(SHARE_THREAD_ID)
                if isinstance(target, (discord.Thread, discord.TextChannel)):
                    try:
                        await target.send(content=share_thread_note, silent=True)
                    except Exception:
                        pass

            # Refresh persistent message (best-effort)
            try:
                await self._maybe_refresh_channel_message()
            except Exception:
                pass

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True, delete_after=60 * 5)

        finally:
            try:
                await self.r.delete(lock_key)
            except Exception:
                pass

    async def _refill_sigma_tokens(self, user_id: int) -> Tuple[int, int]:
        """Single-charge token bucket for Sigma (cap=1, +1 every 300s)."""
        cfg = self._config
        now = int(time.time())
        tkey = K_SIGMA_TOKENS.format(user_id=user_id)
        lkey = K_SIGMA_LAST.format(user_id=user_id)

        pipe = self.r.pipeline()
        pipe.get(tkey)
        pipe.get(lkey)
        cur_tokens_s, last_ts_s = await pipe.execute()

        if cur_tokens_s is None or last_ts_s is None:
            await self.r.set(tkey, cfg.sigma.tokens_cap)
            await self.r.set(lkey, now)
            return cfg.sigma.tokens_cap, 0

        tokens = int(cur_tokens_s or 0)
        last_ts = int(last_ts_s or now)

        if tokens < cfg.sigma.tokens_cap:
            elapsed = max(0, now - last_ts)
            gained = elapsed // cfg.sigma.cooldown_seconds
            if gained > 0:
                tokens = min(cfg.sigma.tokens_cap, tokens + gained)
                last_ts = last_ts + gained * cfg.sigma.cooldown_seconds
                pipe = self.r.pipeline()
                pipe.set(tkey, tokens)
                pipe.set(lkey, last_ts)
                await pipe.execute()
        else:
            # at cap, move anchor forward to avoid big deltas
            await self.r.set(lkey, now)

        if tokens >= cfg.sigma.tokens_cap:
            next_in = 0
        else:
            elapsed = max(0, now - last_ts)
            next_in = cfg.sigma.cooldown_seconds - (elapsed % cfg.sigma.cooldown_seconds)
        return tokens, next_in

    async def _sigma_spread_to_all_others(self, amount: int, *, initiator_id: int) -> Tuple[int, List[int]]:
        """Evenly distribute 'amount' to all known users except initiator. Remainder → jackpot."""
        if amount <= 0:
            return 0, []

        all_map = await self.r.hgetall(K_STATS_WINNINGS)
        if not all_map:
            return 0, []

        recipients = [int(u) for u in all_map.keys() if int(u) != initiator_id]
        if not recipients:
            return 0, []

        per = amount // len(recipients)
        remainder = amount - per * len(recipients)
        if per <= 0:
            # Not enough to split meaningfully → remainder to jackpot
            await self.r.incrbyfloat(K_JACKPOT_POOL, amount)
            return 0, recipients

        # Batch credit recipients
        pipe = self.r.pipeline()
        for rid in recipients:
            s = str(rid)
            pipe.hincrbyfloat(K_STATS_WINNINGS, s, per)
            pipe.zincrby(K_LEADERBOARD, per, s)
        await pipe.execute()

        if remainder > 0:
            await self.r.incrbyfloat(K_JACKPOT_POOL, remainder)

        return per * len(recipients), recipients
    
    def _make_result_view(self, interaction: discord.Interaction, embed: discord.Embed, summary: str = "") -> discord.ui.View:
        return ResultShareView(
            bot=self.bot,
            thread_id=SHARE_THREAD_ID,
            author_id=interaction.user.id,
            share_title=embed.title or "Spin Result",
            share_description=embed.description or "",
            summary=summary,
            color=embed.color or discord.Color.green(),
            spin_time=datetime.now(tz=NY_TZ),
        )

    # ---------------- Spin handling (button interaction) ----------------

    async def handle_spin(self, interaction: discord.Interaction, *, mega: bool, edit_in_place: bool = False):
        await self._ensure_config_for_today()
        assert self._config is not None
        cfg = self._config

        user = interaction.user
        user_name = getattr(interaction.user, "global_name", None) or interaction.user.name
        user_id = str(user.id)
        spin_time = datetime.now(tz=NY_TZ)
        spin_time_utc_sec = int(spin_time.timestamp())
        date_str = ny_date_str()
        jackpot_contribution = 0
        cost = 0

        # NORMAL spin: enforce cooldown
        if not mega:
            # token-bucket check
            tokens, next_in = await self._refill_normal_tokens(user.id)
            if tokens <= 0:
                # Build a lightweight status embed and EDIT the original message if requested
                status = discord.Embed(
                    title="🎰 No normal spins available",
                    description=f"Next spin **<t:{spin_time_utc_sec + next_in}:R>**\n"
                                f"(you can store up to **{NORMAL_TOKENS_CAP}**).\n{self_destruct_text(60*10)}",
                    color=discord.Color.dark_gray()
                )
                status.timestamp = spin_time
                logger.info(f"[{user_name}] 🎰 No normal spins available.")
                if edit_in_place:
                    return await interaction.response.edit_message(embed=status, view=self._make_result_view(interaction, status), delete_after=60 * 10)
                else:
                    return await interaction.response.send_message(embed=status, ephemeral=True, delete_after=60 * 10)
            # consume one token
            await self.r.decr(K_NORMAL_TOKENS.format(user_id=user.id))

            # Increase jackpot by .05%
            try:
                jackpot_award = int(await self.r.get(K_JACKPOT_POOL))
            except Exception:
                jackpot_award = 0

            if jackpot_award > 0:
                jackpot_contribution = int(jackpot_award * JACKPOT_NORMAL_INC_FRACTION)
                await self.r.set(K_JACKPOT_POOL, int(jackpot_award + jackpot_contribution))
        else:
            # MEGA spin: enforce per-day count and cost
            mkey = mega_plays_key(user.id, date_str)
            used = int(await self.r.get(mkey) or 0)
            if used >= MEGA_SPINS_PER_DAY:
                msg = discord.Embed(
                    title="🤖 No MEGA spins available",
                    description=f"You've used your **{MEGA_SPINS_PER_DAY}** MEGA spins for today. "
                                f"Come back after midnight ET or try a **Sigma** spin to refill some MEGA spins!\n{self_destruct_text(60*10)}",
                    color=discord.Color.dark_gray()
                )
                msg.timestamp = spin_time
                logger.info(f"[{user_name}] 🤖 No MEGA spins available.")
                if edit_in_place:
                    return await interaction.response.edit_message(embed=msg, view=self._make_result_view(interaction, msg), delete_after=60 * 10)
                else:
                    return await interaction.response.send_message(embed=msg, ephemeral=True, delete_after=60 * 10)

            total_points = int(await self.r.hget(K_STATS_WINNINGS, user_id) or 0)
            if total_points <= MEGA_MIN_POINTS:
                msg = discord.Embed(
                    title="🤖 No MEGA spins available",
                    description=f"MEGA spins require **> {MEGA_MIN_POINTS:,}** points. You currently have **{total_points:,}**.\n{self_destruct_text(60*10)}",
                    color=discord.Color.dark_gray()
                )
                msg.timestamp = spin_time
                logger.info(f"[{user_name}] 🤖 No MEGA spins available, not enough points.")
                if edit_in_place:
                    return await interaction.response.edit_message(embed=msg, view=self._make_result_view(interaction, msg), delete_after=60 * 10)
                else:
                    return await interaction.response.send_message(embed=msg, ephemeral=True, delete_after=60 * 10)
            # Defer the response for mega spins.
            await interaction.response.defer(ephemeral=not edit_in_place, thinking=not edit_in_place)
            cost = max(1, int(total_points * MEGA_COST_FRACTION))
            jackpot_contribution = cost
            # Deduct cost up-front and add to the progressive jackpot
            pipe = self.r.pipeline()
            pipe.hincrbyfloat(K_STATS_WINNINGS, user_id, -cost)
            pipe.zincrby(K_LEADERBOARD, -cost, user_id)
            pipe.incrbyfloat(K_JACKPOT_POOL, cost)
            await pipe.execute()

            # Record today's MEGA usage
            mkey = mega_plays_key(int(user_id), date_str)
            await self.r.incr(mkey)
            await self.r.expire(mkey, 60 * 60 * 48)

            streak = int(await self.r.hget(K_MEGA_LOSS_STREAK, user_id) or 0)
            if streak >= 1:
                loss_bonus_mult = MEGA_LOSS_BONUS_INITIAL * (MEGA_LOSS_BONUS_SCALE ** (streak - 1))
            else:
                loss_bonus_mult = 1.0


        # Perform spin
        bonus_mult = MEGA_PAYOUT_MULT * loss_bonus_mult if mega else 1.0
        board_size = 7 if mega else 5
        grid, spin_total, breakdown, mult_used, grid_mult, total_mult = self._spin_and_score(
            cfg, bonus_multiplier=bonus_mult, size=board_size
        )
        # %-I to remove the leading zero is unix specific, %#I works on windows.

        match_count = len(breakdown)
        breakdown = [f"{match_count} matches"]
        
        # spin_time_str = spin_time.strftime("%B %d, %Y at %-I:%M %p %Z")

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
        else:
            breakdown.append(f"*{jackpot_contribution:g} added to jackpot*")

        gross_total = spin_total + jackpot_award

        net_delta = gross_total - (cost if mega else 0)

        await self.r.hincrby(K_STATS_SPINS, user_id, 1)
        if mega:
            await self.r.hincrby(K_STATS_SPINS_MEGA, user_id, 1)
            if net_delta <= 0:
                new_streak = (streak + 1)
                await self.r.hincrby(K_MEGA_LOSS_STREAK, user_id, 1)
                best_so_far = int(await self.r.hget(K_MEGA_LOSS_STREAK_BEST, user_id) or 0)
                if new_streak > best_so_far:
                    now_ts = int(datetime.now(tz=NY_TZ).timestamp())
                    pipe = self.r.pipeline()
                    pipe.hset(K_MEGA_LOSS_STREAK_BEST, user_id, new_streak)
                    pipe.hset(K_MEGA_LOSS_STREAK_BEST_TS, user_id, now_ts)
                    await pipe.execute()
            else:
                # reset by deleting the field (saves storage vs writing zero)
                await self.r.hdel(K_MEGA_LOSS_STREAK, user_id)
        
        if gross_total:
            await self.r.hincrbyfloat(K_STATS_WINNINGS, user_id, gross_total)
            await self.r.zincrby(K_LEADERBOARD, gross_total, user_id)

        if net_delta > 0:
            biggest_entry = {
                "user_id": int(user_id),
                "username": user_name,
                "amount": net_delta,
                "utc_sec": spin_time_utc_sec,
                "mega": bool(mega)
            }
            member = json.dumps(biggest_entry, separators=(",", ":"))
            await self.r.zadd(K_BIGGEST_SPINS, {member: net_delta})

            if mega:
                await self.r.zadd(K_BIGGEST_SPINS_MEGA, {member: net_delta})
            else:
                await self.r.zadd(K_BIGGEST_SPINS_NORMAL, {member: net_delta})

            # trim to top ~200 for each set
            async def _trim_top200(key: str):
                total = await self.r.zcard(key)
                remove_n = total - 200
                if remove_n > 0:
                    await self.r.zremrangebyrank(key, 0, remove_n - 1)

            await _trim_top200(K_BIGGEST_SPINS)
            await _trim_top200(K_BIGGEST_SPINS_MEGA if mega else K_BIGGEST_SPINS_NORMAL)

        # Big-wins feed uses net
        if net_delta >= cfg.big_win_threshold or jackpot_award > 0:
            entry = {
                "user_id": int(user_id),
                "username": user_name,
                "amount": net_delta,
                "date": date_str,
                "utc_sec": spin_time_utc_sec,
                "mega": mega,
                "jackpot": jackpot_award
            }
            await self.r.lpush(K_BIGWINS, json.dumps(entry))
            await self.r.ltrim(K_BIGWINS, 0, BIGWINS_FEED_LEN - 1)

        # Refresh persistent message (best-effort)
        try:
            await self._maybe_refresh_channel_message()
        except Exception:
            pass

        # Build ephemeral result
        grid_str = self._render_grid(grid)

        total_spins = int(await self.r.hget(K_STATS_SPINS, user_id) or 0)
        total_wins_accum = int(await self.r.hget(K_STATS_WINNINGS, user_id) or 0)
        # avg = (total_wins_accum / total_spins) if total_spins > 0 else 0.0

        desc_lines = []
        title = "🎰 Your Spin Result" if not mega else "🤖 MEGA Spin Result"
        loss_streak_text = ""

        if not mega:
            # Decide outcome text
            if net_delta > 0:
                desc_lines.append(f"**You won:** {net_delta:g}")
            else:
                desc_lines.append("No win this time!")
        else:
            # MEGA info block
            # Present gross, cost, net
            if loss_bonus_mult > 1:
                loss_streak_text = f"MEGA loss streak of {streak} = ×{loss_bonus_mult:g}"
            gross_line = f"Gross win: **{gross_total:g}**"
            #cost_line = f"MEGA cost: **-{cost:g}**"
            net_line = f"**Net change:** **{net_delta:g}**"
            desc_lines.extend([gross_line, net_line])

        if breakdown:
            breakdown_max = 5
            desc_lines += [f"- {line}" for line in breakdown[0:breakdown_max]]
            excluded = max(0, len(breakdown) - breakdown_max)
            if excluded:
                desc_lines.append(f"...and {excluded} more!")

        desc_lines.append(f"**Total multiplier:** {total_mult:g}×")

        # show remaining tokens and next refill
        tok_left, next_in = await self._refill_normal_tokens(user.id)

        used_after = int(await self.r.get(mega_plays_key(user.id, date_str)) or 0)
        remaining = max(0, MEGA_SPINS_PER_DAY - used_after)

        if mega:
            embed_color = discord.Color.orange() if net_delta > 0 else discord.Color.red()
        else:
            embed_color = discord.Color.green() if net_delta > 0 else discord.Color.dark_gray()

        embed = discord.Embed(
            title=title,
            description=grid_str,
            color=embed_color
        )
        if jackpot_award > 0:
            desc_lines.append(f"💰 **Jackpot paid:** +{jackpot_award:g}")
        if loss_streak_text:
            embed.add_field(name="Loss Bonus Active", value=loss_streak_text, inline=False)

        normal_tok_text = f"{tok_left}/{NORMAL_TOKENS_CAP}"
        mega_tok_text = f"{remaining}/{MEGA_SPINS_PER_DAY}"

        if tok_left < NORMAL_TOKENS_CAP and next_in > 0:
            normal_tok_text += f"\n*+1 <t:{spin_time_utc_sec + next_in}:R>*"
        if remaining < MEGA_SPINS_PER_DAY:
            mega_tok_text += f"\n*+{MEGA_SPINS_PER_DAY} <t:{next_midnight_et_epoch()}:R>*"

        current_loss_streak = int(await self.r.hget(K_MEGA_LOSS_STREAK, user_id) or 0)

        embed.add_field(name="Summary", value="\n".join(desc_lines + [self_destruct_text(60*10)]), inline=False)
        embed.add_field(name="Normal Spins", value=normal_tok_text, inline=True)
        embed.add_field(name="MEGA Spins", value=mega_tok_text, inline=True)
        embed.add_field(name="Total Spins", value=f"{total_spins}", inline=True)
        embed.add_field(name="MEGA Loss Streak", value=f"{current_loss_streak}", inline=True)
        embed.add_field(name="Current Score", value=f"{total_wins_accum:g}", inline=True)
        # Fetch current rank (0-based) and total ranked players
        pipe = self.r.pipeline()
        pipe.zrevrank(K_LEADERBOARD, user_id)
        pipe.zcard(K_LEADERBOARD)
        rank_idx, total_ranked = await pipe.execute()

        if rank_idx is not None:
            rank_field = f"**{ordinal(rank_idx + 1)}** of **{total_ranked}**"
        else:
            # user might not be in the zset yet (e.g., zero score on a normal spin)
            rank_field = f"— of **{total_ranked}**"

        # later, when building the embed fields (you already add spins/score), include:
        embed.add_field(name="Rank", value=rank_field, inline=True)
        embed.timestamp = spin_time

        # Add the loss streak to the share message
        desc_lines.insert(0, loss_streak_text)
        logger.info("\n\t".join([user_name, f"Respin: {edit_in_place}"] + desc_lines))

        # view = ResultShareView(
        #     bot=self.bot,
        #     thread_id=SHARE_THREAD_ID,
        #     author_id=user.id,
        #     share_title=title,
        #     share_description=grid_str,
        #     summary="\n".join(desc_lines),
        #     color=embed.color,
        #     spin_time=spin_time
        # )
        view = self._make_result_view(interaction, embed, "\n".join(desc_lines))
        spin_auto_delete_sec = 60 * 10

        if edit_in_place:
            # overwrite this original ephemeral result message
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.edit_message(embed=embed, view=view, delete_after=spin_auto_delete_sec)
        else:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True, view=view)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True, view=view, delete_after=spin_auto_delete_sec)

    # Replace your start_duel method with this version (auto-cleans stale mappings before blocking)
    async def start_duel(self, interaction: discord.Interaction):
        await self._ensure_config_for_today()
        user = interaction.user
        uid = str(user.id)
        now = int(datetime.now(tz=NY_TZ).timestamp())

        # Auto-clean stale "pending 1v1" mapping before enforcing it
        existing_mid = await self.r.hget(K_DUEL_ACTIVE_BY_USER, uid)
        if existing_mid:
            dkey = K_DUEL_REQ.format(message_id=int(existing_mid))
            data = await self.r.get(dkey)
            stale = False
            if not data:
                stale = True
            else:
                try:
                    obj = json.loads(data)
                    # stale if not open or already past expiry
                    if obj.get("state") != "open" or now >= int(obj.get("expires_at", 0) or 0):
                        stale = True
                except Exception:
                    stale = True
            if stale:
                await self.r.hdel(K_DUEL_ACTIVE_BY_USER, uid)
            else:
                return await interaction.response.send_message(f"You already have a pending 1v1 challenge.\n{self_destruct_text(30)}", ephemeral=True, delete_after=30)

        # Fee: 5% of INITIATOR's points (opponent pays the SAME fixed fee)
        points = int(await self.r.hget(K_STATS_WINNINGS, uid) or 0)
        init_fee = max(1, int(points * DUEL_FEE_FRACTION))
        if points < init_fee or init_fee <= 0:
            return await interaction.response.send_message(f"Not enough points to start a 1v1.\n{self_destruct_text(30)}", ephemeral=True, delete_after=30)

        # Deduct initiator's fee now
        pipe = self.r.pipeline()
        pipe.hincrbyfloat(K_STATS_WINNINGS, uid, -init_fee)
        pipe.zincrby(K_LEADERBOARD, -init_fee, uid)
        await pipe.execute()

        expires_at = now + DUEL_TIMEOUT_SECONDS

        # Post public (silent) challenge with delete_after to avoid spam
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return await interaction.response.send_message("Run this in a text channel.", ephemeral=True)

        desc = (
            f"🗡️ <@{uid}> has issued a **1v1 challenge**!\n"
            f"Join cost: **{init_fee:g}**\n"
            f"Minimum payout: **{init_fee*2:g}**\n"
            f"Expires **<t:{expires_at}:R>**.\n"
            f"{self_destruct_text(DUEL_TIMEOUT_SECONDS)}"
        )
        embed = discord.Embed(title="1v1 Challenge", description=desc, color=discord.Color.blurple())

        # Prepare view; fill message_id after send
        duel_key = K_DUEL_REQ.format(message_id=0)
        view = DuelAcceptView(
            self,
            message_id=0,
            channel_id=channel.id,
            duel_key=duel_key,
            initiator_id=int(uid),
            initiator_fee=init_fee,
            expires_at=expires_at
        )
        posted = await channel.send(embed=embed, view=view, silent=True, delete_after=DUEL_TIMEOUT_SECONDS)
        duel_key = K_DUEL_REQ.format(message_id=posted.id)
        view.message_id = posted.id
        view.duel_key = duel_key

        duel_obj = {
            "state": "open",
            "initiator_id": int(uid),
            "initiator_name": getattr(user, "global_name", None) or user.name,
            "initiator_fee": init_fee,
            "created": now,
            "expires_at": expires_at,
            "channel_id": posted.channel.id,
            "message_id": posted.id
        }
        logger.info(f"[{duel_obj['initiator_name']}] ⚔️ Start Duel {json.dumps(duel_obj, indent=2)}")
        pipe = self.r.pipeline()
        pipe.set(duel_key, json.dumps(duel_obj), ex=DUEL_TIMEOUT_SECONDS + 120)
        pipe.hset(K_DUEL_ACTIVE_BY_USER, uid, posted.id)
        await pipe.execute()

        await interaction.response.send_message(f"1v1 challenge posted.\n{self_destruct_text(5)}", ephemeral=True, delete_after=5)

    async def accept_duel(self, interaction: discord.Interaction, view: DuelAcceptView):
        now = int(datetime.now(tz=NY_TZ).timestamp())
        user = interaction.user
        user_name = getattr(interaction.user, "global_name", None) or interaction.user.name

        data = await self.r.get(view.duel_key)
        if not data:
            logger.info(f"[{user_name}] This 1v1 has expired (Unknown 1v1).")
            return await interaction.response.send_message(f"This 1v1 has expired.\n{self_destruct_text(30)}", ephemeral=True, delete_after=30)
        obj = json.loads(data)
        if obj.get("state") != "open" or now >= int(obj["expires_at"]):
            logger.info(f"[{user_name}] This 1v1 has expired (Not open or is expired).")
            return await interaction.response.send_message(f"This 1v1 has expired.\n{self_destruct_text(30)}", ephemeral=True, delete_after=30)

        initiator_id = int(obj["initiator_id"])
        if interaction.user.id == initiator_id:
            logger.info(f"[{user_name}] You can't accept your own 1v1.")
            return await interaction.response.send_message(f"You can't accept your own 1v1.\n{self_destruct_text(10)}", ephemeral=True, delete_after=10)

        # Opponent pays the SAME fixed fee as calculated from the initiator
        init_fee = int(obj["initiator_fee"])
        opp_uid = str(interaction.user.id)
        opp_points = int(await self.r.hget(K_STATS_WINNINGS, opp_uid) or 0)
        if opp_points < init_fee:
            logger.info(f"[{user_name}] Not enough points to 1v1.")
            return await interaction.response.send_message(
                f"You need at least **{init_fee:g}** points to accept this 1v1.\n{self_destruct_text(30)}", ephemeral=True, delete_after=30
            )
        
        # Single accept guard
        lock_key = K_DUEL_LOCK.format(message_id=view.message_id)
        if not await self.r.set(lock_key, "1", ex=DUEL_TIMEOUT_SECONDS, nx=True):
            logger.info(f"[{user_name}] This 1v1 was already accepted or closed.")
            return await interaction.response.send_message(f"This 1v1 was already accepted or closed.\n{self_destruct_text(30)}", ephemeral=True, delete_after=30)

        # Deduct opponent fee now
        pipe = self.r.pipeline()
        pipe.hincrbyfloat(K_STATS_WINNINGS, opp_uid, -init_fee)
        pipe.zincrby(K_LEADERBOARD, -init_fee, opp_uid)
        await pipe.execute()

        # Mark accepted
        obj["state"] = "accepted"
        obj["opponent_id"] = int(opp_uid)
        obj["opponent_name"] = getattr(interaction.user, "global_name", None) or interaction.user.name
        await self.r.set(view.duel_key, json.dumps(obj), ex=DUEL_TIMEOUT_SECONDS)

        # Run both spins (normal rules, 5x5)
        cfg = self._config
        assert cfg is not None

        async def spin_once(user_id: int):
            grid, spin_total, breakdown, mult_used, grid_mult, total_mult = self._spin_and_score(cfg, bonus_multiplier=1.0, size=6)
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
            total = spin_total + jackpot_award
            return grid, total

        g1, t1 = await spin_once(initiator_id)
        g2, t2 = await spin_once(int(opp_uid))

        pot_total = init_fee + init_fee + t1 + t2
        house_cut = max(0, int(pot_total * 0.10))
        winner_payout = pot_total - house_cut

        # Decide winner (tie splits)
        split = False
        if t1 > t2:
            winner_id, loser_id = initiator_id, int(opp_uid)
        elif t2 > t1:
            winner_id, loser_id = int(opp_uid), initiator_id
        else:
            split = True
            winner_id = loser_id = None

        # 10% to jackpot
        if house_cut > 0:
            await self.r.incrbyfloat(K_JACKPOT_POOL, house_cut)

        # Credit payouts + W/L
        if split:
            share = winner_payout // 2
            pipe = self.r.pipeline()
            pipe.hincrbyfloat(K_STATS_WINNINGS, str(initiator_id), share)
            pipe.hincrbyfloat(K_STATS_WINNINGS, opp_uid, share)
            pipe.zincrby(K_LEADERBOARD, share, str(initiator_id))
            pipe.zincrby(K_LEADERBOARD, share, opp_uid)
            await pipe.execute()
        else:
            pipe = self.r.pipeline()
            pipe.hincrbyfloat(K_STATS_WINNINGS, str(winner_id), winner_payout)
            pipe.zincrby(K_LEADERBOARD, winner_payout, str(winner_id))
            pipe.hincrby(K_DUEL_WINS, str(winner_id), 1)
            pipe.hincrby(K_DUEL_LOSSES, str(loser_id), 1)
            await pipe.execute()

        # Close duel, clear mapping
        pipe = self.r.pipeline()
        pipe.hdel(K_DUEL_ACTIVE_BY_USER, str(initiator_id))
        pipe.delete(view.duel_key)
        await pipe.execute()

        # Disable accept button on the original message (it will auto-delete soon anyway)
        for item in view.children:
            item.disabled = True
        try:
            if interaction.message:
                await interaction.message.edit(view=view)
        except Exception:
            pass

        # Build RESULT embed: grids in DESCRIPTION; other info as FIELDS
        def grid_str(g): return "\n".join(" ".join(cell.token() for cell in row) for row in g)

        desc = (
            f"**Challenger <@{initiator_id}>**\n{grid_str(g1)}\n**Total:** {t1:g}\n\n"
            f"**Opponent <@{opp_uid}>**\n{grid_str(g2)}\n**Total:** {t2:g}"
        )

        stakes = (
            f"Challenger fee: **{init_fee:g}**\n"
            f"Opponent fee: **{init_fee:g}**\n"
            f"Pot: **{pot_total:g}**\n"
            f"House → Jackpot (10%): **{house_cut:g}**"
        )

        if split:
            outcome = f"Result: **Tie** — each receives **{(winner_payout // 2):g}**"
            color = discord.Color.purple()
        else:
            outcome = f"Winner: <@{winner_id}> receives **{winner_payout:g}**"
            color = discord.Color.purple()

        embed = discord.Embed(title="⚔️ 1v1 Result", description=desc, color=color)
        embed.add_field(name="Stakes & Pot", value=stakes, inline=False)
        embed.add_field(name="Outcome", value=outcome, inline=False)
        logger.info(f"[{initiator_id} ⚔️ {user_name}] 🥇 {winner_id or "Split"}\n{desc}")

        # Send results to the SHARE_THREAD_ID (silent). Fallback to current channel if not found.
        target = self.bot.get_channel(SHARE_THREAD_ID)
        if target is None:
            try:
                target = await self.bot.fetch_channel(SHARE_THREAD_ID)
            except Exception:
                target = None

        try:
            if isinstance(target, (discord.Thread, discord.TextChannel)):
                await target.send(embed=embed, silent=True)
            else:
                await interaction.channel.send(embed=embed, silent=True)
        except Exception:
            # last-resort fallback
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception:
                pass

        try:
            await interaction.response.send_message(f"1v1 resolved — results posted.\n{self_destruct_text(5)}", ephemeral=True, delete_after=5)
        except Exception:
            try:
                await interaction.followup.send("1v1 resolved — results posted.", ephemeral=True)
            except Exception:
                pass

        # Refresh persistent message (best-effort)
        try:
            await self._maybe_refresh_channel_message()
        except Exception:
            pass

        # Delete original challenge message to avoid channel clutter
        try:
            if interaction.message:
                await interaction.message.delete()
            else:
                ch = self.bot.get_channel(view.channel_id) or await self.bot.fetch_channel(view.channel_id)
                if isinstance(ch, (discord.TextChannel, discord.Thread)):
                    msg = await ch.fetch_message(view.message_id)
                    await msg.delete()
        except Exception:
            pass

    async def cancel_duel(self, interaction: discord.Interaction, view: "DuelAcceptView"):
        user_name = getattr(interaction.user, "global_name", None) or interaction.user.name
        # Only the initiator can cancel
        if interaction.user.id != view.initiator_id:
            logger.info(f"[{user_name}] Only the challenger can cancel this 1v1.")
            return await interaction.response.send_message(f"Only the challenger can cancel this 1v1.\n{self_destruct_text(30)}", ephemeral=True, delete_after=30)

        # Acquire same lock used by accept to prevent races
        lock_key = K_DUEL_LOCK.format(message_id=view.message_id)
        if not await self.r.set(lock_key, "1", ex=DUEL_TIMEOUT_SECONDS, nx=True):
            logger.info(f"[{user_name}] This 1v1 was already accepted or closed (lock).")
            return await interaction.response.send_message(f"This 1v1 was already accepted or closed.\n{self_destruct_text(30)}", ephemeral=True, delete_after=30)

        data = await self.r.get(view.duel_key)
        if not data:
            logger.info(f"[{user_name}] This 1v1 is no longer active")
            return await interaction.response.send_message(f"This 1v1 is no longer active.\n{self_destruct_text(30)}", ephemeral=True, delete_after=30)
        obj = json.loads(data)
        if obj.get("state") != "open":
            logger.info(f"[{user_name}] This 1v1 was already accepted or closed (state).")
            return await interaction.response.send_message(f"This 1v1 was already accepted or closed.\n{self_destruct_text(30)}", ephemeral=True, delete_after=30)

        # Mark cancelled & refund initiator's fee
        obj["state"] = "cancelled"
        await self.r.set(view.duel_key, json.dumps(obj), ex=60)

        uid = str(view.initiator_id)
        fee = int(obj.get("initiator_fee", view.initiator_fee))
        pipe = self.r.pipeline()
        pipe.hincrbyfloat(K_STATS_WINNINGS, uid, fee)
        pipe.zincrby(K_LEADERBOARD, fee, uid)
        pipe.hdel(K_DUEL_ACTIVE_BY_USER, uid)
        pipe.delete(view.duel_key)
        await pipe.execute()

        logger.info(f"[{user_name}] Cancelled their duel.")

        # Disable buttons and delete the challenge message (it also had delete_after, but remove now to de-clutter)
        for item in view.children:
            item.disabled = True
        try:
            if interaction.message:
                await interaction.message.delete()
            else:
                ch = self.bot.get_channel(view.channel_id) or await self.bot.fetch_channel(view.channel_id)
                if isinstance(ch, (discord.TextChannel, discord.Thread)):
                    msg = await ch.fetch_message(view.message_id)
                    await msg.delete()
        except Exception:
            pass

        # Ack
        try:
            await interaction.response.send_message(f"1v1 cancelled. Your fee was refunded.\n{self_destruct_text(60)}", ephemeral=True, delete_after=60)
        except Exception:
            try:
                await interaction.followup.send("1v1 cancelled. Your fee was refunded.", ephemeral=True)
            except Exception:
                pass

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

        # ↘ primary diagonal
        diag1 = [grid[i][i] for i in range(size)]
        amt, info = score_line(diag1)
        total_base += amt
        if info and amt > 0:
            breakdown.append(f"Diag ↘: {info}")

        # ↙ anti-diagonal
        diag2 = [grid[i][size - 1 - i] for i in range(size)]
        amt, info = score_line(diag2)
        total_base += amt
        if info and amt > 0:
            breakdown.append(f"Diag ↙: {info}")
        
        # Multipliers in-grid
        grid_mult = 1
        for it in (cell for row in grid for cell in row):
            if getattr(it, "is_multiplier", False) and it.multiplier > 1:
                grid_mult *= it.multiplier

        total_mult = grid_mult * (bonus_multiplier if bonus_multiplier else 1.0)
        mult_used = total_mult > 1.0
        total_after = int(total_base * total_mult)

        return grid, total_after, breakdown, mult_used, grid_mult, total_mult
    
    async def _refund_mega_usage(self, user_id: int, count: int) -> int:
        """
        Reduce today's MEGA usage by up to `count`, not below 0.
        Returns how many were actually refunded.
        """
        if count <= 0:
            return 0
        mkey = mega_plays_key(user_id, ny_date_str())
        # optimistic retry to avoid going negative under race
        for _ in range(3):
            try:
                async with self.r.pipeline() as p:
                    await p.watch(mkey)
                    used = int(await self.r.get(mkey) or 0)
                    if used <= 0:
                        await p.reset()
                        return 0
                    refund = min(used, count)
                    new_val = used - refund
                    p.multi()
                    if new_val > 0:
                        p.set(mkey, new_val, ex=60 * 60 * 48)
                    else:
                        p.delete(mkey)
                    await p.execute()
                    return refund
            except redis.WatchError:
                continue
        # fallback (non-atomic): best-effort clamp
        used = int(await self.r.get(mkey) or 0)
        if used <= 0:
            return 0
        refund = min(used, count)
        await self.r.set(mkey, max(0, used - refund), ex=60 * 60 * 48)
        return refund

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
                #formatted_total = fmt_spin_value(total_wins)
                #avg = (total_wins / spins) if spins > 0 else 0.0
                lb_lines.append(f"`{i:>2}.` <@{uid}> — **{total_wins:g}** | spins: **{spins}**")
        else:
            lb_lines.append("_No entries yet._")

        # Helper to render a zset into lines
        async def _render_big_list(key: str, title_suffix: str) -> Tuple[str, List[str]]:
            items = await self.r.zrevrange(key, 0, BIGGEST_SPINS_LEN - 1, withscores=True)
            lines: List[str] = []
            if items:
                for i, (member, score) in enumerate(items, start=1):
                    try:
                        obj = json.loads(member)
                        uid = int(obj.get("user_id", 0))
                        amt = int(obj.get("amount", int(score)))
                        # amt_fmtd = fmt_spin_value(amt)
                        utc_sec = int(obj.get("utc_sec", 0))
                        when = f"<t:{utc_sec}:R>" if utc_sec > 0 else ""
                        lines.append(f"`{i:>2}.` <@{uid}> — **{amt:g}** • {when}")
                    except Exception:
                        continue
            else:
                lines.append("_No spins recorded yet._")
            return title_suffix, lines

        mega_title, mega_lines = await _render_big_list(K_BIGGEST_SPINS_MEGA, f"Biggest MEGA Spins (Top {BIGGEST_SPINS_LEN})")
        norm_title, norm_lines = await _render_big_list(K_BIGGEST_SPINS_NORMAL, f"Biggest Normal Spins (Top {BIGGEST_SPINS_LEN})")

        # Fallback: if both new sets are empty but the legacy set has data, split it on the fly
        if (len(mega_lines) == 1 and "No spins" in mega_lines[0]) and (len(norm_lines) == 1 and "No spins" in norm_lines[0]):
            legacy = await self.r.zrevrange(K_BIGGEST_SPINS, 0, 199, withscores=True)  # up to 200, then we’ll slice
            mega_buf: List[Tuple[str, float]] = []
            norm_buf: List[Tuple[str, float]] = []
            for member, score in legacy:
                try:
                    obj = json.loads(member)
                    if obj.get("mega"):
                        mega_buf.append((member, score))
                    else:
                        norm_buf.append((member, score))
                except Exception:
                    continue

            def fmt_split(buf: List[Tuple[str, float]]) -> List[str]:
                out = []
                for i, (member, score) in enumerate(buf[:BIGGEST_SPINS_LEN], start=1):
                    obj = json.loads(member)
                    uid = int(obj.get("user_id", 0))
                    amt = int(obj.get("amount", int(score)))
                    # amt_fmtd = fmt_spin_value(amt)
                    utc_sec = int(obj.get("utc_sec", 0))
                    when = f"<t:{utc_sec}:R>" if utc_sec > 0 else ""
                    out.append(f"`{i:>2}.` <@{uid}> — **{amt:g}** • {when}")
                return out or ["_No spins recorded yet._"]

            mega_lines = fmt_split(mega_buf)
            norm_lines = fmt_split(norm_buf)

        # Big wins feed (most recent first)
        feed_raw = await self.r.lrange(K_BIGWINS, 0, BIGWINS_FEED_LEN-1)
        feed_lines: List[str] = []
        if feed_raw:
            for s in feed_raw:
                try:
                    obj = json.loads(s)
                    if "utc_sec" in obj:
                        feed_timestamp = f"<t:{obj["utc_sec"]}:R>"
                    else:
                        feed_timestamp = f"on {obj.get('date', '')}"
                    feed_lines.append(f"🎉 <@{obj['user_id']}> won **{int(obj['amount']):g}** {feed_timestamp}")
                except Exception:
                    continue
        else:
            feed_lines.append("_No big wins yet._")

        # last_cfg_date = await self.r.get(K_CONFIG_DATE)
        pool_val = int(await self.r.get(K_JACKPOT_POOL) or 0)
        # pool_fmtd = fmt_spin_value(pool_val)
        reset_ts = next_midnight_et_epoch()
        embed = discord.Embed(
            title=cfg.title,
            description=cfg.instructions + f", refills <t:{reset_ts}:R>.",
            color=discord.Color.gold(),
            timestamp=datetime.now(tz=NY_TZ)
        )

        # MEGA Loss Streaks (All-Time)
        best_map = await self.r.hgetall(K_MEGA_LOSS_STREAK_BEST)      # user_id -> best count
        best_ts  = await self.r.hgetall(K_MEGA_LOSS_STREAK_BEST_TS)   # user_id -> epoch seconds

        rows = []
        for uid_str, best_str in (best_map or {}).items():
            try:
                uid = int(uid_str)
                best = int(best_str)
                if best <= 0:
                    continue
                ts = int(best_ts.get(uid_str, "0") or 0)
                rows.append((uid, best, ts))
            except Exception:
                continue

        # sort: best desc, then most recently achieved desc
        rows.sort(key=lambda t: (t[1], t[2]), reverse=True)

        lines: List[str] = []
        if rows:
            for i, (uid, best, ts) in enumerate(rows[:MEGA_LOSS_STREAK_LB_LEN], start=1):
                # bonus corresponding to that best streak (what they would have gotten on the next MEGA then)
                if best >= 1:
                    bonus = MEGA_LOSS_BONUS_INITIAL * (MEGA_LOSS_BONUS_SCALE ** (best - 1))
                else:
                    bonus = 1
                when = f" • <t:{ts}:R>" if ts > 0 else ""
                lines.append(f"`{i:>2}.` <@{uid}> — **{best}** (bonus ×{bonus:g}){when}")
        else:
            lines.append("_No records yet._")


        embed.add_field(name=f"Progressive Jackpot ({JACKPOT_MIN_MATCHES}+ Matching Symbols)", value=f"{pool_val:g}\n**+{JACKPOT_NORMAL_INC_FRACTION * 100}%** per normal spin", inline=False)
        embed.add_field(name=f"Leaderboard (Top {LEADERBOARD_LEN})", value="\n".join(lb_lines), inline=False)
        embed.add_field(name=mega_title, value="\n".join(mega_lines), inline=False)
        embed.add_field(name=norm_title, value="\n".join(norm_lines), inline=False)
        embed.add_field(name="Recent Big Wins", value="\n".join(feed_lines), inline=False)
        embed.add_field(name="MEGA Loss Streaks (All-Time)", value="\n".join(lines), inline=False)
        wins_map = await self.r.hgetall(K_DUEL_WINS)
        loss_map = await self.r.hgetall(K_DUEL_LOSSES)

        duel_lines: List[str] = []
        if wins_map or loss_map:
            users = set(wins_map.keys()) | set(loss_map.keys())
            rows = []
            for uid in users:
                w = int(wins_map.get(uid, 0))
                l = int(loss_map.get(uid, 0))
                total = w + l
                if total <= 3: # Min num of games
                    continue
                rate = w / total
                rows.append((uid, w, l, rate))
            # sort: win rate desc, then wins desc
            rows.sort(key=lambda t: (t[3], t[1]), reverse=True)
            for i, (uid, w, l, rate) in enumerate(rows[:DUEL_LEADERBOARD_LEN], start=1):
                duel_lines.append(f"`{i:>2}.` <@{int(uid)}> — **{w}–{l}** ({rate:.0%})")
        else:
            duel_lines.append("_No duels yet._")

        embed.add_field(name="1v1 Leaderboard", value="\n".join(duel_lines), inline=False)
        return embed
    
    async def _maybe_refresh_channel_message(self, *, force: bool = False):
        """
        Refresh the persistent message at most once every REFRESH_THROTTLE_SECONDS.
        Use force=True to bypass the throttle (e.g., setup/reload).
        """
        now = int(time.time())
        if force:
            try:
                await self._refresh_channel_message()
            finally:
                await self.r.set(K_MAINMSG_LAST_REFRESH, now)
            return

        last_s = await self.r.get(K_MAINMSG_LAST_REFRESH)
        if last_s is not None:
            try:
                last = int(last_s)
                if now - last < REFRESH_THROTTLE_SECONDS:
                    return  # too soon; skip
            except Exception:
                pass

        # Prevent stampede: only one refresher at a time
        if not await self.r.set(K_MAINMSG_REFRESH_LOCK, "1", ex=10, nx=True):
            return

        try:
            await self._refresh_channel_message()
            await self.r.set(K_MAINMSG_LAST_REFRESH, now)
        finally:
            try:
                await self.r.delete(K_MAINMSG_REFRESH_LOCK)
            except Exception:
                pass


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
