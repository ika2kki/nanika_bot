import asyncio
import datetime

from discord import app_commands
from discord.ext import commands, tasks

import core


class WFM(core.nanika_cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._ratelimit = app_commands.Cooldown(3, 1.0)
        self._api_lock = asyncio.Lock()

    async def cog_load(self):
        await super().cog_load()
        self.wfm_loop.start()

    async def cog_unload(self):
        await super().cog_unload()
        self.wfm_loop.cancel()

    async def request(self, route):
        async with self._api_lock:
            remaining = self._ratelimit.update_rate_limit()
            if remaining:
                await asyncio.sleep(remaining)

            async with self.session.get(route) as r:
                r.raise_for_status()
                return await r.json()

    @tasks.loop(minutes=5)
    async def wfm_loop(self):
        pass
