from discord.ext import commands

__all__ = ("nanika_cog",)

class nanika_cog(commands.Cog):
    def __init_subclass__(cls, **kwargs):
        cls.emoji = kwargs.pop("emoji", None)
        super().__init_subclass__(**kwargs)

    def __init__(self, bot):
        self.bot = bot
