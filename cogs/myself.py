import asyncio
import contextlib
import io
import os
import random
import traceback
from collections import deque
from typing import Annotated, Literal

import aiohttp
import discord
import rapidfuzz
import rapidfuzz.process
import tabulate
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import FlagConverter, flag
from sphinx.util.inventory import InventoryFile as SphinxInventoryFile

import core
import utils


async def setup(bot):
    await bot.add_cog(myself(bot))

class myself(core.nanika_cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._inventories = {}

    async def cog_check(self, ctx):
        if ctx.command.qualified_name.startswith("rtfm"):
            # i put it in this cog but others can invoke it fine
            return True
        ctx.alway_debug()
        if await self.bot.is_owner(ctx.author):
            ctx.alway_debug()
            return True
        return False

    @core.command()
    async def reloadext(self, ctx, ext):
        """reload extension"""
        module = "cogs." + ext
        method = (
            self.bot.reload_extension
            if module in self.bot.extensions
            else self.bot.load_extension
        )
        try:
            await method(module)
        except commands.ExtensionError:
            await ctx.safe_send_codeblock(utils.Codeblock(code=traceback.format_exc(), language="py"))
        else:
            try:
                del self.bot.get_cog("Self").line_count
            except AttributeError:
                # cog dont exist/not cached
                pass
            await ctx.send(f"{ctx.command.qualified_name}: `{module}`")

    @core.command(aliases=["rl"])
    async def reloadlastext(self, ctx, spec: Literal["*"] = None):
        """reloads or loads the last edited extension"""
        modules = self.bot.edited_modules
        if not modules:
           return await ctx.send("no edits detected since start-up")

        while modules:
            mod = modules.popleft()
            await self.reloadext(ctx, ext=mod.parts[1].removesuffix(".py")) # skip cogs/

            if not spec:
                break

    @core.command()
    async def sync(self, ctx, spec: Literal["*", "."]):
        """syncing command"""
        async with ctx.typing():
            if spec == "*":
                guild = None
            else:
                guild = ctx.guild
                if not guild:
                    return await ctx.send("nanika u cant local sync in DMs")
            synced = await self.bot.sync_tree(guild=guild)
            await ctx.safe_send_codeblock(repr(synced), language="py")

    @core.command()
    async def die(self, ctx):
        """restart the bot"""
        try:
            await ctx.message.add_reaction("\N{DROPLET}")
        except Exception:
            pass

        await self.bot.close()

    @core.command()
    async def isort(self, ctx):
        """run isort on source files"""
        proc = await asyncio.create_subprocess_shell(
            "poetry run isort .",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        stream = stderr if stderr else stdout
        await ctx.send(stream.decode("utf-8"))

    async def execute_query(self, ctx, *, query, method):
        try:
            recordset = await method(query)
        except Exception:
            codeblock = f"```py\n{traceback.format_exc()}```"
            return await ctx.send(codeblock)
        else:
            if not recordset:
                return await ctx.send("it didnt return any rows")

        if isinstance(recordset, list):
            headers = [k for k in recordset[0].keys()]
            rows = [[str(v) for v in r.values()] for r in recordset]

            pretty = tabulate.tabulate(rows, headers, tablefmt="psql")
            codeblock = f"```\n{pretty}```"
        else:
            codeblock = recordset # it wont get shortened to unbound pretty

        if len(codeblock) < 2000:
            await ctx.send(codeblock)
        else:
            stream = io.BytesIO(pretty.encode("utf-8"))
            await ctx.send(file=discord.File(stream, "rows.txt"))

    @commands.group(invoke_without_command=True)
    async def sql(self, ctx, *, query: utils.Codeblock):
        """sql command"""
        await self.execute_query(ctx, query=query.code, method=self.bot.pgpool.fetch)

    @sql.command(name="execute", aliases=["exec", "eval"])
    async def sql_exec(self, ctx, *, query: utils.Codeblock):
        """like sql but can work with multi-statement; returns the status."""
        await self.execute_query(ctx, query=query.code, method=self.bot.pgpool.execute)

    #@commands.command()
    #async def edge(self, ctx, *, query: utils.Codeblock):
    #    """edgedb command"""
    #    # the CLI outputs in a pretty format so i wanna use that
    #    stdin = stdout = stderr = asyncio.subprocess.PIPE
    #    proc = await asyncio.create_subprocess_exec("edgedb", "query", query.code,
    #        stdin=stdin, stdout=stdout, stderr=stderr)
    #    await proc.wait() # apparently this can deadlock (idc)
    #    match proc.returncode:
    #        case 0:
    #            stream, lang = (proc.stdout, "json")
    #        case _:
    #            stream, lang = (proc.stderr, "ansi")
    #    await ctx.safe_send_codeblock((await stream.read()).decode("utf-8"), language=lang)

    class TestFlags(FlagConverter):
        a: str = flag(description="a") # typical
        b: str                         # no description
        c: str = flag(default="")      # with a default

    @core.command()
    async def test_flag_doc(self, ctx, *, flags: TestFlags = "..."):
        """this is testing command for add_flag_stuff()"""
        await ctx.send(flags)
        await ctx.send_help(ctx.command.qualified_name)

    @core.command(name="raise")
    async def raise_(self, ctx):
        """a command that raises an error"""
        raise RuntimeError("k")

    async def _request_library_inventory(self, url):
        async with aiohttp.ClientSession() as session:
            async with session.get(os.path.join(url, "objects.inv")) as response:
                response.raise_for_status()
                stream = io.BytesIO(await response.read())
                inventory = SphinxInventoryFile.load(stream, uri=url, joinfunc=os.path.join)
                prepped = {}
                for directive, members in inventory.items():
                    for member, (library, version, url, spec) in members.items():
                        name = url.rsplit("#", maxsplit=1)[-1] if spec == "-" else spec
                        prepped[(name, url)] = name
                return prepped

    def request_library_inventory(self, module, url):
        try:
            task = self._inventories[module]
        except KeyError:
            self._inventories[module] = task = asyncio.create_task(self._request_library_inventory(url))
        return task

    async def rtfm(self, ctx, *, module, search, url):
        inventory = await self.request_library_inventory(module, url)

        def processor(qualname):
            return qualname.replace(module + ".", "")

        matches = rapidfuzz.process.extract(search, inventory, limit=8,
                                            processor=processor, scorer=rapidfuzz.fuzz.QRatio)
        matches = [key for (choice, similarity, key) in matches]
        embed = discord.Embed()
        fmt = [
            f"[`{name}`]({url})"
            for name, url in matches
        ]
        embed.description = "\n".join(fmt)
        # set to random pastel colour
        embed.colour = discord.Colour.from_hsv(random.random(), 0.28, 0.97) # thxs to hayley
        await ctx.send(embed=embed)

    @commands.group(name="rtfm", invoke_without_command=True)
    async def rtfm_cmd(self, ctx, *, search):
        """search discord.py documentation"""
        await self.rtfm(ctx, module="discord", search=search, url="https://discordpy.readthedocs.io/en/latest/")

    @rtfm_cmd.command(name="asyncpg")
    async def rtfm_asyncpg(self, ctx, *, search):
        """search asyncpg documentation"""
        await self.rtfm(ctx, module="asyncpg", search=search, url="https://magicstack.github.io/asyncpg/current/")

    @rtfm_cmd.command(name="wavelink")
    async def rtfm_wavelink(self, ctx, *, search):
        """search wavelink documentation"""
        await self.rtfm(ctx, module="wavelink", search=search, url="https://wavelink.dev/en/latest/")

    @rtfm_cmd.command(name="invalidate")
    @commands.is_owner()
    async def rtfm_invalidate(self, ctx, *, library):
        """take away a library from the internal cache so the bot will request it again"""
        try:
            del self._inventories[library]
        except KeyError:
            await ctx.send("no library with that name cached")
        else:
            await ctx.react("\N{JOYSTICK}")
