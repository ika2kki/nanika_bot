import discord
from discord import ui
from discord.utils import maybe_coroutine as maybe_coro

from utils import VS15

# little bit of code that helpful to let me use
# buttons for paginator in the style of danny's original ext.menus

# some differences from the original design is based on the relativly recent bikeshedding

__all__ = ("ListPageSource", "blank", "Navi",)

class ListPageSource:
    def __init__(self, items, per_page=None):
        self.items = items
        self._variable_per_page = per_page is not None
        per = per_page if self._variable_per_page else 1
        self.per_page = per
        self.max_pages = -(len(items) // -per)
        self.index = 0

    def jump_first(self, navi):
        self.index = 0
        return self._slice()

    def previous(self, navi):
        self.index = max(self.index - 1, 0)
        return self._slice()

    def peek(self, navi):
        return self._slice()

    def seek(self, navi, page):
        self.index = min(max(page, 0), self.max_pages - 1)
        return self._slice()

    def next(self, navi):
        self.index = min(self.index + 1, self.max_pages - 1)
        return self._slice()

    def jump_last(self, navi):
        self.index = self.max_pages - 1
        return self._slice()

    def _slice(self):
        offset = self.index * self.per_page
        sl = self.items[offset:offset + self.per_page]
        return sl if self._variable_per_page else sl[0]

    def format_page(self, navi, thing):
        raise NotImplementedError

class blank(ListPageSource):
    """source that do nothing and just return the item as-is"""
    def format_page(self, navi, page):
        return page

class PageNumberModal(ui.Modal):
    def __init__(self, navi):
        super().__init__(title="jump to page", timeout=25.0)
        self.navi = navi
        self.page = page = ui.TextInput(
            label="page number",
            placeholder=f"1 to {navi.source.max_pages}"
        )
        self.add_item(page)

    async def on_submit(self, interaction):
        pageno = self.page.value
        if not pageno.isdigit():
            return await interaction.response.defer()
        navi = self.navi
        item = await maybe_coro(navi.source.seek, navi, int(pageno) - 1)
        prepped = await navi.prepare(item)
        navi.update_items()
        await interaction.response.edit_message(**prepped)

class Navi(ui.View):
    def __init_subclass__(cls, *, navi_row=None):
        super().__init_subclass__()
        if navi_row is not None:
            for index, fn in enumerate(cls.__view_children_items__):
                if index % 5 == 0:
                    navi_row += 1

                copy = fn.__discord_ui_model_kwargs__.copy()
                copy["row"] = navi_row
                fn.__discord_ui_model_kwargs__ = copy

    def __init__(self, source):
        super().__init__(timeout=4 * 60.0)
        self.source = source
        if self.source.max_pages == 1:
            self.clear_items()
            self.stop()
        self.owner_id = None

    async def interaction_check(self, interaction):
        if self.owner_id:
            return interaction.user.id == self.owner_id
        else:
            return True

    async def prepare(self, page):
        fmt = await maybe_coro(self.source.format_page, self, page)
        prepped = {"view": self}
        if isinstance(fmt, str):
            prepped["content"] = fmt
        elif isinstance(fmt, discord.Embed):
            prepped["embed"] = fmt
        elif isinstance(fmt, dict):
            prepped |= fmt
        return prepped

    @ui.button(label="1 \N{BLACK LEFT-POINTING DOUBLE TRIANGLE}" + VS15)
    async def jump_first(self, interaction, button):
        item = await maybe_coro(self.source.jump_first, self)
        prepped = await self.prepare(item)
        self.update_items()
        await interaction.response.edit_message(**prepped)

    @ui.button(label="\N{BLACK LEFT-POINTING TRIANGLE}" + VS15, style=discord.ButtonStyle.green)
    async def previous(self, interaction, button):
        item = await maybe_coro(self.source.previous, self)
        prepped = await self.prepare(item)
        self.update_items()
        await interaction.response.edit_message(**prepped)

    @ui.button(style=discord.ButtonStyle.blurple, disabled=True)
    async def page_number(self, interaction, button): ...

    @ui.button(label="\N{BLACK RIGHT-POINTING TRIANGLE}" + VS15, style=discord.ButtonStyle.green)
    async def next(self, interaction, button):
        item = await maybe_coro(self.source.next, self)
        prepped = await self.prepare(item)
        self.update_items()
        await interaction.response.edit_message(**prepped)

    @ui.button()
    async def jump_last(self, interaction, button):
        item = await maybe_coro(self.source.jump_last, self)
        prepped = await self.prepare(item)
        self.update_items()
        await interaction.response.edit_message(**prepped)

    @ui.button(label=f"\N{RIGHTWARDS ARROW WITH HOOK}{VS15} jump to page", style=discord.ButtonStyle.blurple)
    async def jump_to_page(self, interaction, button):
        await interaction.response.send_modal(PageNumberModal(self))

    @ui.button(label=f"\N{EJECT SYMBOL}{VS15} close pages", style=discord.ButtonStyle.red)
    async def close(self, interaction, button):
        await interaction.response.defer()
        await interaction.delete_original_response()
        self.stop()

    def update_items(self):
        self.jump_first.disabled = self.previous.disabled = self.source.index == 0
        self.page_number.label = str(self.source.index + 1)
        self.jump_last.disabled = self.next.disabled = self.source.index == (self.source.max_pages - 1)
        self.jump_last.label = f"\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE}{VS15} {self.source.max_pages}"
