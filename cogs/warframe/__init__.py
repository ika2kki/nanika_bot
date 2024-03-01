import aiohttp

from .warframe import Warframe
from .wfm import WFM


class WarframeCog(Warframe, WFM, name="Warframe"):
    async def cog_load(self):
        await super().cog_load()
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        await super().cog_unload()
        await self.session.close()

async def setup(bot):
    await bot.add_cog(WarframeCog(bot))
