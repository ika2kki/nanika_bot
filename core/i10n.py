import contextvars
import pathlib

import discord
from discord import app_commands
from discord.app_commands import locale_str
from fluent_compiler.bundle import FluentBundle
from fluent_compiler.resource import FtlResource

__all__ = ("translate", "nanika_bot_translator",)

LOCALE = contextvars.ContextVar("LOCALE")
nanika_bot = None

def translate(string, locale=None, /, **params):
    locale = locale or LOCALE.get()

    message, pattern = (
        (string.message, string.extras.get("fluent"))
        if isinstance(string, locale_str)
        else (string, None)
    )

    dpy_translator = nanika_bot.tree.translator
    bundles = []
    bundles.append(dpy_translator.bundles[locale])
    bundles.append(dpy_translator.bundles[dpy_translator.native])

    id_ = message if pattern is None else pattern
    initial, _, _ = id_.partition(".")
    for bundle in bundles:
        if bundle.has_message(initial):
            translated, _ = bundle.format(id_, params)
            if translated is not None:
                return translated

    if pattern is None:
        raise ValueError(f'{locale!r} missing "{id_}"')

    return message

class nanika_bot_translator(app_commands.Translator):
    def __init__(self, bot, *, filepath, native):
        global nanika_bot
        nanika_bot = self.bot = bot
        self.native = native
        self.bundles = {}

        for path in pathlib.Path(filepath).iterdir():
            if path.is_dir():
                resources = []
                for f in path.glob("**/*.ftl"):
                    ftl = FtlResource.from_string(f.read_text(encoding="utf-8"))
                    resources.append(ftl)

                self.bundles[discord.Locale(path.name)] = FluentBundle(path.name, resources)

    async def translate(self, string, locale, ctx):
        try:
            pattern = string.extras["fluent"]
            bundle = self.bundles[locale]
        except KeyError:
            return None

        initial, _, _ = pattern.partition(".")
        if not bundle.has_message(initial):
            return None

        translated, exceptions = bundle.format(pattern)
        for exc in exceptions:
            raise exc
        return translated
