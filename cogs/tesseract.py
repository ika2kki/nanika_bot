import asyncio
import io
import os
import pathlib

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw

import core
import utils


async def setup(bot):
    await bot.add_cog(Tesseract(bot))

class Semy(asyncio.Semaphore):
    @property
    def waiting(self):
        return sum(not w.cancelled() for w in (self._waiters or ()))

class Tesseract(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.context_cmd = app_commands.ContextMenu(
            name="Tesseract OCR",
            callback=self.tess_context_cmd_adapter
        )
        bot.tree.add_command(self.context_cmd)
        self._processing = set()
        self._semaphore = Semy(10) # put a concurrency limit just to be safe

    def cog_unload(self):
        self.bot.tree.remove_command(self.context_cmd.name, type=self.context_cmd.type)

    async def tess_context_cmd_adapter(self, interaction, message: discord.Message):
        if message.author == self.bot.user:
            return await interaction.response.send_message("sorry u cant use tesseract on messages that i send",
                                                           ephemeral=True)
        ctx = await core.nanika_ctx.from_interaction(interaction)
        ctx.message = message
        await self.tess(ctx)

    @commands.group(aliases=["tesseract", "ocr"])
    async def tess(self, ctx):
        """tesseract ocr
        japanese and english only.
        """
        ctx.alway_ephemeral()
        attachment = next(iter(ctx.message.attachments), None)
        if not attachment:
            ref = ctx.message.reference
            if ref and ref.message_id:
                try:
                    message = await ctx.fetch_message(ref.message_id)
                except discord.NotFound:
                    pass
                else:
                    if message.author == ctx.me:
                        return await ctx.send("sorry you cant use tesseract on my own messages")
                    attachment = next(iter(message.attachments), None)
            else:
                try:
                    message = await anext(
                        m async for m in
                        ctx.history(before=ctx.message, limit=5)
                        if m.attachments and m.author != ctx.me
                    )
                except (StopAsyncIteration, discord.HTTPException):
                    return await ctx.send(
                        "couldnt find an attachment. put a message URL or to reply to a message with an attachment"
                    )
                else:
                    attachment = message.attachments[0]

            if not attachment:
                msg = (
                    "attach file to your command invocation"
                    if not ctx.interaction
                    else "message doesnt have any attachment"
                )
                await ctx.reply(msg, mention_author=False)
                return

        limit = min((ctx.guild and ctx.guild.filesize_limit) or 8388608, 104857600)
        if attachment.size >= limit:
            await ctx.reply("sorry this attachment is too big", mention_author=False)
            return
        elif hash(attachment) in self._processing:
            await ctx.reply("im already processing this attachment", mention_author=False)
            return

        async with ctx.typing():
            try:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=5.0)
            except asyncio.TimeoutError:
                return await ctx.send("too many people are using this command atm, try again later")

            try:
                # tesseract can write to stdout (saves having to write/read from disk)
                # but i dont know how to get it to work when i specify multiple parameters
                # (i cant know when the boxes end and when the text starts)

                base = pathlib.Path("tess/")
                base.mkdir(exist_ok=True)
                name = os.urandom(16).hex()
                tessfile = base / (name + ".txt")
                boxfile = base / (name + ".box")

                language = ctx.invoked_subcommand and ctx.invoked_subcommand.name or "jpn+eng"

                try:
                    self._processing.add(hash(attachment))
                    stream = io.BytesIO(await attachment.read())

                    proc = await asyncio.create_subprocess_exec(
                        "tesseract", *(
                            "stdin",
                            (base.resolve() / name).as_posix(),
                            "--oem", "1",
                            "--psm", "11",
                            "-l", language,
                            "-c", "tessedit_create_txt=1",
                            "-c", "tessedit_create_boxfile=1"
                        ),
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    try:
                        await asyncio.wait_for(proc.communicate(stream.read()), timeout=15.0)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await ctx.reply("it was taking too long")
                        return

                    if proc.returncode != 0:
                        await ctx.reply("something went wrong...")
                        return

                    files = []

                    content = "\n".join(
                        s for line in tessfile.read_text().splitlines()
                        if (s := line.strip())
                    )
                    if not content:
                        await ctx.reply("didnt find any text")
                        return

                    escaped = discord.utils.escape_markdown(content)
                    if len(escaped) > 2000:
                        files.append(discord.File(io.BytesIO(content.encode("utf-8")), attachment.filename + ".txt"))
                        escaped = discord.utils.MISSING

                    stream.seek(0)
                    fp = await self.draw_boxes(stream, boxfile)
                    files.append(discord.File(fp, attachment.filename + ".png"))
                    await ctx.reply(
                        escaped,
                        files=files,
                        allowed_mentions=discord.AllowedMentions.none(),
                        suppress_embeds=True
                    )
                finally:
                    self._processing.discard(hash(attachment))
                    tessfile.unlink(missing_ok=True)
                    boxfile.unlink(missing_ok=True)
            finally:
                self._semaphore.release()

    @utils.in_executor()
    def draw_boxes(self, stream, boxfile):
        boxes = boxfile.read_text().splitlines()
        image = Image.open(stream)
        draw = ImageDraw.Draw(image)
        for line in boxes:
            left, bottom, right, top = [int(n) for n in line.split()[-5:-1]]
            box = (
                (left, image.height - top),
                (right, image.height - bottom)
            )
            draw.rectangle(box, outline="#88F2A4", width=2)
        buffer = io.BytesIO()
        image.save(buffer, "png")
        buffer.seek(0)
        return buffer

    @tess.command(name="jpn")
    async def tess_jpn(self, ctx):
        """japanese only"""

    @tess.command(name="eng")
    async def tess_eng(self, ctx):
        """english only"""
