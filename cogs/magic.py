import random

from discord.ext import commands

import core


class Magic(core.nanika_cog):
    @commands.command(name="8ball", aliases=["eightball"])
    async def eightball(self, ctx, *, question):
        answers = [
            "it will happen",
            "i decided yes",
            "maaybe",
            "uhhhhhhh- sureeee",
            "yea",
            "there is no doubts",
            "it will def happen",
            "u can rely on it if that makes u comfy",
            "from what i see, nah",
            "im unsure",
            "try me again later",
            "i cant tell you now, for your safety",
            "its too blurry for me rn",
            "you werent focusing?",
            "not v reliable",
            "nah",
            "mmmm dunno",
            "mah, maybe",
            "there is doubts",
            "it wont happen"
        ]
        await ctx.reply(f"magic eight ball say this:\n{random.choice(answers)}", mention_author=False)


async def setup(bot):
    await bot.add_cog(Magic(bot))
