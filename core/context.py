import asyncio
import io
import logging
from contextlib import contextmanager

import discord
from discord.ext.commands import Context as OriginalContext
from discord.utils import MISSING

__all__ = ("nanika_ctx",)

LOGGER = logging.getLogger(__name__)

class nanika_ctx(OriginalContext):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._alway_ephemeral = False
        self.invocation_id = None
        self._redirect = None
        self._dont_need_parsing = False
        self._debugging = False

    def purge(self, **kwargs):
        if self.guild:
            return self.channel.purge(**kwargs)
        # no bulk delete + can only delete messages from self
        me = self.me
        def check(m):
            return m.author == me
        kwargs["check"] = check
        kwargs["bulk"] = False
        return discord.abc._purge_helper(self.channel, **kwargs)

    @contextmanager
    def redirect(self, sendable):
        previous = self._redirect
        self._redirect = sendable
        try:
            yield
        finally:
            self._redirect = previous

    async def react(self, emoji, *, suppress=True):
        if self.interaction:
            # cant really react for hybrid
            return

        try:
            await self.message.add_reaction(emoji)
        except Exception:
            if not suppress:
                raise

    def alway_ephemeral(self):
        self._alway_ephemeral = True
        return self

    def dont_parse(self):
        self._dont_need_parsing = True
        return self

    def alway_debug(self):
        self._debugging = True
        return self

    def typing(self, *, ephemeral=MISSING):
        if ephemeral is MISSING:
            ephemeral = self._alway_ephemeral
        return super().typing(ephemeral=ephemeral)

    async def send(self, *args, **kwargs):
        if self._redirect is not None:
            return await self._redirect.send(*args, **kwargs)

        kwargs.setdefault("ephemeral", self._alway_ephemeral)
        anon = kwargs.pop("anonymous", False)

        # inspire by stella_bot
        maybe_reply = kwargs.pop("maybe_reply", True)
        if maybe_reply and not self.interaction:
            if (
                kwargs.get("reference", MISSING) is MISSING
                and (msg_id := getattr(self.channel, "last_message_id", None)) is not None
                and msg_id != self.message.id
            ):
                # choose to reply instead
                kwargs["reference"] = self.message.to_reference(fail_if_not_exists=False)
                kwargs.setdefault("mention_author", False) # without ping

        sent = await super().send(*args, **kwargs)

        if not anon:
            if self_cog := self.bot.get_cog("Self"):
                # schedule it as task so it doesnt delay the invocation flow
                t = asyncio.create_task(self_cog.blame(self, sent))
                t.add_done_callback(self.__blame_error_handle)

        return sent

    def __blame_error_handle(self, task):
        if exc := task.exception():
            LOGGER.error("blame error", exc_info=exc)

    async def plain(self, *args, **kwargs):
        kwargs["suppress_embeds"] = True
        kwargs["allowed_mentions"] = discord.AllowedMentions.none()
        return await self.send(*args, **kwargs)

    async def chain(self, sendables, *, initial=MISSING):
        ref = initial if initial is not MISSING else self.message
        for item in sendables:
            ref = await self.send(
                item,
                reference=ref and ref.to_reference(fail_if_not_exists=False),
                mention_author=False, maybe_reply=False
            )

    async def safe_send_codeblock(self, codeblock, *, filename=None, language=""):
        match codeblock:
            case (code, code_language):
                language = language or code_language
            case str():
                code = codeblock
            case _:
                raise TypeError("safe_send_codeblock() only can take (code, language) tuple or string")

        code = code.replace(self.bot.http.token, "[omg]")
        with_zws = code.replace("```", "``\u200b`")
        discord_markdown = f"```{language}\n{with_zws}```"
        if len(discord_markdown) > 2000:
            stream = io.BytesIO(code.encode("utf-8"))
            return await self.send(file=discord.File(stream, filename or f"code.{language or 'txt'}"))
        else:
            return await self.plain(discord_markdown)

    async def paginate(self, navi):
        navi.owner_id = self.author.id
        thing = await discord.utils.maybe_coroutine(navi.source.peek, self)
        prepped = await navi.prepare(thing)
        navi.update_items()
        await self.send(**prepped)

    # i feel unsafe naming this copy() since dpy does it a lot
    def copy_context(self, *, interaction=MISSING, with_invoke_id=False):
        copy = self.__class__(
            # t-t
            message=self.message,
            bot=self.bot,
            view=self.view,
            args=self.args,
            kwargs=self.kwargs,
            prefix=self.prefix,
            command=self.command,
            invoked_with=self.invoked_with,
            invoked_parents=self.invoked_parents,
            subcommand_passed=self.subcommand_passed,
            command_failed=self.command_failed,
            current_parameter=self.current_parameter,
            current_argument=self.current_argument,
            interaction=interaction if interaction is not MISSING else self.interaction
        )
        copy._alway_ephemeral = self._alway_ephemeral
        if with_invoke_id:
            copy.invocation_id = self.invocation_id
        return copy
