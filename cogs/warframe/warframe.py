import asyncio
import calendar
import datetime
import json
import logging
import math
import pathlib

import aiohttp
import discord
from discord.ext import tasks
from discord.ext.commands import Cog, command, is_owner

import core
import utils
from utils import normalise_hms, ordinal

LOGGER = logging.getLogger(__name__)

INCARNON_GENESIS_ROTATIONS = [
    ["Braton", "Lato", "Skana", "Paris", "Kunai"],
    ["Boar", "Gammacor", "Angstrum", "Gorgon", "Anku"],
    ["Bo", "Latron", "Furis", "Furax", "Strun"],
    ["Lex", "Magistar", "Boltor", "Bronco", "Ceramic Dagger"],
    ["Torid", "Dual Toxocyst", "Dual Ichor", "Miter", "Atomos"],
    ["Ack & Brunt", "Soma", "Vasto", "Nami Solo", "Burston"],
    ["Zylok", "Sibear", "Dread", "Despair", "Hate"]
]
INCARNON_GENESIS_EPOCH = datetime.datetime(
    year=2023, month=12, day=18, hour=0, minute=0,
    tzinfo=datetime.UTC
)

EVERGREEN_OFFERINGS = [
    "Umbra Forma Blueprint",
    "50,000 Kuva",
    "Kitgun Riven Mod",
    "3x Forma",
    "Zaw Riven Mod",
    "30,000 Endo",
    "Rifle Riven Mod",
    "Shotgun Riven Mod",
]
EVERGREEN_EPOCH = datetime.datetime(
    year=2023, month=12, day=11, hour=0, minute=0,
    tzinfo=datetime.UTC
)

MIDNIGHT = datetime.time(hour=0, minute=0, tzinfo=datetime.UTC)

MISSION_TYPES = {
    "MT_ARENA":                 "Rathuum",
    "MT_ARMAGEDDON":            "Void Armageddon",
    "MT_ARTIFACT":              "Disruption",
    "MT_ASSAULT":               "Assault",
    "MT_ASSASSINATION":         "Assassination",
    "MT_CAPTURE":               "Capture",
    "MT_CORRUPTION":            "Void Flood",
    "MT_DEFAULT":               "Unknown",
    "MT_DEFENSE":               "Defense",
    "MT_ENDLESS_EXTERMINATION": "(Elite) Sanctuary Onslaught",
    "MT_EVACUATION":            "Defection",
    "MT_EXCAVATE":              "Excavation",
    "MT_EXTERMINATION":         "Exterminate",
    "MT_HIVE":                  "Hive Sabotage",
    "MT_INTEL":                 "Spy",
    "MT_LANDSCAPE":             "Landscape",
    "MT_MOBILE_DEFENSE":        "Mobile Defense",
    "MT_PURIFY":                "Infested Salvage",
    "MT_PVP":                   "Conclave",
    "MT_RACE":                  "Rush (Archwing)",
    "MT_RESCUE":                "Rescue",
    "MT_RETRIEVAL":	            "Hijack",
    "MT_SABOTAGE":              "Sabotage",
    "MT_SECTOR":                "Solar Rail Conflict",
    "MT_SURVIVAL":              "Survival",
    "MT_TERRITORY":             "Interception",
    "MT_VOID_CASCADE":          "Void Cascade",
}

RELICS = {
    "VoidT1": "Lith",
    "VoidT2": "Meso",
    "VoidT3": "Neo",
    "VoidT4": "Axi",
    "VoidT5": "Requiem",
}

me_rn = pathlib.Path(__file__)
SOLNODES = json.loads((me_rn.parent / "solnodes.json").read_bytes())

def _midnight_next_weekday(dt, /, weekday):
    dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    days = weekday - dt.weekday()
    if days <= 0:
        days += 7
    dt += datetime.timedelta(days=days)
    return dt

class Warframe(core.nanika_cog):
    def __init__(self, bot):
        self.bot = bot
        self._world_state = None
        self._request_lock = asyncio.Lock()

    async def cog_load(self):
        await super().cog_load()
        self.weekly_reset.start()

    async def cog_unload(self):
        await super().cog_unload()
        self.weekly_reset.cancel()

    def _state_needs_updating(self):
        state = self._world_state
        epoch_now = datetime.datetime.now(datetime.UTC).timestamp() * 1000.0
        return (
            not state
            or any(epoch_now >= int(mission["Expiry"]["$date"]["$numberLong"]) for mission in state["ActiveMissions"])
            or epoch_now >= int(state["VoidTraders"][0]["Expiry"]["$date"]["$numberLong"])
        )

    async def _request_world_state(self):
        async with self._request_lock:
            if self._state_needs_updating():
                LOGGER.info("requesting world state")
                async with self.session.get("https://content.warframe.com/dynamic/worldState.php") as r:
                    r.raise_for_status()
                    stream = await r.read()
                    self._world_state = json.loads(stream.decode("utf-8"))

            return self._world_state

    @command(aliases=["fissures"])
    async def voidfissures(self, ctx):
        """tell the current void fissures"""
        try:
            state = await self._request_world_state()
        except aiohttp.ClientResponseError:
            return await ctx.send("something went wrong trying to fetch the world state")

        missions = state["ActiveMissions"]

        pg = utils.BlankPaginator()

        for mission in sorted(missions, key=lambda m: int(m["Modifier"].removeprefix("VoidT"))):
            steel_path = mission.get("Hard", False)
            if steel_path:
                continue

            relic = RELICS[mission["Modifier"]]
            node_type = MISSION_TYPES.get(mission["MissionType"], "unknown mission type.")
            fmt = f"`{relic}` {node_type}"

            #if node := SOLNODES.get(mission["Node"]):
            #    fmt = f"{fmt} ({node['node']}, {node['planet']})"

            expiry = int(mission["Expiry"]["$date"]["$numberLong"])
            fmt = f"{fmt} (gone {f'<t:{int(expiry / 1000.0)}:R>'})"

            pg.add_line(fmt)

        await ctx.chain(pg.pages, initial=None)

    @command(aliases=["baro"])
    async def whenbaro(self, ctx):
        """tell baro ki'teers next visit"""
        try:
            state = await self._request_world_state()
        except aiohttp.ClientResponseError:
            return await ctx.send(
                "something went wrong trying to fetch the world state"
                "\njust check this lol <https://warframe.fandom.com/wiki/Baro_Ki'Teer>"
            )

        trader = state["VoidTraders"][0]
        activation = int(trader["Activation"]["$date"]["$numberLong"])
        expiry = int(trader["Expiry"]["$date"]["$numberLong"])

        now = datetime.datetime.now(datetime.UTC).timestamp() * 1000.0

        fmt = f"<t:{int(expiry // 1000)}:R>"
        if now > activation:
            m = f"kitty's here! (gone {fmt})"
        else:
            m = f"kitty's coming {fmt}"

        await ctx.send(m)

    @tasks.loop(time=MIDNIGHT)
    async def weekly_reset(self, *, force=False):
        now = datetime.datetime.now(datetime.UTC).replace(second=0, microsecond=0)
        if not force:
            if now.weekday() != calendar.MONDAY:
                return

        reset = _midnight_next_weekday(now, calendar.MONDAY)

        aws = [weekly(self, now, reset) for weekly in self.weeklies]
        gathered = await asyncio.gather(*aws, return_exceptions=True)
        for item in gathered:
            if item is not None: # exception
                LOGGER.error("weekly task error", exc_info=item)

    weeklies = []

    @weeklies.append
    async def iron_wake(self, now, reset):
        await self.bot.something.send(f"palladino got new stock (buy the **kuva**!) (new offerings {reset:R})")

    @weeklies.append
    async def archimedean_supplies(self, now, reset):
        await self.bot.something.send(f"yonta got more kuva (expires {reset:R})")

    @weeklies.append
    async def evergreen_offerings(self, now, reset):
        elapsed = now - EVERGREEN_EPOCH
        weeks = math.floor(elapsed / datetime.timedelta(days=7))
        offering = EVERGREEN_OFFERINGS[weeks % len(EVERGREEN_OFFERINGS)]
        await self.bot.something.send(f"teshin got new offering: {offering} (new offering {reset:R})")

    @command()
    async def teshin(self, ctx):
        """show the current evergreen offering"""
        now = ctx.message.created_at
        elapsed = now - EVERGREEN_EPOCH
        weeks = math.floor(elapsed / datetime.timedelta(days=7))
        offering = EVERGREEN_OFFERINGS[weeks % len(EVERGREEN_OFFERINGS)]
        reset = _midnight_next_weekday(now, calendar.MONDAY)
        await ctx.send(f"{offering} (gone {reset:R})")

    @command()
    async def spcircuit(self, ctx):
        """tells u what incarnon genesis weapons are in rotation for steel path circuit"""
        now = ctx.message.created_at
        elapsed = now - INCARNON_GENESIS_EPOCH
        weeks = math.floor(elapsed / datetime.timedelta(days=7))
        rotation = INCARNON_GENESIS_ROTATIONS[weeks % len(INCARNON_GENESIS_ROTATIONS)]

        until = now.replace(hour=0, minute=0, second=0, microsecond=0)
        days = calendar.MONDAY - until.weekday()
        if days <= 0:
            days += 7
        until += datetime.timedelta(days=days)

        wiki_url = "https://warframe.fandom.com/wiki/The_Circuit#The_Steel_Path_Circuit"
        await ctx.send(
            f"{', '.join(w.lower() for w in rotation)}"
            f"\n[next rotation {until:R}]({wiki_url})",
            suppress_embeds=True
        )

    @command()
    async def spiral(self, ctx):
        """tell the current duruvi spiral mood"""
        moods = ["sorrow", "fear", "joy", "anger", "envy"]
        epoch = 1703808000 # sorrow epoch
        duration = 1.0 * 60.0 * 60.0 * 2
        now = ctx.message.created_at.timestamp()
        elapsed = (now - epoch) % (duration * len(moods))
        index = int(elapsed // duration)
        mood = moods[index]
        next_mood = moods[(index + 1) % len(moods)]
        remaining = ((index + 1) * duration) - elapsed
        await ctx.send(f"{mood}\n{next_mood} in {normalise_hms(remaining)}")

    @command()
    async def cetus(self, ctx):
        """tells u how much time until night in plains of eidolon.
        tbh i calculate this using epoch and some math and its not that accurate
        and i have to keep updating the epoch myself.

        unlike what the wiki and update notes mentions, days and nights aren't actually
        100 minutes and 50 minutes long respectively. the total duration of day + night
        is actually a floating point between 149 and 150, and the night length is 1/3 of that value.
        this is why all the night clocks differ so much from each other, because it is up
        to the author to decide how much precision they want to use to calculate.

        i tried to keep the estimated time faithful to what the game displays when you
        hover over cetus, but i dont wanna monitor this value so it may become
        outdated over time unless i update the epochs.

        im unsure why warframe's servers doesn't use 150 exactly..
        """

        # technically i can change this to use accurate world state times now but i dont wanna

        ACTIVATION = 1703803661650
        EXPIRY = 1703812660524
        delta = EXPIRY - ACTIVATION
        day_duration = delta * 0.66666
        night_duration = delta - day_duration
        now = ctx.message.created_at.timestamp() * 1000.0
        cycles, elapsed = divmod(now - ACTIVATION, delta)
        timeofdays = ["day", "night"]
        nighttime = elapsed > day_duration
        end = day_duration
        if nighttime:
            end += night_duration
        remaining = (end - elapsed) / 1000.0
        rep = normalise_hms(remaining)
        wiki_url = "https://warframe.fandom.com/wiki/World_State#Timers"
        await ctx.send(f"{ordinal(cycles + 1)} {timeofdays[nighttime]}. [{timeofdays[not nighttime]} in {rep}](<{wiki_url}>)", suppress_embeds=True)
        # revisit? "remind me 15/10/5 minutes before night" button.

    @command()
    @is_owner()
    async def test_warframe_weekly(self, ctx):
        """test the warframe weekly task callback"""
        await self.weekly_reset(force=True)
