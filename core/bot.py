import json
import logging
import pathlib
import re
import traceback
from collections import deque
from functools import cached_property
from math import inf

import discord
import watchdog
import watchdog.observers
import wavelink
from discord import app_commands as ac
from discord.ext import commands
from discord.ext.commands.core import \
    _CaseInsensitiveDict as CaseInsensitiveDictionary
from watchdog.events import FileSystemEventHandler
from .i10n import nanika_bot_translator
import utils

from .config import configs
from .context import nanika_ctx
from .trace import aiohttp_trace_thing

__all__ = ("Terrier", "nanika_bot",)

LOGGER = logging.getLogger(__name__)

class Terrier(FileSystemEventHandler):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    def on_modified(self, event):
        path = pathlib.Path(event.src_path)
        if path.is_dir() or path.suffix != ".py":
            return
        cogs = pathlib.Path("cogs/")
        relative = path.relative_to(cogs.resolve())
        # by being relative to ./cogs/, the first part after
        # will always be the package or file name, which is what we care about
        mod = cogs / relative.parts[0]
        if mod not in self.bot.edited_modules:
            self.bot.edited_modules.append(mod)

class nanika_bot(commands.Bot):
    def __init__(self, *, asyncpg_pool):
        super().__init__(
            "hello i am string", # get_prefix() is overriden so command_prefix is never used
            intents=discord.Intents.all(),
            strip_after_prefix=True,
            http_trace=aiohttp_trace_thing(),
            max_messages=5000, # default 5x
            case_insensitive=True
        )
        self.pgpool = asyncpg_pool
        self.edited_modules = deque(maxlen=255)
        self.default_prefixes = ["ww", "!", "?"]
        self.debug_prefix = "wa"
        self._BotBase__cogs = CaseInsensitiveDictionary()

    async def on_message_edit(self, before, after):
        await self.process_commands(after)

    async def normal_get_prefix(self, message):
        augment = commands.when_mentioned_or
        if await self.is_owner(message.author):
            return augment(self.default_prefixes[0], self.debug_prefix)(self, message)
        if guild := message.guild:
            from_guild = await self.remember_guild_prefixes(guild.id)
            return augment(*from_guild)(self, message)
        return augment(*self.default_prefixes)(self, message)

    async def get_prefix(self, message):
        prefixes = await self.normal_get_prefix(message)
        pattern = "|".join(re.escape(p) for p in prefixes)
        if message.content and (
            match := re.match(f"({pattern})", message.content[:100], re.IGNORECASE)
        ):
            return match.group(1)
        return prefixes

    async def get_context(self, origin, *, cls=None):
        return await super().get_context(origin, cls=cls or nanika_ctx)

    @utils.remember(inf)
    async def remember_guild_prefixes(self, guild_id):
        query = "SELECT prefixes FROM bot_prefixes WHERE id=$1"
        prefixes = await self.pgpool.fetchval(query, guild_id)
        # [] is valid so check for None
        return prefixes if prefixes is not None else self.default_prefixes

    async def on_ready(self):
        LOGGER.info(f"stuff stuff im up {self.user} (id: {self.user.id})")

    async def setup_hook(self):
        app_command_translator = nanika_bot_translator(self, filepath="fluent_ftl", native=discord.Locale.british_english)
        await self.tree.set_translator(app_command_translator)

        try:
            await self.load_extension("jishaku")
        except commands.ExtensionError as exc:
            LOGGER.error("jishaku extension didn't load properly", exc_info=exc)

        base = pathlib.Path("cogs/")

        self.watcher = watchdog.observers.Observer()
        self.watcher.schedule(
            Terrier(self),
            base.resolve(),
            recursive=True
        )
        self.watcher.start()

        nodes = [wavelink.Node(uri=configs["lavalink"]["url"], password=configs["lavalink"]["password"])]
        await wavelink.Pool.connect(nodes=nodes, client=self, cache_capacity=None)

        for path in base.iterdir():
            # only add the top level modules
            if path.is_dir():
                if not (path / "__init__.py").exists():
                    continue
            else:
                if path.suffix != ".py":
                    continue

            module = ".".join(path.parts).removesuffix(".py")
            try:
                await self.load_extension(module)
            except commands.ExtensionError as exc:
                kind = "unknown" if isinstance(exc, commands.ExtensionFailed) else "known"
                LOGGER.error(f"Ignoring {kind} exception in extension {module}", exc_info=exc)

    async def close(self):
        self.watcher.stop()
        try:
            self.watcher.join()
        except Exception:
            pass
        await super().close()

    async def sync_tree(self, guild=None):
        synced = await self.tree.sync(guild=guild)
        if guild is None:
            with open("app_cmds.json", mode="w") as f:
                json.dump(
                    [c.to_dict() for c in synced],
                    f, separators=(",", ":") # compact
                )
                try:
                    del self.app_cmds # invalidate cached value
                except AttributeError:
                    pass
        return synced

    @cached_property
    def app_cmds(self):
        try:
            with open("app_cmds.json", mode="r") as f:
                data = json.load(f)
        except FileNotFoundError:
            return []
        else:
            return [ac.AppCommand(data=c, state=self._connection) for c in data]

    async def on_command_error(self, ctx, error):
        if isinstance(error, (commands.CommandInvokeError, commands.ConversionError, commands.HybridCommandError)):
            LOGGER.error(f"Ignoring unknown exception in command {ctx.command.qualified_name}", exc_info=error)

            probably_nanika_debugging = ctx._debugging or await self.is_owner(ctx.author) and ctx.prefix == self.debug_prefix
            if probably_nanika_debugging:
                fmt = "".join(traceback.format_exception(error.__class__, error, error.__traceback__))
                await ctx.safe_send_codeblock(utils.Codeblock(code=fmt, language="py"))

        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("only can use this command in a server")

        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"argument `{error.param.name}` missing", view=utils.CommandHelpView(ctx))

        elif isinstance(error, commands.TooManyArguments):
            say = "too many arguments"

            copy = commands.view.StringView(ctx.view.buffer)
            copy.index = ctx.view.index
            copy.previous = ctx.view.previous

            remaining = 0
            try:
                while copy.get_quoted_word():
                    remaining += 1
                    if remaining > 10:
                        break
                    copy.skip_ws()
            except commands.ArgumentParsingError:
                pass

            if remaining > 0:
                # it can be 0 if something like wwprefix add <whatever> "blablah
                say += f" ({min(remaining, 10)}{'+' if remaining > 10 else ''} too many)"
            await ctx.send(say, view=utils.CommandHelpView(ctx))

        elif isinstance(error, commands.UnexpectedQuoteError):
            await ctx.send("unexpected quote somewhere")
        elif isinstance(error, commands.InvalidEndOfQuotedStringError):
            await ctx.send("spaces should follow quotes")
        elif isinstance(error, commands.ExpectedClosingQuoteError):
            await ctx.send("an open quote wasn't closed")

    @property
    def something(self):
        return self.get_user(236802254298939392)
