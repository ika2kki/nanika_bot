import random

from discord.ext.commands import Cog, command

import utils


async def setup(bot):
    await bot.add_cog(RNG(bot))

class RNG(Cog):
    @command(aliases=["choose"], require_var_positional=True)
    async def choice(self, ctx, *choices):
        """pick something at random"""
        await ctx.send(utils.shorten(random.choice(choices)))

    @command(require_var_positional=True)
    async def fate(self, ctx, *choices):
        """like choice, but the outcome is the same every time depending on your discord ID"""
        seed = random.Random(ctx.author.id)
        await ctx.send(utils.shorten(seed.choice(sorted(choices))))
