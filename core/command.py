from discord.ext import commands

__all__ = ("nanika_command", "command", "nanika_group", "group",)

class nanika_command(commands.Command):
    def __init__(self, *args, **kwargs):
        # ghost attribute is to make command completely invisible
        # from help command. this is different to hidden which can still be shown
        # if it is requested help specifically, like "wwhelp lurking"
        self.ghost = kwargs.pop("ghost", False)
        if self.ghost:
            kwargs["hidden"] = True
        super().__init__(*args, **kwargs)

    async def _parse_arguments(self, ctx):
        if not ctx._dont_need_parsing:
            await super()._parse_arguments(ctx)

class nanika_group(commands.Group, nanika_command):
    def command(self, **kwargs):
        kwargs.setdefault("cls", nanika_command)
        return super().command(**kwargs)

    def group(self, **kwargs):
        kwargs.setdefault("cls", self.__class__)
        return super().group(**kwargs)

def command(**kwargs):
    kwargs.setdefault("cls", nanika_command)
    return commands.command(**kwargs)

def group(**kwargs):
    kwargs.setdefault("cls", nanika_group)
    return command(**kwargs)
