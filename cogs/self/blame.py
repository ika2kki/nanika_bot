import datetime
import logging

import discord
from discord.ext import commands

import core
import utils

LOGGER = logging.getLogger(__name__)

class Blame(core.nanika_cog):
    # per the invoke flow, check-onces always run first
    # but not for subsequent times by the help command since it is called by the bot only.
    # i dont want to use before_invoke since that is only for succesful invocations but blame
    # needs to work on everything ideally
    async def bot_check_once(self, ctx):
        if ctx.invocation_id is None: # because of myself can happen
            ctx.invocation_id = await self.bot.pgpool.fetchval("""
                INSERT INTO invocations (message_id, channel_id, guild_id, author_id, command, prefix)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                ctx.message.id,                             # $1
                ctx.channel.id,                             # $2
                ctx.guild and ctx.guild.id,                 # $3
                ctx.author.id,                              # $4
                ctx.command and ctx.command.qualified_name, # $5
                ctx.prefix                                  # $6
            )
        return True

    async def blame(self, ctx, sent):
        """called by ctx.send"""
        await self.bot.pgpool.execute("""
            INSERT INTO blame (message_id, channel_id, guild_id, invocation_id)
            VALUES ($1, $2, $3, $4)
            """,
            sent.id,
            sent.channel.id,
            sent.guild and sent.guild.id,
            ctx.invocation_id # this can be none for unbound context
        )

    @commands.command(name="blame")
    async def blame_command(self, ctx, message: discord.Message = commands.param(default=None)):
        """check who caused the bot to send a certain message.
        put a message link/id or reply to a message to use it.
        """
        if not message:
            ref = ctx.message.reference
            if ref and ref.message_id:
                try:
                    message = await ctx.fetch_message(ref.message_id)
                except discord.HTTPException:
                    return await ctx.send("couldnt find that message")
            else:
                try:
                    message = await anext(
                        m async for m in
                        ctx.history(before=ctx.message, limit=4)
                        if m.author == ctx.me
                    )
                except (StopAsyncIteration, discord.HTTPException):
                    return await ctx.send("couldnt find a message. put a message URL or reply to something")

        if message.author != ctx.me:
            return await ctx.send("?-? i didnt send that message")

        invocation = await self.remember_invocation_from_message(message.id)
        if not invocation:
            return await ctx.send("im unsure")

        author_id = invocation["author_id"]
        author = "*you" if author_id == ctx.author.id else f"<@{author_id}>"

        to_send = f"{author} made me say [this]({message.jump_url})"
        if cmd := invocation["command"]:
            to_send += f" when invoking command `{cmd}`"

        route = invocation["guild_id"] or "@me"
        jump_url = (
            "https://discord.com/channels"
            f"/{route}"
            f"/{invocation['channel_id']}"
            f"/{invocation['message_id']}"
        )
        to_send += f" (original: {jump_url})"
        await ctx.plain(to_send)

    @utils.remember()
    async def remember_invocation_from_message(self, message_id):
        return await self.bot.pgpool.fetchrow("""
            SELECT invocations.*
            FROM blame
            INNER JOIN invocations ON invocations.id=blame.invocation_id
            WHERE blame.message_id=$1""",
            message_id
        )

    EMOJIS = (
        "\N{WASTEBASKET}",
        "\N{PUT LITTER IN ITS PLACE SYMBOL}",
    )
    REQUIRED_PERMISSIONS = (
        "read_messages",
        "read_message_history",
        "manage_messages",
    )

    @core.nanika_cog.listener("on_raw_reaction_add")
    async def delete_message_on_bin_reaction(self, payload):
        if str(payload.emoji).startswith(self.EMOJIS):
            created_at = discord.utils.snowflake_time(payload.message_id)
            now = discord.utils.utcnow()
            if (now - created_at) >= datetime.timedelta(days=2, hours=12):
                return

            invocation = await self.remember_invocation_from_message(payload.message_id)
            if invocation and payload.user_id in (invocation["author_id"], self.bot.something.id):
                # it can be deleted safely

                guild = self.bot.get_guild(payload.guild_id)
                channel = guild and guild.get_channel(payload.channel_id)
                if not channel:
                    return

                perms = channel.permissions_for(guild.me)
                if all(getattr(perms, permission) for permission in self.REQUIRED_PERMISSIONS):
                    partial = channel.get_partial_message(payload.message_id)
                    try:
                        await partial.delete()
                    except discord.HTTPException:
                        pass
