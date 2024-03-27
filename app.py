from anathema import datetime_curse # isort: skip

import asyncio
import datetime
import logging
import pathlib
import signal
import traceback
import zoneinfo
from logging.handlers import TimedRotatingFileHandler

import asyncpg
import discord
import jishaku
from discord.ext import commands

import core

discord.VoiceClient.warn_nacl = False

jishaku.Flags.NO_UNDERSCORE = True
jishaku.Flags.NO_DM_TRACEBACK = True
#jishaku.Flags.HIDE = True

ROOT = logging.getLogger()
ROOT.setLevel(logging.INFO)

pathlib.Path("bot_log").mkdir(exist_ok=True)

filer = TimedRotatingFileHandler(
    filename="bot_log/nanika_bot.log",
    encoding="utf-8",
    #maxBytes=32 * 1024 * 1024,
    backupCount=7 * 8, # 8 weeks worth
    atTime=datetime.time(hour=0, minute=0, tzinfo=zoneinfo.ZoneInfo("Australia/Melbourne"))
)
filer.setFormatter(
    logging.Formatter(
        "[{asctime}] [{levelname:<8}] {name}: {message}",
        style="{",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
)
ROOT.addHandler(filer)

class PastelColourFormatter(logging.Formatter):
    COLOURS = {
        logging.DEBUG: "85",
        logging.INFO: "225",
        logging.WARNING: "209",
        logging.ERROR: "140",
        logging.CRITICAL: "1",
    }

    def __init__(self):
        super().__init__(
            "[{asctime}] [{levelname:<8}] {name}: {message}",
            style="{",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

    def format(self, record):
        # logging caches the formatted trace
        original = record.exc_text
        record.exc_text = None
        fmt = super().format(record)
        record.exc_text = original
        code = self.COLOURS[record.levelno]
        return "\n".join([
            f"\x1b[38;5;{code}m{line}\x1b[0m"
            for line in fmt.splitlines()
        ])

    def formatException(self, exc_info):
        fmt = traceback.format_exception(*exc_info)
        colour = self.COLOURS[logging.ERROR]
        return "\n".join([
            f"\x1b[38;5;{colour}m{line}\x1b[0m"
            for each_line in fmt
            # some lines contain internal newlines
            for line in each_line.splitlines()
        ])

writer = logging.StreamHandler()
writer.setFormatter(PastelColourFormatter())
ROOT.addHandler(writer)

class KeyboardInterruptHandler:
    def __init__(self):
        self.bot = None
        self._pending = False

    def __call__(self, code, frame):
        if self._pending or not self.bot:
            raise KeyboardInterrupt

        self.bot.loop.call_soon_threadsafe(
            self.bot.loop.create_task,
            self.bot.close()
        )
        self.bot.loop.call_soon_threadsafe(lambda: None) # no-op to wake up loop (important!)
        self._pending = True

    def bind_bot(self, bot: commands.Bot):
        self.bot = bot

on_sigint = KeyboardInterruptHandler()
signal.signal(signal.SIGINT, on_sigint)
#signal.siginterrupt(signal.SIGINT, False)

async def main():
    async with asyncpg.create_pool(core.configs["postgresql"]["uri"]) as pool:
        async with core.nanika_bot(asyncpg_pool=pool) as n:
            on_sigint.bind_bot(n)
            await n.start(core.configs["discord"]["token"])

    ROOT.info("no more asyncio")

asyncio.run(main())
ROOT.info("there is nothing else")
