from discord.ext import commands

__all__ = ("has_guild_permissions", "is_nsfw",)

def has_guild_permissions(**perms):
    async def predicate(ctx):
        return (
            await ctx.bot.is_owner(ctx.author)
            or await commands.has_guild_permissions(**perms).predicate(ctx)
        )
    return commands.check(predicate)

def is_nsfw():
    async def predicate(ctx):
        return (
            await ctx.bot.is_owner(ctx.author)
            or await commands.is_nsfw().predicate(ctx)
        )
    return commands.check(predicate)
