from discord.ext import commands
import random

class Magic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="8ball", aliases=["eightball","magic8ball"])
    async def eight_ball(self, ctx, *, question):
        answers = [
            "It is certain.",
            "It is decidedly so.",
            "Without a doubt.",
            "Yes - definitely.",
            "You may rely on it.",
            "As I see it, no.",
            "I'm not sure.",
            "Ask again later.",
            "Better not tell you now.",
            "Cannot predict now.",
            "Concentrate and ask again.",
            "Don't count on it.",
            "My reply is no.",
            "I don't think so.",
            "Very doubtful.",
            "No."
        ]
        await ctx.send(f"Your question: {question}\n The 8ball replied: {random.choice(answers)}")