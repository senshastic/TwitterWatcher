import asyncio
import calendar
import ipaddress
import time
import json
import os
import re
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import discord
import feedparser
from discord import app_commands
from discord.ext import commands, tasks

__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))

CONFIG_FILE = os.path.join(__location__, "config.json")
SEEN_FILE = os.path.join(__location__, "seen_tweets.json")

NITTER_INSTANCE = "https://nitter.net"

DEFAULT_GUILD_CONFIG = {
    "channel_id": None,
    "accounts": [],
    "account_roles": {},
    "account_channels": {},
}


# ── Config helpers ──────────────────────────────────────────────────────────

def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump({}, f, indent=4)
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def save_config(config: dict) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)


def guild_config(config: dict, guild_id: int) -> dict:
    key = str(guild_id)
    if key not in config:
        config[key] = dict(DEFAULT_GUILD_CONFIG)
        config[key]["accounts"] = []
        config[key]["account_roles"] = {}
        config[key]["account_channels"] = {}
    return config[key]


def load_seen() -> dict:
    if not os.path.exists(SEEN_FILE):
        return {}
    with open(SEEN_FILE, "r") as f:
        return json.load(f)


def save_seen(seen: dict) -> None:
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f)


# ── RSS helpers ─────────────────────────────────────────────────────────────

def clean_title(title: str) -> str:
    title = re.sub(r'^RT by @\w+:\s*', '', title)
    urls = re.findall(r'https?://\S+', title)
    for url in urls:
        if title.count(url) > 1:
            title = title.replace(url, '', title.count(url) - 1).strip()
    return title


def is_safe_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname
        ip = ipaddress.ip_address(socket.gethostbyname(host))
        return ip.is_global and not ip.is_private and not ip.is_loopback and not ip.is_link_local
    except Exception:
        return False


def fetch_og_image(url: str) -> str | None:
    class _Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.result = None
        def handle_starttag(self, tag, attrs):
            if tag == 'meta' and not self.result:
                d = dict(attrs)
                if d.get('property') in ('og:image', 'og:image:url') or d.get('name') == 'og:image':
                    self.result = d.get('content')
    if not is_safe_url(url):
        print(f"Blocked unsafe URL: {url}")
        return None
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read(50000).decode("utf-8", errors="ignore")
        parser = _Parser()
        parser.feed(html)
        if not parser.result:
            print(f"No og:image found at {url}")
        return parser.result
    except Exception as e:
        print(f"fetch_og_image error for {url}: {e}")
        return None


def get_tweets(nitter_instance: str, account: str) -> list[dict]:
    url = f"{nitter_instance.rstrip('/')}/{account}/rss"
    feed = feedparser.parse(url)

    tweets = []
    for entry in feed.entries:
        raw_title = entry.get("title", "")
        if re.match(r'^R to @\w+:', raw_title) or re.match(r'^RT by @\w+:', raw_title):
            continue

        image_url = None
        video_url = None
        external_link = None
        if hasattr(entry, "summary"):
            def resolve_nitter_path(src: str) -> str:
                pic_match = re.search(r'/pic/(.+)', src)
                if pic_match:
                    path = urllib.parse.unquote(pic_match.group(1))
                    if path.startswith("pbs.twimg.com"):
                        return "https://" + path
                    else:
                        return "https://pbs.twimg.com/" + path
                if src.startswith("/"):
                    return nitter_instance.rstrip("/") + src
                return src

            img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', entry.summary)
            if img_match:
                image_url = resolve_nitter_path(img_match.group(1))

            # GIFs and videos appear as <video> tags in Nitter RSS
            video_match = re.search(r'<video[^>]+src=["\']([^"\']+)["\']', entry.summary)
            if not video_match:
                video_match = re.search(r'<source[^>]+src=["\']([^"\']+)["\']', entry.summary)
            if video_match:
                video_url = resolve_nitter_path(video_match.group(1))
                # Use the poster as the embed thumbnail if no static image
                if not image_url:
                    poster_match = re.search(r'<video[^>]+poster=["\']([^"\']+)["\']', entry.summary)
                    if poster_match:
                        image_url = resolve_nitter_path(poster_match.group(1))

            for href in re.findall(r'<a[^>]+href=["\']([^"\']+)["\']', entry.summary):
                if href.startswith("http") and "twitter.com" not in href and "x.com" not in href and nitter_instance not in href:
                    external_link = href
                    break

        if not external_link:
            for url in re.findall(r'https?://\S+', raw_title):
                if "twitter.com" not in url and "x.com" not in url:
                    external_link = url
                    break

        timestamp = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            timestamp = int(calendar.timegm(entry.published_parsed))

        tweets.append({
            "id": entry.get("id", entry.get("link", "")),
            "title": clean_title(raw_title),
            "link": entry.get("link", "").replace(nitter_instance.rstrip("/"), "https://x.com"),
            "author": account,
            "published": entry.get("published", ""),
            "timestamp": timestamp,
            "image_url": image_url,
            "video_url": video_url,
            "external_link": external_link,
        })

    return tweets


def build_embed(tweet: dict) -> discord.Embed:
    timestamp = tweet.get("timestamp")
    description = tweet["title"]
    if timestamp:
        description += f"\n\n<t:{timestamp}:f>"

    embed = discord.Embed(
        description=description,
        url=tweet["link"],
        color=0x1DA1F2,
    )
    embed.set_author(
        name=f"@{tweet['author']}",
        url=f"https://x.com/{tweet['author']}",
        icon_url=f"https://unavatar.io/twitter/{tweet['author']}",
    )
    image_url = tweet.get("image_url")
    if image_url and image_url.startswith("https://"):
        embed.set_image(url=image_url)
    return embed


# ── Permission check ─────────────────────────────────────────────────────────

def is_mod(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.manage_guild:
        return True
    mod_role_id = os.getenv("MOD_ROLE_ID")
    if mod_role_id:
        return any(str(r.id) == mod_role_id for r in interaction.user.roles)
    return False


# ── Cog ──────────────────────────────────────────────────────────────────────

class TwitterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = load_config()
        self.seen = load_seen()   # dict: guild_id_str -> list of seen tweet IDs
        self.seeded = set()       # set of guild_id_str that have been seeded
        self.poll_tweets.start()

    def cog_unload(self):
        self.poll_tweets.cancel()

    @tasks.loop(seconds=300)
    async def poll_tweets(self):
        nitter = NITTER_INSTANCE

        for guild_id_str, gcfg in self.config.items():
            channel_id = gcfg.get("channel_id")
            account_channels = gcfg.get("account_channels", {})
            if not channel_id and not account_channels:
                continue

            guild_seen = set(self.seen.get(guild_id_str, []))
            accounts = gcfg.get("accounts", [])

            print(f"[{guild_id_str}] Polling {len(accounts)} account(s)...")

            for account in accounts:
                try:
                    loop = asyncio.get_event_loop()
                    tweets = await loop.run_in_executor(None, get_tweets, nitter, account)
                    print(f"[{guild_id_str}] @{account}: {len(tweets)} tweets fetched")
                except Exception as e:
                    print(f"[{guild_id_str}] Error fetching @{account}: {e}")
                    continue

                now = int(calendar.timegm(time.gmtime()))
                new_tweets = [
                    t for t in tweets
                    if t["id"] not in guild_seen
                    and t.get("timestamp") is not None
                    and (now - t["timestamp"]) < 86400  # ignore tweets older than 24 hours
                ]
                print(f"[{guild_id_str}] @{account}: {len(new_tweets)} new")

                if guild_id_str not in self.seeded:
                    for t in tweets:
                        guild_seen.add(t["id"])
                    continue

                target_channel_id = account_channels.get(account, channel_id)
                if not target_channel_id:
                    continue
                channel = self.bot.get_channel(int(target_channel_id))
                if channel is None:
                    continue

                for tweet in reversed(new_tweets):
                    try:
                        if not tweet.get("image_url") and tweet.get("external_link"):
                            loop = asyncio.get_event_loop()
                            tweet["image_url"] = await loop.run_in_executor(None, fetch_og_image, tweet["external_link"])
                        role_id = gcfg.get("account_roles", {}).get(account)
                        ping = f"<@&{role_id}> " if role_id else ""
                        content = f"{ping}{tweet['link']}"
                        await channel.send(
                            content=content,
                            embed=build_embed(tweet),
                            allowed_mentions=discord.AllowedMentions(roles=True),
                        )
                        if tweet.get("video_url"):
                            await channel.send(tweet["video_url"])
                        guild_seen.add(tweet["id"])
                        print(f"[{guild_id_str}] Posted tweet from @{account}: {tweet['link']}")
                    except Exception as e:
                        print(f"[{guild_id_str}] Error posting tweet from @{account}: {e}")

            self.seen[guild_id_str] = list(guild_seen)

            if guild_id_str not in self.seeded:
                self.seeded.add(guild_id_str)
                print(f"[{guild_id_str}] Seeded {len(guild_seen)} existing tweets.")

        save_seen(self.seen)

    @poll_tweets.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    # ── Slash commands ────────────────────────────────────────────────────────

    @app_commands.command(name="twitter-add", description="Start watching a Twitter/X account")
    @app_commands.describe(account="Twitter username (with or without @)")
    async def twitter_add(self, interaction: discord.Interaction, account: str):
        if not is_mod(interaction):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        account = account.lstrip("@")
        gcfg = guild_config(self.config, interaction.guild_id)
        if account in gcfg["accounts"]:
            await interaction.response.send_message(f"`@{account}` is already being watched.", ephemeral=True)
            return
        gcfg["accounts"].append(account)
        save_config(self.config)

        # Seed existing tweets immediately so we don't spam on first poll
        await interaction.response.defer()
        guild_id_str = str(interaction.guild_id)
        try:
            loop = asyncio.get_event_loop()
            tweets = await loop.run_in_executor(None, get_tweets, NITTER_INSTANCE, account)
            guild_seen = set(self.seen.get(guild_id_str, []))
            for t in tweets:
                guild_seen.add(t["id"])
            self.seen[guild_id_str] = list(guild_seen)
            save_seen(self.seen)
            print(f"[{guild_id_str}] Seeded {len(tweets)} tweets for @{account}")
        except Exception as e:
            print(f"[{guild_id_str}] Failed to seed @{account}: {e}")

        await interaction.followup.send(f"Now watching `@{account}`.")

    @app_commands.command(name="twitter-remove", description="Stop watching a Twitter/X account")
    @app_commands.describe(account="Twitter username to remove")
    async def twitter_remove(self, interaction: discord.Interaction, account: str):
        if not is_mod(interaction):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        account = account.lstrip("@")
        gcfg = guild_config(self.config, interaction.guild_id)
        if account not in gcfg["accounts"]:
            await interaction.response.send_message(f"`@{account}` is not in the watch list.", ephemeral=True)
            return
        gcfg["accounts"].remove(account)
        gcfg.get("account_roles", {}).pop(account, None)
        gcfg.get("account_channels", {}).pop(account, None)
        save_config(self.config)
        await interaction.response.send_message(f"Stopped watching `@{account}`.")

    @app_commands.command(name="twitter-list", description="Show all watched Twitter/X accounts")
    async def twitter_list(self, interaction: discord.Interaction):
        if not is_mod(interaction):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        gcfg = guild_config(self.config, interaction.guild_id)
        if not gcfg["accounts"]:
            await interaction.response.send_message(
                "No accounts are being watched. Use `/twitter-add` to add one.", ephemeral=True
            )
            return
        account_list = "\n".join(f"• `@{a}`" for a in gcfg["accounts"])
        embed = discord.Embed(title="Watched Twitter/X accounts", description=account_list, color=0x1DA1F2)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="twitter-setchannel", description="Post tweets in this channel")
    async def twitter_setchannel(self, interaction: discord.Interaction):
        if not is_mod(interaction):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        gcfg = guild_config(self.config, interaction.guild_id)
        gcfg["channel_id"] = interaction.channel_id
        save_config(self.config)
        await interaction.response.send_message(f"Tweet posts will now be sent to {interaction.channel.mention}.")

    @app_commands.command(name="twitter-setrole", description="Ping a role when a watched account tweets")
    @app_commands.describe(account="Twitter username", role="Role to ping")
    async def twitter_setrole(self, interaction: discord.Interaction, account: str, role: discord.Role):
        if not is_mod(interaction):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        account = account.lstrip("@")
        gcfg = guild_config(self.config, interaction.guild_id)
        if account not in gcfg["accounts"]:
            await interaction.response.send_message(f"`@{account}` is not being watched. Add it first with `/twitter-add`.", ephemeral=True)
            return
        gcfg["account_roles"][account] = role.id
        save_config(self.config)
        await interaction.response.send_message(f"{role.mention} will be pinged for new tweets from `@{account}`.")

    @app_commands.command(name="twitter-removerole", description="Stop pinging a role for a watched account")
    @app_commands.describe(account="Twitter username")
    async def twitter_removerole(self, interaction: discord.Interaction, account: str):
        if not is_mod(interaction):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        account = account.lstrip("@")
        gcfg = guild_config(self.config, interaction.guild_id)
        if gcfg.get("account_roles", {}).pop(account, None) is None:
            await interaction.response.send_message(f"`@{account}` has no role assigned.", ephemeral=True)
            return
        save_config(self.config)
        await interaction.response.send_message(f"Removed role ping for `@{account}`.")

    @app_commands.command(name="twitter-setaccountchannel", description="Post tweets from a specific account to a different channel")
    @app_commands.describe(account="Twitter username", channel="Channel to post this account's tweets to")
    async def twitter_setaccountchannel(self, interaction: discord.Interaction, account: str, channel: discord.TextChannel):
        if not is_mod(interaction):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        account = account.lstrip("@")
        gcfg = guild_config(self.config, interaction.guild_id)
        if account not in gcfg["accounts"]:
            await interaction.response.send_message(f"`@{account}` is not being watched. Add it first with `/twitter-add`.", ephemeral=True)
            return
        gcfg.setdefault("account_channels", {})[account] = channel.id
        save_config(self.config)
        await interaction.response.send_message(f"`@{account}` tweets will now be posted to {channel.mention}.")

    @app_commands.command(name="twitter-removeaccountchannel", description="Stop overriding the channel for a specific account")
    @app_commands.describe(account="Twitter username")
    async def twitter_removeaccountchannel(self, interaction: discord.Interaction, account: str):
        if not is_mod(interaction):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        account = account.lstrip("@")
        gcfg = guild_config(self.config, interaction.guild_id)
        if gcfg.get("account_channels", {}).pop(account, None) is None:
            await interaction.response.send_message(f"`@{account}` has no channel override.", ephemeral=True)
            return
        save_config(self.config)
        await interaction.response.send_message(f"`@{account}` will now post to the default channel.")

    @app_commands.command(name="twitter-status", description="Show RivalsRelay status and config")
    async def twitter_status(self, interaction: discord.Interaction):
        gcfg = guild_config(self.config, interaction.guild_id)
        channel_id = gcfg.get("channel_id")
        channel_mention = f"<#{channel_id}>" if channel_id else "not set — use `/twitter-setchannel`"
        embed = discord.Embed(title="RivalsRelay status", color=0x1DA1F2)
        embed.add_field(name="Posting to", value=channel_mention, inline=False)
        embed.add_field(name="Accounts watched", value=str(len(gcfg["accounts"])), inline=True)
        embed.add_field(name="Nitter instance", value=NITTER_INSTANCE, inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    cog = TwitterCog(bot)
    await bot.add_cog(cog)
    # Explicitly register app commands to the tree in case the discord.py
    # version doesn't auto-register Cog app commands via add_cog.
    for cmd in cog.get_app_commands():
        try:
            bot.tree.add_command(cmd)
        except discord.app_commands.errors.CommandAlreadyRegistered:
            pass
    print(f"Registered {len(cog.get_app_commands())} app commands to tree")
