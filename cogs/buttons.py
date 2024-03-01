import logging

import discord
from discord import ui
from discord.ext import commands

import utils

LOGGER = logging.getLogger(__name__)

async def setup(bot):
    await bot.add_cog(Buttons(bot))

class RoleButton(
    ui.DynamicItem[ui.Button],
    template=r"buttonroles:(?P<view_id>[0-9]+):(?P<role_id>[0-9]+)"
):
    def __init__(self, *, view_id, role_id, label):
        super().__init__(
            ui.Button(
                label=label,
                custom_id=f"buttonroles:{view_id}:{role_id}",
                style=discord.ButtonStyle.blurple
            )
        )
        self.view_id = view_id
        self.role_id = role_id

    @classmethod
    async def from_custom_id(cls, interaction, button, match):
        return cls(
            view_id=int(match.group("view_id")),
            role_id=int(match.group("role_id")),
            label="" # not actually used
        )

    async def callback(self, interaction):
        bot = interaction.client

        query = """
            SELECT views.*, array_agg(button_roles.role_id) AS buttons
            FROM button_views views
            LEFT JOIN button_roles ON button_roles.view_id=views.id
            WHERE views.id=$1
            GROUP BY views.id
        """
        record = await bot.pgpool.fetchrow(query, self.view_id)
        if not record:
            # it was deleted; disable buttons as-is
            view = ui.View.from_message(interaction.message)
            for child in view.children:
                child.disabled = True
            await interaction.response.edit_message(view=view)
            return

        guild = interaction.guild
        await interaction.response.edit_message(view=RoleView(guild=guild, data=record))

        if self.role_id not in record["buttons"]:
            return await interaction.followup.send(
                "sorry, those buttons were pending an update"
                " and that role button was since removed",
                ephemeral=True
            )

        role = guild.get_role(self.role_id)
        if not role:
            return await interaction.followup.send("sorry that role was deleted...", ephemeral=True)

        if not role.is_assignable():
            return await interaction.followup.send(
                "sorry i unable to assign you this role - "
                "please tell a moderator to fix my permissioning",
                ephemeral=True
            )

        member = interaction.user
        if member.get_role(role.id):
            await member.remove_roles(role)
            msg = f"took away the `{role.name}` role from you"
        else:
            await member.add_roles(role)
            msg = f"added you to the `{role.name}` role"

        sent = await interaction.followup.send(msg, ephemeral=True, wait=True)
        await sent.delete(delay=5.0)


class RoleView(ui.View):
    def __init__(self, *, guild, data):
        super().__init__()
        for role_id in data["buttons"]:
            if role := guild.get_role(role_id):
                self.add_item(RoleButton(
                    view_id=data["id"],
                    role_id=role_id,
                    label=utils.shorten(role.name, width=45)
                ))
        self.stop()


class CreateViewRoleSelect(ui.RoleSelect):
    def __init__(self, parent):
        super().__init__(max_values=25)
        self.parent = parent

    async def callback(self, interaction):
        selected = self.values
        ctx = self.parent.ctx

        if ctx.author != ctx.guild.owner:
            restricted = [r for r in selected if r.managed or r.position >= ctx.author.top_role.position]
            if restricted:
                return await interaction.response.send_message(
                    "sorry you're not allowed to add the following roles:\n"
                    + "\n".join([f"- {utils.escape(r.name, width=45)}" for r in restricted])
                )

        await interaction.response.defer()

        async with ctx.bot.pgpool.acquire() as c, c.transaction():
            view_query = """
                INSERT INTO button_views (name, guild_id) VALUES ($1, $2)
                ON CONFLICT (name, guild_id)
                DO UPDATE SET name=button_views.name
                RETURNING id
            """
            view_id = await c.fetchval(view_query, self.parent.name_id, interaction.guild.id)

            in_guild = [r.id for r in interaction.guild.roles]
            in_table = await c.fetch("SELECT role_id FROM button_roles WHERE view_id=$1", view_id)
            new = [r for (r,) in in_table if r in in_guild] # validate existing roles

            added = 0
            popped = 0
            for role in selected:
                r = role.id
                if r in new:
                    popped += 1
                    new.remove(r)
                else:
                    added += 1
                    new.append(r)

            if len(new) > 25:
                return await interaction.followup.send("not enough space. discord only lets you put up to 25 buttons")

            await c.execute("DELETE FROM button_roles WHERE view_id=$1", view_id)
            await c.copy_records_to_table("button_roles",
                records=[(view_id, r) for r in new],
                columns=["view_id", "role_id"]
            )

        cmd = discord.utils.get(ctx.bot.app_cmds, name="buttonroles")
        mention = f"</buttonroles render:{cmd.id}>" if cmd else "`render`"

        extras = []
        if added:
            extras.append(f"{added} added")
        if popped:
            extras.append(f"{popped} removed")

        message = f"toggled {added+popped} roles"
        if extras:
            message = f"{message} ({', '.join(extras)})"
        message += f"\nyou can turn them into buttons using the {mention} command"

        unassignable = [r for r in selected if not r.is_assignable()]
        if unassignable:
            message += (
                "\n\nsome of the roles i cant manage yet, so make sure to fix my permissioning asap\n"
                + "\n".join([f"- {utils.escape(r.name, width=45)}" for r in unassignable])
            )
        await interaction.followup.send(message)


class EditorView(ui.View):
    def __init__(self, ctx, *, name_id):
        super().__init__(timeout=6 * 60.0)
        self.ctx = ctx
        self.name_id = name_id

    @ui.button(label="Toggle roles", style=discord.ButtonStyle.blurple)
    async def add_role(self, interaction, _):
        view = ui.View(timeout=60.0 * 2)
        view.interaction_check = self.interaction_check
        view.add_item(CreateViewRoleSelect(self))
        await interaction.response.send_message(view=view)

    async def interaction_check(self, interaction):
        return interaction.user == self.ctx.author


class Buttons(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_dynamic_items(RoleButton)

    def cog_unload(self):
        self.bot.remove_dynamic_items(RoleButton)

    @commands.group(hidden=True)
    @commands.has_guild_permissions(manage_roles=True)
    async def buttonroles(self, ctx):
        """self-assignable roles using buttons"""

    @buttonroles.command(name="create")
    async def buttonroles_create(self, ctx, *, name: str):
        """create a button role group.
        if you use this on an existing group, it lets you toggle the roles instead."""

        if not (1 <= len(name) <= 100):
            return await ctx.send("too short/long name")
        await ctx.send(name, view=EditorView(ctx, name_id=name))

    @buttonroles.command(name="delete")
    async def buttonroles_delete(self, ctx, *, name: str):
        """delete button roles by name. when they're next used, they will get disabled instead"""

        deleted = await self.bot.pgpool.fetchrow(
            "DELETE FROM button_views WHERE name=$1 AND guild_id=$2 RETURNING *",
            name, ctx.guild.id
        )
        if deleted:
            await ctx.send("deleted those button roles")
        else:
            await ctx.send("dont know any button roles using that name", ephemeral=True)

    @buttonroles.command(name="render")
    async def buttonroles_render(self, ctx, *, name: str):
        """send the buttons so they can be used by members."""

        query = """
            SELECT views.*, array_agg(button_roles.role_id) AS buttons
            FROM button_views views
            LEFT JOIN button_roles ON button_roles.view_id=views.id
            WHERE views.name=$1 AND views.guild_id=$2
            GROUP BY views.id
        """
        record = await self.bot.pgpool.fetchrow(query, name, ctx.guild.id)
        if not record:
            return await ctx.send("dont know any button roles with that name", ephemeral=True)

        await ctx.send(record["name"], view=RoleView(guild=ctx.guild, data=record))
