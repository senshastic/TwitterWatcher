import os
import traceback

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"{bot.user} has connected to Discord!")
    print(f"Bot is in {len(bot.guilds)} guild(s)")
    print("Loading cogs...")
    await load_cogs()
    print("Bot is ready!")
    print("Use !sync to register slash commands globally with Discord")


async def load_cogs():
    cogs = ["twitter_cog"]
    for cog in cogs:
        try:
            await bot.load_extension(cog)
            print(f"Loaded {cog}")
        except Exception:
            print(f"Failed to load {cog}:")
            traceback.print_exc()


@bot.command(name="sync")
@commands.is_owner()
async def sync(ctx):
    """Sync slash commands with Discord globally (Owner only)."""
    tree_commands = bot.tree.get_commands()
    print(f"Commands in tree before sync: {[c.name for c in tree_commands]}")
    if not tree_commands:
        await ctx.send(
            "Refusing to sync: the local command tree is empty. Syncing now would "
            "wipe all slash commands from Discord. Check the logs for a cog load "
            "failure, fix it, then restart the bot before syncing."
        )
        print("Sync aborted: tree is empty.")
        return
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"Synced {len(synced)} slash command(s) globally! (tree had {len(tree_commands)})")
        print(f"Synced {len(synced)} commands globally")
    except Exception as e:
        await ctx.send(f"Failed to sync commands: {e}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.NotOwner):
        await ctx.send("Only the bot owner can use this command.")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(f"Error: {error}")


if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN not found in .env")
        exit(1)
    bot.run(TOKEN)
