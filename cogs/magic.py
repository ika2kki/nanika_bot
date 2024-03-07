from discord.ext import commands
import random
import core

class Magic(core.nanika_cog):
    @commands.command(name="8ball", aliases=["eightball"])
    async def eightball(self, ctx, *, question):
        answers = [
            "it will happen",
            "i decided yes",
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
            "mah, maybe",
            "there is doubts",
            "it wont happen"
        ]
        await ctx.send(f"magic eight ball say this: {random.choice(answers)}, in response to your question:\n{question}"[:2000])