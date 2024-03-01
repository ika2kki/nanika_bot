import datetime
import random
import re
from typing import TypedDict
from urllib.parse import quote as urlquote

import aiohttp
import discord
from discord.ext import commands

import core
import utils
from core import navi
from core.config import configs


async def setup(bot):
    await bot.add_cog(Internet(bot))

BASE = "https://gelbooru.com/index.php?page=dapi&s=post&q=index&json=1"
BASE += "&api_key=" + configs["gelbooru"]["api_key"]
BASE += "&user_id=" + configs["gelbooru"]["user_id"]

class GelbooruPost(TypedDict):
    id: int
    created_at: str
    score: int
    width: int
    height: int
    md5: str
    directory: str
    image: str
    rating: str
    source: str
    change: int
    owner: str
    creator_id: int
    parent_id: int
    sample: int
    preview_height: int
    preview_width: int
    tags: str
    title: str
    has_notes: str
    has_comments: str
    file_url: str
    preview_url: str
    sample_url: str
    sample_height: int
    sample_width: int
    status: str
    post_locked: int
    has_children: str

class GelbooruPageSource(navi.ListPageSource):
    def format_page(self, navi, post: GelbooruPost):
        embed = discord.Embed(colour=0x006ffa)
        creator = post["creator_id"]
        embed.set_author(**
            {
                "name": "crossposted from danbooru",
                "icon_url": "https://cdn.discordapp.com/attachments/1191586641031217212/1191586674438852689/danbooru-logo.png",
                "url": "https://danbooru.donmai.us/"
            }
            if creator == 6498 # danbooru
            else {
                "name": post["owner"],
                "icon_url": f"https://gelbooru.com/user_avatars/avatar_{creator}.jpg",
                "url": f"https://gelbooru.com/index.php?page=account&s=profile&id={creator}"
            }
        )
        embed.set_image(url=post["file_url"])
        post_url = f"https://gelbooru.com/index.php?page=post&s=view&id={post['id']}"
        embed.add_field(name="Post", value=f"[Link]({post_url})")
        timestamp = datetime.datetime.strptime(post["created_at"], "%a %b %d %H:%M:%S %z %Y")
        embed.timestamp = timestamp.replace(tzinfo=datetime.UTC)
        return embed

class UrbanDictionaryDefinition(TypedDict):
    defid: int
    written_on: str
    permalink: str
    word: str
    definition: str
    author: str
    thumbs_up: int
    thumbs_down: int
    current_vote: str # ?-?

class UrbanDictionaryPageSource(navi.ListPageSource):
    COLOURS = [
        # these are the mug colours
        0xFFF200, # yellow
        0x53F7FF, # aquamarine
        0x2EFF3D, # harlequin
        0xF82418, # scarlet
        0x5AAD52, # grass
        0xFC66FB, # pink flamingo
        0x6D4343, # ferra
        0x542C5D, # eggplant
        0x000000, # black
        0x1b2936, # + banner colour
    ]
    def cleanup_field(self, field, *, limit=4096):
        def repl(match):
            word = match.group(1)
            url = (
                f"http://{word.replace(' ', '-')}.urbanup.com"
                if word.replace(" ", "").isalnum()
                else
                # fall back to longer-form url
                f"https://urbandictionary.com/define.php?term={urlquote(word)}"
            )
            return f"[{word}]({url})"
        field = re.sub(r"\[(.+?)\]", repl, field)
        return utils.shorten(field, width=limit) # not ideal since it can cut out a hyperlink but im lazy

    def format_page(self, navi, word: UrbanDictionaryDefinition):
        return (
            discord.Embed(
                title=word["word"],
                description=self.cleanup_field(word["definition"]),
                timestamp=datetime.datetime.fromisoformat(word["written_on"]),
                url=word["permalink"],
                colour=random.Random(word["defid"]).choice(self.COLOURS)
            )
                .set_footer(text="written")
                .set_author(
                    name=word["author"],
                    url=f"https://urbandictionary.com/author.php?author={urlquote(word['author'])}"
                )
                .add_field(name="Example", value=self.cleanup_field(word["example"], limit=1024), inline=False)
                .add_field(
                    name="Votes",
                    value=(
                        f"{word['thumbs_up']} \N{THUMBS UP SIGN}{utils.VS16}"
                        f" {word['thumbs_down']} \N{THUMBS DOWN SIGN}{utils.VS16}"
                    ),
                    inline=False
                )
            # waw
        )

class Internet(core.nanika_cog):
    async def cog_load(self):
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        await self.session.close()

    @commands.command(require_var_positional=True)
    @commands.is_nsfw()
    @commands.cooldown(3, 5.0)
    async def gel(self, ctx, *tags):
        """search gelbooru.
        tags come after, for example: wwgel wariza skirt
        to put multi word tag, use double quote: wwgel "blue sky"
        """
        url = BASE + "&limit=25"

        new_tags = []
        new_tags.append("sort:random")

        rated: bool = False
        for tag in tags:
            tag = tag.replace(" ", "_")
            if not tag.lstrip("-").startswith("sort:"):
                new_tags.append(tag)
                if not rated:
                    rated = tag.lstrip("-").startswith("rating:")

        if not rated:
            # default to a general rating
            new_tags.append("rating:general")

        async with self.session.get(url, params={"tags": " ".join(new_tags)}) as response:
            if response.status < 200 or response.status >= 300:
                return await ctx.send("downtime")
            data = await response.json()

        posts = data.get("post", [])
        if not posts:
            await ctx.send("there is nothing")
            return

        await ctx.paginate(navi.Navi(GelbooruPageSource(posts)))

    @gel.error
    async def gel_error(self, ctx, error):
        if isinstance(error, commands.NSFWChannelRequired):
            def predicate(c):
                return (
                    isinstance(c, discord.abc.Messageable)
                    and c.is_nsfw()
                    and (perms := c.permissions_for(ctx.author))
                        .read_messages
                        and perms.send_messages
                )

            msg = "this command dont work in sfw channels"

            visible_nsfw = [c for c in ctx.guild.channels if predicate(c)]
            weights = []
            for c in visible_nsfw:
                weight = 1
                if c.type is discord.ChannelType.text:
                    weight += 10
                if c.name in ("spam", "bots", "nsfw"):
                    weight += 20
                weights.append(weight)

            try:
                suggestion = random.choices(visible_nsfw, weights=weights, k=1)[0]
                msg += f".\ntry invoking it in an nsfw channel, like {suggestion.mention}"
            except IndexError:
                pass

            await ctx.send(msg)

    @commands.group(invoke_without_command=True)
    @commands.cooldown(8, 3.5)
    async def urban(self, ctx, *, word):
        """search urban dictionary"""
        url = getattr(ctx, "_urban_url", None)
        if url is None:
            url = f"https://api.urbandictionary.com/v0/define?term={urlquote(word)}"

        async with self.session.get(url) as response:
            if response.status < 200 or response.status >= 300:
                return await ctx.send("downtime")
            data = await response.json()

        definitions = sorted(
            data.get("list", []),
            key=lambda d: (d["thumbs_up"], d["thumbs_down"]),
            reverse=True
        )
        if not definitions:
            msg = "nothing found"
            if word != "random":
                async with self.session.get(
                    "https://api.urbandictionary.com/v0/autocomplete",
                    params={"term": word}
                ) as response:
                    if 200 <= response.status < 300:
                        autocomplete = await response.json()
                        if autocomplete:
                            msg += "\nurban dictionary suggestions:"
                            remaining = 2000 - len(msg)
                            for suggestion in autocomplete:
                                remaining -= len(suggestion) + 1
                                if remaining < 0:
                                    break
                                else:
                                    msg += "\n" + suggestion
            return await ctx.send(msg)
        await ctx.paginate(navi.Navi(UrbanDictionaryPageSource(definitions)))

    @urban.command(name="random")
    @commands.cooldown(8, 3.5)
    async def urban_random(self, ctx):
        """search up random definitions"""
        ctx._urban_url = "https://api.urbandictionary.com/v0/random"
        await self.urban(ctx, word="")

    @commands.command()
    async def httpcat(self, ctx, *, status_code: int):
        await ctx.send(f"\* https://http.cat/{status_code}"[:2000])
