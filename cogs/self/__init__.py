from .blame import Blame
from .self import SelfBase


class SelfCog(Blame, SelfBase, name="Self"): ...

async def setup(bot):
    await bot.add_cog(SelfCog(bot))
