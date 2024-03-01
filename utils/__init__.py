import asyncio
import contextvars
import time
import typing
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from functools import partial, wraps
from math import isinf

import discord
from discord import ui
from discord.ext import commands
from discord.ext.commands import Paginator

VS15 = "\N{VARIATION SELECTOR-15}"
VS16 = "\N{VARIATION SELECTOR-16}"

def shorten(s, /, width=2000, suffix=" [...]"):
    if len(s) > width:
        end = width - len(suffix)
        if not s[end].isspace():
            # cutting in middle of word
            clean = suffix.lstrip()
            end += len(suffix) - len(clean)
            suffix = clean
        return s[:end] + suffix
    return s

def escape(s, /, width=2000, suffix=" [...]"):
    escaped = discord.utils.escape_markdown(s)
    return shorten(escaped, width=width, suffix=suffix)

def natural_join(*words, delimiter=", ", conjunction="&", oxford_comma=False):
    n = len(words)
    if n == 0:
        return ""

    if n == 1:
        return words[0]

    if n == 2:
        return f"{words[0]} {conjunction} {words[1]}"

    conjunction = f", {conjunction}" if oxford_comma else f" {conjunction}"
    return delimiter.join(words[:-1]) + f"{conjunction} {words[-1]}"

def ordinal(n):
    n = int(n)
    return f"{n}{'tsnrhtdd'[(n//10%10!=1)*(n%10<4)*n%10::4]}"


class Codeblock(typing.NamedTuple):
    """language is optional for non-codeblocks and empty string for codeblocks without language"""
    code: str
    language: str | None
    @classmethod
    async def convert(cls, ctx, string):
        code = string
        language = None
        if string[:3] == string[-3:] == "```":
            code = code[3:-3]
            language = ""
            if "\n" in code:
                before, after = code.split("\n", maxsplit=1)
                if after.strip() and not any(w.isspace() for w in before):
                    code, language = (after, before)
        return cls(code=code, language=language)

    def __str__(self):
        if self.language is None:
            return self.code
        elif not self.language:
            return f"```{self.code}```"
        else:
            return f"```{self.language}\n{self.code}```"

def in_executor():
    def decorator(fn):
        @wraps(fn)
        async def decorated(*args, **kwargs):
            return await asyncio.get_running_loop().run_in_executor(None, partial(fn, *args, **kwargs))
        return decorated
    return decorator


class BlankPaginator(Paginator):
    def __init__(self):
        super().__init__(prefix=None, suffix=None)


class BucketedLock:
    # um yea
    def __init__(self):
        self._buckets = set()
        self._waiters = deque()

    @asynccontextmanager
    async def acquire(self, bucket):
        try:
            await self._acquire(bucket)
            yield
        finally:
            self.release(bucket)

    async def _acquire(self, bucket):
        if bucket not in self._buckets:
            # not locked, take it and return
            self._buckets.add(bucket)
            return

        future = asyncio.get_running_loop().create_future()
        future.bucket = bucket
        self._waiters.append(future)

        try:
            try:
                await future
            finally:
                self._waiters.remove(future)
        except asyncio.CancelledError:
            if bucket in self._buckets:
                # if it got cancelled it wont call release()
                # so we need to call it instead
                self._wake_up_first(bucket)
            raise

        # it's our turn, take the lock
        self._buckets.add(bucket)
        return

    def release(self, bucket):
        try:
            self._buckets.remove(bucket)
        except KeyError:
            pass
        else:
            self._wake_up_first(bucket)

    def _wake_up_first(self, bucket):
        if not self._waiters:
            return
        try:
            future = next(
                f for f in self._waiters
                if f.bucket == bucket
            )
        except StopIteration:
            return
        if not future.done():
            future.set_result(None)

    def __repr__(self):
        return (
            f"<{self.__class__.__name__}"
            f" locked={len(self._buckets)}"
            f" waiting={len(self._waiters)}"
            ">"
        )


class LRU(OrderedDict):
    def __init__(self, maxsize=128):
        super().__init__()
        self._maxsize = maxsize

    def __getitem__(self, key):
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if len(self) > self._maxsize:
            self.popitem(last=False)


def remember(maxsize=128):
    """*only works on bound methods
    *uses string representation of each positional for the key
    **objects with weak repr() wont be properly saved
    """
    if isinf(maxsize):
        cache = {}
    else:
        cache = LRU(int(maxsize))

    def make_key(args):
        return ":".join([repr(a) for a in args])

    def forget(*args, **kwargs):
        try:
            del cache[make_key(args)]
        except KeyError:
            return False
        else:
            return True

    def actual_decorator(fn):
        @wraps(fn)
        async def decorated(*args, **kwargs):
            key = make_key(args[1:]) # skip self
            task = cache.get(key)

            if task:
                if not task.done():
                    return await asyncio.shield(task)

                try:
                    return task.result()
                except Exception:
                    # cancelled/raised
                    pass

            cache[key] = task = asyncio.create_task(fn(*args, **kwargs))
            return await asyncio.shield(task)

        decorated.forget = forget
        return decorated

    return actual_decorator


class CommandHelpView(ui.View):
    def __init__(self, context):
        super().__init__(timeout=2 * 60.0)
        self.ctx = context
        if not context.command:
            self.clear_items()
            self.stop()

    @ui.button(label=f"\N{RIGHTWARDS ARROW WITH HOOK}{VS15} show help", style=discord.ButtonStyle.green)
    async def show_help(self, interaction, _):
        cmd = self.ctx.bot.help_command.copy()
        cmd.context = ctx = self.ctx.copy_context(interaction=interaction)
        await cmd.send_command_help(ctx.command)


def normalise_hms(seconds):
    minutes, seconds = divmod(float(seconds), 60.0)
    hours, minutes = divmod(minutes, 60.0)
    units = []
    for (unit, letter) in zip((hours, minutes, seconds), "hms"):
        if unit != 0:
            units.append(f"{int(unit)}{letter}")
    return "".join(units)


class _MultiViewCheckCallback:
    def __init__(self, predicates, view, item):
        self.predicates = predicates
        self.view = view
        self.item = item

    async def __call__(self, interaction):
        for predicate in self.predicates:
            ret = await predicate(self.view, interaction, self.item)
            if not ret:
                return False
        return True

class UsefulView(ui.View):
    def disable(self):
        for item in self.children:
            item.disabled = True

    def _init_children(self):
        children = super()._init_children()

        for item in children:
            original = item.callback.callback
            if predicates := getattr(original, "__discord_ui_interaction_check_custom__", None):
                item.interaction_check = _MultiViewCheckCallback(predicates, self, item)

        return children

    @classmethod
    def item_check(cls, method):
        def decorator(predicate):
            try:
                predicates = method.__discord_ui_interaction_check_custom__
            except AttributeError:
                method.__discord_ui_interaction_check_custom__ = predicates = []
            predicates.append(predicate)
            return predicate
        return decorator

_interaction = contextvars.ContextVar("interaction")

class ContextView(ui.View):
    def _scheduled_task(self, item, interaction):
        _interaction.set(interaction)
        return super()._scheduled_task(item, interaction)

    @property
    def interaction(self):
        return _interaction.get(None)


class ConfirmationPrompt(ContextView):
    def __init__(self):
        super().__init__(timeout=2 * 60.0)
        self.result = None

    async def _done(self, result):
        await self.interaction.response.defer()
        await self.interaction.delete_original_response()
        self.result = result
        self.stop()

    @ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def yes(self, interaction, button):
        await self._done(True)

    @ui.button(label="cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction, button):
        await self._done(False)
