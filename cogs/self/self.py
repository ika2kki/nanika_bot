import asyncio
import datetime
import functools
import importlib.metadata
import inspect
import io
import json
import logging
import pathlib
import re
from collections import Counter
from math import inf
from typing import Annotated

import discord
import rapidfuzz as fuzzy
import starlight
from discord import app_commands, ui
from discord.ext import commands
from discord.ext.commands import (
    BadArgument,
    Converter,
    DefaultHelpCommand,
    FlagConverter,
    group,
    has_guild_permissions
)
from discord.utils import maybe_coroutine as maybe_coro

import core
import utils
from core import navi

LOGGER = logging.getLogger(__name__)

@starlight.describe_help_command(command="command or cog to search for")
class nanika_bot_help_command(DefaultHelpCommand, starlight.HelpHybridCommand):
    class dummy(Exception): ...

    def __init__(self):
        super().__init__(show_parameter_descriptions=False, command_attrs=self.attrs)

    @property
    def attrs(self):
        return {"help": "shows help for the bot"}

    @property
    def bot(self):
        return self.context.bot

    def get_destination(self):
        # this is for the blame
        # normally ctx.channel get return so it dont end up calling my ctx.send method
        return self.context

    # little way to make it so jishaku is invisible to anyone except me.
    # otherwise, people can still find help for it if they type in
    # a command name explicility and i dont think its appriopate
    # same should apply to ghost command...
    async def prepare_help_command(self, ctx, argument):
        if argument is None:
            return

        cog = self.bot.get_cog(argument)
        if not cog:
            cmd = self.bot.get_command(argument)
            if cmd:
                if getattr(cmd, "ghost", False):
                    raise self.dummy
                cog = cmd.cog

        if cog and cog.qualified_name in {"Jishaku",}:
            raise self.dummy

    def get_prefix(self, command):
        if isinstance(command, (app_commands.Command, app_commands.Group)):
            # obviously only slash can be used for app commands
            return "/"
        used = self.context.clean_prefix
        return (
            # if this command was invoked as prefix, use that prefix
            used if used != "/"
            # otherwise if we're viewing help on a prefix command from /help, use a default prefix
            # the guild mightve removed this prefix but its ok for display purposes
            else self.bot.default_prefixes[0]
        )

    async def command_callback(self, ctx, *, command=None):
        # now catch it
        try:
            await super().command_callback(ctx, command=command)
        except self.dummy:
            string = await maybe_coro(self.command_not_found, self.remove_mentions(command.split()[0]))
            await self.send_error_message(string)

    def walk_with_respect_to_hidden(self, cmd):
        if not cmd.hidden:
            yield cmd
            if isinstance(cmd, commands.GroupMixin):
                for subc in cmd.commands:
                    yield from self.walk_with_respect_to_hidden(subc)

    def walk_all_command(self, bot):
        for cmd in bot.commands:
            yield from self.walk_with_respect_to_hidden(cmd)

    @starlight.help_autocomplete(parameter_name="command")
    async def autocomplete_callback(self, interaction, typed):
        # context isnt available here
        bot = interaction.client

        # dont want to fully call checks here
        # theres only mostly 2 relevant things to consider:
        # - whether the command is hidden
        # - whether the command is owner-only (pending solution)

        def predicate(cmd):
            if cmd.cog and cmd.cog.qualified_name in {"Jishaku",}:
                return False

            return True

        choices = sorted(c.qualified_name for c in self.walk_all_command(bot) if predicate(c))
        if typed:
            # narrow it down
            choices = [
                choice for (choice, similarity, index)
                in fuzzy.process.extract(typed, choices, scorer=fuzzy.fuzz.QRatio)]
        return [app_commands.Choice(name=c, value=c) for c in choices[:25]]

    async def send_pages(self):
        destination = self.get_destination()
        if self.context.command is not self._command_impl:
            # being invoked outside of the help command
            # this is considerate of ctx.send_help()
            # and importantly the "show help" button, so it doesnt cloud up chat
            # i dont want the app command to be ephemeral otherwies
            destination.alway_ephemeral()
        navigator = navi.Navi(navi.blank(self.paginator.pages))
        await destination.paginate(navigator)

    async def send_bot_help(self, cmd_map):
        self.paginator.add_line("bot for nanika", empty=True)

        gh = core.configs["github"]
        proc = await asyncio.create_subprocess_shell(
            f'git log origin/{gh["branch"]} -n 3 --format="%H:%s"',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if not stderr:
            self.paginator.add_line("latest 3 revisions:")
            for commit in stdout.decode().splitlines():
                sha1, msg = commit.split(":", maxsplit=1)
                self.paginator.add_line(self.shorten_text(
                    self.indent * " " + sha1[:7] + " " + utils.escape(msg, width=inf)
                ))
            self.paginator.add_line()

        await super().send_bot_help(cmd_map)

    def shorten_text(self, text):
        return utils.shorten(text, width=self.width)

    def add_command_formatting(self, cmd):
        super().add_command_formatting(cmd)
        self.add_flags_stuff(cmd)

    def add_flags_stuff(self, cmd):
        try:
            flag_converter = next(
                param.converter
                for param in cmd.clean_params.values()
                if isinstance(param.converter, FlagConverter)
                or inspect.isclass(param.converter)
                and issubclass(param.converter, FlagConverter)
            )
        except StopIteration:
            return

        flags = flag_converter.get_flags().values()

        string_width = discord.utils._string_width
        maxlen = max([string_width(flag.name) for flag in flags], default=0)

        prefix = flag_converter.__commands_flag_prefix__
        delimiter = flag_converter.__commands_flag_delimiter__

        self.paginator.add_line("flags:")

        for flag in flags:
            width = maxlen - string_width(flag.name) - len(flag.name)
            (o,c) = "<>" if flag.required else "[]"
            usage = (
                o
                + prefix
                + flag.name.ljust(width)
                + delimiter
                + c
                + " "
                + (flag.description or "undescribed flag.")
            )
            self.paginator.add_line(self.shorten_text((self.indent * " ") + usage))

        self.paginator.add_line()
        self.paginator.add_line(
            f"to invoke with a flag, type the flag syntax and the value but without the brackets\n"
            "example:\n"
            f"{self.indent * ' '}?command {prefix}something{delimiter} hello\n"
            "the <> brackets around the flag means its required, [] means its optional"
        )

    def command_not_found(self, cmd):
        return "dont know a command like that"

    def subcommand_not_found(self, group, cmd):
        return "dont know a subcommand like that"

class SelfBase(core.nanika_cog):
    def __init__(self, bot):
        self.bot = bot
        # i want the prefix updates to be atomic from
        # the moment the command starts until to what the bot says
        # i know i can use defaultdict(asyncio.Lock) here
        # but i dont want the dict to grow with each guild
        self._write_lock = utils.BucketedLock()
        self._original_help_command = bot.help_command
        # im really like the default........
        bot.help_command = nanika_bot_help_command()
        bot.help_command.cog = self

    def cog_unload(self):
        self.bot.help_command = self._original_help_command

    async def cog_command_error(self, ctx, error):
        if isinstance(error, BadArgument):
            await ctx.send(str(error))

    @functools.cached_property
    def line_count(self):
        return sum(
            len(path.read_text().splitlines())
            for path in pathlib.Path(".").glob("**/*.py")
        )

    @core.command(aliases=["about"])
    async def aboutme(self, ctx):
        """about me command"""
        githubs = core.configs["github"]
        proc = await asyncio.create_subprocess_shell(
            f'git log origin/{githubs["branch"]} -n 3 --format="%H:%at:%s"',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        commits = []
        for commit in stdout.decode().splitlines():
            sha1, timestamp, msg = commit.split(":", maxsplit=2)
            when = datetime.datetime.fromtimestamp(float(timestamp))
            url = "https://github.com/%s/%s/commit/%s" % (githubs["me"], githubs["repository"], sha1)
            commits.append(f"[`{sha1[:7]}`]({url}): {utils.escape(msg, width=75)} ({when:R})")
        dpy_version = importlib.metadata.metadata("discord.py").json["version"]
        await ctx.send(
            "\*nanikas discord botto\n"
            "\- testing/proof of concept/helpful bot -\n"
            f"made with [discord.py `{dpy_version}`](<https://github.com/Rapptz/discord.py/>) ({self.line_count} loc) https://discord.gg/dpy\n"
            + ((
                "latest 3 revisions:\n"
                + "\n".join(commits)
            )
            if commits else "")
        )

    @core.command(aliases=["src"], disabled=True, hidden=True)
    async def source(self, ctx, *, thing=None):
        """link the source for a bot command"""
        gh = core.configs["github"]
        if not thing:
            return await ctx.send("https://github.com/%s/%s/" % (gh["me"], gh["repository"]))
        thing = thing.lower()
        didnt_find = "sorry idk what"
        if cmd := self.bot.get_command(thing):
            if cmd.cog:
                cog_module = cmd.cog.__module__
                if not cog_module.startswith("cogs"):
                    # 3rd party module (basically only jishaku)
                    return await ctx.send(didnt_find)
                cog_filename = cog_module.split(".")[-1]
                if cog_filename.startswith("_"):
                    # private for me
                    return await ctx.send(didnt_find)

            qual = cmd.qualified_name
            if qual == "help":
                # unwrap help command because it otherwise point to
                # command_callback method which not helpful on it own
                code = self.bot.help_command.__class__
                module = code.__module__
            else:
                code = cmd.callback.__code__
                module = cmd.callback.__module__
            codes, linestart = inspect.getsourcelines(code)
            lineend = linestart + len(codes) - 1 # skip trailing \n
            filepath = module.replace(".", "/")
            base = "https://github.com/%s/%s/blob/%s/" % (gh["me"], gh["repository"], gh["branch"])
            await ctx.send(f"here is source for {qual!r} " + base + filepath + ".py" + f"#L{linestart}-L{lineend}")
        else:
            await ctx.send(didnt_find)

    @group(aliases=["prefix"], invoke_without_command=True, ignore_extra=False)
    async def prefixes(self, ctx):
        """show the bot prefixes"""
        prefixes = (
            await self.bot.remember_guild_prefixes(ctx.guild.id)
            if ctx.guild
            else self.bot.default_prefixes
        )
        pg = utils.BlankPaginator()
                                         # always add bot mention as #1
        for (index, prefix) in enumerate((ctx.me.mention, *prefixes), start=1):
            pg.add_line(f"{index}. {discord.utils.escape_markdown(prefix)}")
        #await ctx.chain(pg.pages, initial=None)
        await ctx.paginate(navi.Navi(navi.blank(pg.pages)))

    class BotPrefix(Converter):
        async def convert(self, ctx, argument):
            argument = argument.lower()
            if argument.startswith("/"):
                raise BadArgument("/ is kept for slash commands only")
            bot_user_id = ctx.me.id
            if argument.startswith((f"<@{bot_user_id}>", f"<@!{bot_user_id}>")):
                raise BadArgument("prefix cant start with mention")
            elif len(argument) > 200:
                raise BadArgument("please \N{LESS-THAN OR EQUAL TO}200 chars")
            return argument

    # due to array this is basically the only statement needed to update prefixes
    UPSERT_GUILD_PREFIXES = """
        INSERT INTO bot_prefixes VALUES ($1, $2)
        ON CONFLICT (id)
        DO UPDATE SET prefixes=EXCLUDED.prefixes"""

    @prefixes.command(name="add", ignore_extra=False)
    @has_guild_permissions(manage_guild=True)
    async def prefix_add(self, ctx, prefix: Annotated[str, BotPrefix]):
        """add a custom prefix
        to include spaces in prefix, wrap it in "
        for example: wwprefixes add "prefix "

        limited to 100 prefixes.
        """
        id_ = ctx.guild.id
        async with self._write_lock.acquire(id_):
            prefixes = await self.bot.remember_guild_prefixes(id_)
            if prefix in prefixes:
                return await ctx.send("already")
            copy = prefixes.copy() # dont mutate cached value in case insert fails
            copy.append(prefix)
            async with self.bot.pgpool.acquire() as c, c.transaction():
                n = await c.fetchval("SELECT cardinality(prefixes) FROM bot_prefixes WHERE id=$1", id_)
                if n is not None and n >= 100:
                    return await ctx.send("limited to 100 prefixes")

                await c.execute(self.UPSERT_GUILD_PREFIXES, id_, copy)
                self.bot.remember_guild_prefixes.forget(id_)
                await ctx.send(f"listening for {len(copy)} custom prefixes now")

    @prefixes.command(name="delete", ignore_extra=False)
    @has_guild_permissions(manage_guild=True)
    async def prefix_delete(self, ctx, prefix: str.lower):
        """delete a custom prefix
        prefix with space in it have to be quoted to be deleted properly
        """
        id_ = ctx.guild.id
        async with self._write_lock.acquire(id_):
            prefixes = await self.bot.remember_guild_prefixes(id_)
            prefixes = prefixes.copy()
            try:
                prefixes.remove(prefix)
            except ValueError:
                await ctx.send("dont have that as a prefix")
            else:
                await self.bot.pgpool.execute(self.UPSERT_GUILD_PREFIXES, id_, prefixes)
                self.bot.remember_guild_prefixes.forget(id_)
                await ctx.send("its gone")

    @prefixes.command(name="default", ignore_extra=False)
    @has_guild_permissions(manage_guild=True)
    async def prefix_default(self, ctx):
        """reset back to default prefixes"""
        id_ = ctx.guild.id
        async with self._write_lock.acquire(id_):
            rows = await self.bot.pgpool.fetchval("DELETE FROM bot_prefixes WHERE id=$1 RETURNING prefixes", id_)
            was_default = rows is None or Counter(rows) == Counter(self.bot.default_prefixes)
            self.bot.remember_guild_prefixes.forget(id_)
            await ctx.send("default me" if not was_default else "?-?")

    async def send_payload(self, ctx, payload):
        as_json = json.dumps(payload, indent=4)
        await ctx.safe_send_codeblock(utils.Codeblock(code=as_json, language="json"))

    @core.command()
    async def msgraw(self, ctx, message: discord.Message):
        """show the raw API payload for a message"""
        payload = await self.bot.http.get_message(message.channel.id, message.id)
        await self.send_payload(ctx, payload)

    @core.command()
    async def userraw(self, ctx, *, user: discord.User):
        """show the raw API payload for a user"""
        payload = await self.bot.http.get_user(user.id)
        await self.send_payload(ctx, payload)

    @core.command()
    async def unix(self, ctx):
        """unix time now"""
        now = int(ctx.message.created_at.timestamp())
        fmts = [
            f"<t:{now}:{style}>"
            for style in discord.utils.TimestampStyle.__args__
        ]
        maxlen = max([len(f) for f in fmts])
        await ctx.send(
            f"{now}\n"
            + "\n".join(f"\{fmt:<{maxlen-len(fmt)}} - {fmt}" for fmt in fmts)
        )

    from typing import Literal, Optional

    @core.command(aliases=["avy"])
    async def avatar(self, ctx, spec: Optional[Literal["*", ".", "-"]], *, user: discord.User = commands.Author):
        """show user avatar
        incl. links for other formats
        type a specifier afterwards to only show a certain type of avatar
        . -> resolves to guild, global or default
        * -> global or default
        - -> default avatar
        """
        attrs = ["guild_avatar", "avatar", "default_avatar"]
        offset = 0
        if spec == ".":
            if not ctx.guild:
                return await ctx.send("we r in dm's")
        elif spec == "*":
            offset += 1
        elif spec == "-":
            offset += 2

        avatar = next(avy for attr in attrs[offset:] if (avy := getattr(user, attr, None)))
        avatar = avatar.with_size(2048)
        formats = ["gif"] if avatar.is_animated() else ["png", "jpg", "webp"]

        def as_hyperlink(fmt, *, embedded=False):
            url = avatar.with_format(fmt).url
            if embedded:
                fmt = "*" + fmt
            else:
                url = f"<{url}>"
            return f"[{fmt}]({url})"

        hyperlinks = [
            as_hyperlink(fmt, embedded=index == 0)
            for index, fmt in enumerate(formats)
        ]
        await ctx.send(" ".join(hyperlinks))
