# TwitterWatcher

A Discord bot that monitors Twitter/X accounts via Nitter RSS feeds and posts new tweets to a designated channel. Supports per-account role pings, multi-server (multi-guild) operation, and slash commands for easy management.

## Features

- Polls Nitter RSS feeds every 5 minutes for new tweets
- Posts tweet embeds to a configured Discord channel
- Optionally pings a Discord role when a specific account tweets
- Skips retweets and replies
- Extracts images, GIFs, and videos from tweet embeds
- Fetches Open Graph images from external links
- Deduplicates tweets across restarts via a local JSON store
- Fully multi-server: each guild has its own config, channel, and account list
- Slash commands for all management tasks (mod-only)

## Requirements

- Python 3.10+
- A [Discord bot](https://discord.com/developers/applications) with the `bot` and `applications.commands` scopes
- A Nitter instance (default: `https://nitter.net`)

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/yourusername/TwitterWatcher.git
cd TwitterWatcher
```

### 2. Install dependencies

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `DISCORD_BOT_TOKEN` | Your Discord bot token from the Developer Portal |
| `MOD_ROLE_ID` | *(Optional)* Role ID whose members can run management commands. If unset, only users with **Manage Server** can use them. |

### 4. (Optional) Configure a different Nitter instance

Edit the `NITTER_INSTANCE` constant in [twitter_cog.py](twitter_cog.py) if you want to use a self-hosted or alternative Nitter instance.

### 5. Run the bot

```bash
python bot.py
```

### 6. Sync slash commands

In any Discord channel the bot has access to, run:

```
!sync
```

This registers all slash commands globally. Only the bot owner can run this command.

## Slash Commands

All commands require **Manage Server** permission or the configured `MOD_ROLE_ID`, except `/twitter-status` which is open to everyone.

| Command | Description |
|---|---|
| `/twitter-add <account>` | Start watching a Twitter/X account |
| `/twitter-remove <account>` | Stop watching an account |
| `/twitter-list` | List all watched accounts |
| `/twitter-setchannel` | Set the current channel as the tweet output channel |
| `/twitter-setrole <account> <role>` | Ping a role when a specific account tweets |
| `/twitter-removerole <account>` | Remove the role ping for an account |
| `/twitter-setaccountchannel <account> <channel>` | Post a specific account's tweets to a different channel than the guild default |
| `/twitter-removeaccountchannel <account>` | Remove the channel override, falling back to the guild default |
| `/twitter-status` | Show current bot configuration |

## Data Files

These files are created automatically and are excluded from version control:

- `config.json` — per-guild settings (channel ID, watched accounts, role mappings)
- `seen_tweets.json` — tweet IDs that have already been posted (prevents duplicates on restart)

## Discord Bot Permissions

When inviting the bot, ensure it has:

- `Send Messages`
- `Embed Links`
- `Mention Everyone` (needed to ping roles)
- `Read Message History`

Invite URL scope: `bot` + `applications.commands`

## Notes

- Nitter's availability can be inconsistent. If tweets stop posting, try switching to a different public Nitter instance or host your own.
- The bot seeds existing tweets on first run (or when a new account is added) so it doesn't flood the channel with old content.
- Only original tweets are posted — retweets and `@` replies are filtered out.

## License

MIT
