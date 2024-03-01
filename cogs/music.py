import asyncio
import datetime
import logging
from typing import Literal

import discord
import wavelink
from discord import ui
from discord.ext import commands

import core
import utils
from core import navi
from utils import VS15, VS16, ConfirmationPrompt

LOGGER = logging.getLogger(__name__)

async def setup(bot):
    await bot.add_cog(Music(bot))


class VoiceError(commands.CommandError):
    def __init__(self, m=None, *, with_helps=False):
        super().__init__(m or "something went wrong...")
        self.with_helps = with_helps


class AudioPlayerDropdown(ui.Select):
    def __init__(self, tracks: list[wavelink.Playable]):
        super().__init__()
        self.tracks = tracks
        for index, track in enumerate(tracks):
            desc = f"[{track.source}]"
            if track.author:
                desc = utils.shorten(f"{desc} by {track.author}", width=45)
            self.add_option(
                label=utils.shorten(track.title, width=45),
                description=desc,
                value=str(index),
                #default=index == 0
            )

    async def callback(self, interaction):
        self.view.stop()
        self.track = self.tracks[int(self.values[0])]
        await interaction.response.defer()
        await interaction.delete_original_response()


class AudioPlayerModal(ui.Modal, title="new track"):
    query = ui.TextInput(
        label="name or link",
        placeholder="death grips x hotline miami mashup..."
    )

    def __init__(self, mother):
        super().__init__()
        self.mother = mother

    async def on_submit(self, interaction):
        await self.mother.invoke_audio_command("play", interaction=interaction, kwargs={"query": self.query.value})

class AudioPlayerView(utils.UsefulView, utils.ContextView):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @ui.button(
        label=f"\N{BLACK RIGHT-POINTING TRIANGLE}{VS15} play",
        style=discord.ButtonStyle.blurple,
        row=0,
        custom_id="audio:play"
    )
    async def play(self, interaction, button):
        await interaction.response.send_modal(AudioPlayerModal(self))

    async def invoke_audio_command(self, command, *, interaction=None, args=(), kwargs={}):
        cmd = self.cog.bot.get_command(command)
        # little cringe
        band = interaction or self.interaction
        band.command # first access
        band._cs_command = cmd # shadow
        ctx = await core.nanika_ctx.from_interaction(band)
        # ctx.author is the bot here btw due to ctx.message
        ctx.author = band.user
        if args or kwargs:
            ctx.args = (self.cog, ctx, *args)
            ctx.kwargs = kwargs
            ctx.dont_parse()
        # now invoke command on the bot (dont forget check-onces nanika)
        await self.cog.bot.invoke(ctx)
        if not ctx.interaction.response.is_done():
            # the original command is "silent"
            # app commands need a message response so we need to do something minimal here
            await ctx.send("\N{JOYSTICK}", ephemeral=True)

    @ui.button(
        label=f"\N{CLOCKWISE OPEN CIRCLE ARROW}{VS15} loop",
        style=discord.ButtonStyle.grey,
        row=0,
        custom_id="audio:loop"
    )
    async def loop(self, interaction, button):
        await self.invoke_audio_command("loop")

    @ui.button(
        label=f"\N{RIGHTWARDS ARROW WITH HOOK}{VS15} skip",
        style=discord.ButtonStyle.grey,
        row=0,
        custom_id="audio:skip"
    )
    async def skip(self, interaction, button):
        await self.invoke_audio_command("skip")

    @ui.button(
        label=f"\N{BLACK SQUARE FOR STOP}{VS15} disconnect",
        style=discord.ButtonStyle.red,
        row=0,
        custom_id="audio:disconnect"
    )
    async def disconnect(self, interaction, button):
        await self.invoke_audio_command("disconnect")

    @ui.button(
        label=f"\N{TWISTED RIGHTWARDS ARROWS}{VS15} shuffle queue",
        style=discord.ButtonStyle.blurple,
        row=1,
        custom_id="audio:shuffle"
    )
    async def shuffle_queue(self, interaction, button):
        await self.invoke_audio_command("shuffle")

    @ui.button(
        label=f"\N{DOWNWARDS ARROW}{VS15} expand queue",
        style=discord.ButtonStyle.blurple,
        row=1,
        custom_id="audio:queue"
    )
    async def expand_queue(self, interaction, button):
        await self.invoke_audio_command("queue")

NOT_CONNECTED_MSG = "im not connected to voice"

def requires_voice(*, and_track=False):
    async def predicate(ctx):
        player = ctx.guild.voice_client
        if not player or not player.channel:
            raise VoiceError(NOT_CONNECTED_MSG)
        if and_track and not player.current:
            raise VoiceError("nothing is playing atm")
        return True
    return commands.check(predicate)

class nanika_bot_music_player(wavelink.Player):
    def cycle_queue_loop(self):
        rotation = [
            wavelink.QueueMode.loop,
            wavelink.QueueMode.loop_all,
            wavelink.QueueMode.normal
        ]
        index = rotation.index(self.queue.mode)
        self.queue.mode = rotation[(index + 1) % len(rotation)]


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.view = AudioPlayerView(self)
        bot.add_view(self.view)

    def cog_unload(self):
        self.view.stop()

    async def cog_check(self, ctx):
        return await commands.guild_only().predicate(ctx)

    async def cog_command_error(self, ctx, error):
        if isinstance(error, VoiceError):
            view = (
                utils.CommandHelpView(ctx)
                if error.with_helps
                else discord.utils.MISSING
            )
            await ctx.send(str(error), ephemeral=True, view=view,
                           delete_after=14.0 if error.with_helps else 5.0)

    @core.command()
    async def play(self, ctx, *, query):
        """play a track from youtube/bandcamp/soundcloud/w/e"""
        async with ctx.typing(ephemeral=True):
            found: wavelink.Search = await wavelink.Playable.search(query)

        if isinstance(found, wavelink.Playlist):
            playlist = found
            tracks = playlist.tracks

            if not tracks:
                # empty?
                return await ctx.send("empty playlist", ephemeral=True)

            prompt = ConfirmationPrompt()
            await ctx.send(
                f"add {len(playlist)} tracks from this playlist to the queue?",
                view=prompt,
                ephemeral=True
            )
            await prompt.wait()
            if not prompt.result:
                return

            await self.play_tracks(ctx, tracks)
            await ctx.send(f"queued {len(tracks)} tracks from {playlist.name}")
            return

        if not found:
            return await ctx.send("no tracks found", ephemeral=True)

        if len(found) == 1:
            track = found[0]
        else:
            view = ui.View(timeout=2 * 60.0)
            dropdown = AudioPlayerDropdown(found[:25])
            view.add_item(dropdown)
            await ctx.send(view=view, ephemeral=True)
            timed_out = await view.wait()
            if timed_out:
                return

            track = dropdown.track

        await self.play_tracks(ctx, [track])
        await ctx.plain(f"queued {track.title}")

    @core.command()
    @requires_voice()
    async def loop(self, ctx, mode: Literal[".", "*", "-"] = None):
        """toggle looping.
        you can type a specifier afterwards that lets you switch to a specific loop mode.
        for example:
          wwloop . >>> loops current track
          wwloop * >>> loops whole queue
          wwloop - >>> dont loop
        """
        player = ctx.guild.voice_client
        if mode is not None:
            modes = {
                ".": wavelink.QueueMode.loop,
                "*": wavelink.QueueMode.loop_all,
                "-": wavelink.QueueMode.normal,
            }
            player.queue.mode = modes[mode]
            await ctx.react("\N{JOYSTICK}" + VS16)
        else:
            player.cycle_queue_loop()
            # add a little extra info since ppl wont always know the rotation
            messages = {
                wavelink.QueueMode.loop:     "now looping current track",
                wavelink.QueueMode.loop_all: "now looping the queue",
                wavelink.QueueMode.normal:   "not looping"
            }
            await ctx.send(messages[player.queue.mode], delete_after=5.0)

    @core.command()
    @requires_voice(and_track=True)
    async def skip(self, ctx):
        """skip the current song"""
        player = ctx.guild.voice_client
        await player.skip(force=True)
        await ctx.react("\N{JOYSTICK}" + VS16)

    @core.command(name="jump", aliases=["seek"])
    @requires_voice(and_track=True)
    async def seek(self, ctx, timestamp):
        """jump to a timestamp in the current track.
        valid inputs are:
        24:23 (minutes, seconds)
        4:24:23 (hours, minutes, seconds)
        or a single number (eg. 120) representing the seconds into the track
        """
        player = ctx.guild.voice_client
        split = [s for s in timestamp.split(":") if s]
        from math import pow
        for n in range(3):
            offset = 3 - n
            if len(split) != offset:
                continue
            try:
                seconds = sum(
                    int(thing) * pow(60.0, offset - index - 1)
                    for index, thing in enumerate(split)
                )
                break
            except ValueError:
                continue
        else:
            await ctx.send("dont understand that timestamp")
            return

        duration = player.current.length
        milliseconds = min(max(seconds * 1000.0, 0.0), duration)
        if milliseconds >= (duration - 1000.0):
            await player.skip(force=True)
        else:
            await player.seek(int(milliseconds))

        await ctx.react("\N{JOYSTICK}" + VS16)

    @core.command(aliases=["np"])
    @requires_voice(and_track=True)
    async def nowplaying(self, ctx):
        """show current track progress"""
        player: wavelink.Player = ctx.guild.voice_client
        track = player.current
        position = player.position
        duration = track.length

        def delta_time(ms):
            minutes, seconds = divmod(ms / 1000.0, 60.0)
            hours, minutes = divmod(minutes, 60.0)
            seconds, minutes, hours = (
                (int(seconds)), int(minutes), int(hours)
            )
            if hours != 0:
                return f"{hours}:{minutes:02}:{seconds:02}"
            return f"{minutes}:{seconds:02}"

        gap, mark = ("─", "●")
        width = 8
        index = int((position / duration) * width)
        progress_bar = (gap * (index - 1)) + mark + ((width - index) * gap)

        hyperlink = f"[{discord.utils.escape_markdown(track.title)}]({track.uri})"
        await ctx.plain(
            f"{hyperlink}\n"
            f"{delta_time(position)} {progress_bar} {delta_time(duration)}"
        )

    @core.command()
    @requires_voice()
    async def shuffle(self, ctx):
        """shuffle the queue"""
        player = ctx.guild.voice_client
        player.queue.shuffle()
        await ctx.react("\N{JOYSTICK}" + VS16)

    @core.command()
    @requires_voice()
    async def disconnect(self, ctx):
        """make the bot leave the voice channel. resets the queue."""
        player = ctx.guild.voice_client
        await player.disconnect()
        await ctx.react("\N{JOYSTICK}" + VS16)

    class TrackPageSource(navi.ListPageSource):
        def __init__(self, tracks):
            super().__init__(tracks, per_page=12)

        def format_page(self, navi, tracks):
            offset = self.index * self.per_page
            fmt = "\n".join(
                f"[__`{index}`__]({track.uri}): {utils.escape(track.title, width=45)}"
                for index, track in enumerate(tracks, start=offset + 1)
            )
            embed = discord.Embed(title="queue", description=fmt, colour=0x0723DB)
            embed.set_footer(text=f"page {self.index + 1}/{self.max_pages}")
            return embed

    @core.command()
    @requires_voice()
    async def queue(self, ctx):
        """show what songs are up next."""
        player = ctx.guild.voice_client
        if not len(player.queue):
            raise VoiceError("queue is empty")

        tracks = [t for t in player.queue]
        navigator = navi.Navi(self.TrackPageSource(tracks))
        await ctx.alway_ephemeral().paginate(navigator)

    @core.command()
    @requires_voice(and_track=True)
    async def resume(self, ctx):
        """resume music"""
        player = ctx.guild.voice_client
        if player.paused:
            await player.pause(False)
        await ctx.react("\N{JOYSTICK}" + VS16)

    @core.command()
    @requires_voice(and_track=True)
    async def pause(self, ctx):
        """pause the player"""
        player = ctx.guild.voice_client
        if not player.paused:
            await player.pause(True)
        await ctx.react("\N{JOYSTICK}" + VS16)

    @core.command()
    @commands.is_owner()
    async def console(self, ctx):
        view = AudioPlayerView(self)
        view.stop()
        await ctx.send("sound console", view=view)

    async def play_tracks(self, ctx, tracks):
        player: wavelink.Player
        player = ctx.guild.voice_client
        if not player or not player.channel:
            state = ctx.author.voice
            if not state or not state.channel:
                raise VoiceError("join a voice channel")
            player = await state.channel.connect(cls=nanika_bot_music_player)

        # its always a good idea to push to the queue
        # so looping behaviour works as expected
        for track in tracks:
            player.queue.put(track)

        if not player.current:
            # play the next song
            await player.play(player.queue.get())
        else:
            # if we're looping current track, then skip it
            if player.queue.mode is wavelink.QueueMode.loop:
                await player.skip(force=True)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload):
        player = payload.player
        if not player or not player.connected:
            return

        try:
            track = player.queue.get()
        except wavelink.QueueEmpty:
            pass
        else:
            await player.play(track)
