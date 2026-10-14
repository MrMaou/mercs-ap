# Mercenaries Archipelago

This is an [Archipelago Multiworld Randomizer](https://archipelago.gg) for
*Mercenaries: Playground of Destruction*. It plays on the PS2 version in PCSX2,
or on the Xbox version through
[Mercenaries Recompiled](https://github.com/KraftMacAndChee/Mercenaries-Recompiled)
(see [Playing on Mercenaries Recompiled](#playing-on-mercenaries-recompiled-xbox-native-port)).

This is [MrMaou/mercs-ap](https://github.com/MrMaou/mercs-ap), a fork of
[ToxicFrog/mercs-ap](https://github.com/ToxicFrog/mercs-ap), which is no longer
maintained.

## Features

### Checks

Completing missions and verifying members of the Deck of 52 will count as AP
checks. Collecting bounties will also produce checks, with the number of
bounties needed per check configurable in the yaml. The bounty totals are 110
blueprints, 110 national treasures, 55 listening posts and 20 monuments.

In all cases, the vanilla monetary and faction rewards are left intact; the AP
check replaces the shop unlock or Ace intel you would normally get.

Missable checks (most non-Ace cards and missions) will be auto-released at the
end of their corresponding chapter, so rushing for the Ace early once you have
enough intel and firepower is a viable strategy and will not lock you out of
chapter-specific checks.

### Items

#### Progression

**Ace intel.** This serves the same purpose as intel in the vanilla game.
Depending on your yaml settings, it can use the vanilla intel amounts or a fixed
number of "intel tokens" per ace, and it can be suited or progressive.

**Merchant of Menace unlocks.** These are the only way to unlock new things in the store.

#### Filler

**Cash bonuses.** These range from $5k to $500k.

**Faction mood adjustments.** The more of these you have for a faction, the higher their minimum mood towards you is. There are diminishing returns as you collect more.

**Free samples.** These apply to broad categories (e.g. "free airstrike") and will pick an appropriate random item from that category when issued to you. If you don't have at least three items in that category, they'll wait until you do. These samples are usually lost when you do anything involving a loading screen, so use it or lose it.

### Hints

Completing a mission that gives in-game hints about the location of a Number
will also give an AP hint for what item that Number is carrying.

Capturing a Card alive will give you a hint for a random progression item,
either someone else's in your world, or one of yours in someone else's world.


## Setup

### Prerequisites

- [Archipelago](https://archipelago.gg)
- The [apworld](./release/mercenaries.apworld)
- A **US** copy of "Mercenaries: Playground of Destruction", with game ID `SLUS-20932`
- [PCSX2](https://pcsx2.net/) to play it with
  - Real hardware not supported, sorry

Note that this **is** compatible with iso and memory patches like the subtitles
patch, widescreen, texture replacement, etc, as long as the base game is the
US version.

### First-time setup

Get PCSX2 installed and running and make sure you can actually run Mercenaries
in it. Once you have that, change the following settings:
- `Tools -> Show Advanced Settings` **on**
- `System -> Settings -> Advanced -> PINE Settings -> Enable` **on**
- `System -> Settings -> Advanced -> PINE Settings -> Slot` **28011** (should be the default)

If your computer is sufficiently powerful, you may also want to open up
`Settings -> Game Properties -> Emulation` and set the `EE Cycle Rate` to 180%
or 300%; this will mess up the inter-chapter cutscenes, but allow the game to
maintain a steady 30fps during gameplay.

### Per-game setup

Configuration and generation works basically the same as any other AP game; see
the generated YAML for options. To join, just click `Mercenaries Client` in the
AP launcher and it should automatically connect to PCSX2.


## Playing on Mercenaries Recompiled (Xbox native port)

This fork can also connect to
[Mercenaries Recompiled](https://github.com/KraftMacAndChee/Mercenaries-Recompiled),
the native Windows port of the **Xbox** version. The AP world, items, locations
and YAML options are the same; only the game connection differs.

It needs the matching recomp fork,
[MrMaou/Mercenaries-Recompiled](https://github.com/MrMaou/Mercenaries-Recompiled),
which adds plugin interface 2 and the **Archipelago** plugin. The original
recomp releases do not have them.

### Setup (in-game client)

1. Build the [recomp fork](https://github.com/MrMaou/Mercenaries-Recompiled) (see its README) from your USA retail **Xbox** ISO.
2. Build the plugin from `ports/mercenaries/plugins/archipelago` (see its
   README) and copy its output folder to `mods/Archipelago/` beside
   `Mercenaries Recompiled.exe`.
3. Enable **Archipelago** in the mod selector and choose **Launch Modded**.
   Turning on **Use separate saves** keeps AP saves apart from normal ones.
4. Start a new game, press **F7**, enter server, slot and password, and
   **Connect**.

The client runs inside the game: no Python or Archipelago install is needed to
play. Generate seeds with this repository's `.apworld` as usual. Items, hints
and chat show up as notices over the game; the F7 panel also has the message
log and a text box for chat and `!commands`.

### Saves

The in-game client links each save to one seed and slot, and keeps a record of
delivered cash and free samples inside the save itself (number keys in the
game's scribble memory, which the game writes into the save file).

- A new game is linked on the first sync; the panel says "Save linked".
- Loading an older save re-delivers exactly the cash and free samples that save
  is missing. Checks already sent stay sent.
- A save from another seed or slot is left alone: the client warns once and
  sends nothing until you load the right save or start a new game.

### Python client (optional)

`Mercenaries Client` from the AP launcher still works with the recomp, through
the plugin's local bridge on `localhost:28012`. Use it only while the in-game
client is disconnected; the bridge refuses changes while the in-game client is
active. Use `--game recomp` to skip PCSX2 detection, or `--recomp host:port` if
you changed the bridge port in `archipelago.ini`. The Python client does not use
the save record; do not alternate between the two clients on one save.

Both clients record delivered one-shot items under the same per-slot data
storage key, `mercs_sent_items_<team>_<slot>`. Older versions of this client
used the room-wide key `sent_items`; a seed started with an older client
receives its cash and free samples once more after updating.

### How it works

The PCSX2 backend patches Lua bytecode in emulated memory. The recomp backend
instead runs Lua source in the game's script VM (see
`mercenaries/client/recomp_runtime.py`); the in-game client embeds the same
runtime. Everything goes through the game's own scripts and scribble memory:

- **Cards and missions:** card states and current mission numbers from
  scribble memory.
- **Bounties:** when you collect or destroy a bounty, the game writes a
  scribble key named after its actor (`bty_blueprint30`, `swlistenpost18`,
  `monument_sw9`, ...). The runtime counts these per type over both maps, so
  the counts survive reloads and do not depend on what is loaded nearby.
- **Items:** intel, faction floors, money, messages, free samples and Merchant
  of Menace unlocks use the game's script functions.

The game's script VM has only Lua's base and table libraries (no `string`, no
`math`) and a small heap, so string work is done by the client and the runtime
keeps its garbage low.

The only fixed memory addresses left are the ones that say whether it is safe to
run Lua at all: the script VM pointer, a scene transition flag, two gameplay
state words and the map hash. They are static globals of the one retail XBE the
recomp supports.

### Status

Confirmed in game: runtime install, save linking, cash delivery, Merchant of
Menace unlocks, and bounty counting for blueprints, listening posts and
monuments. Not yet seen in game:

- **Ace missions.** The client only acts on the South and North world maps, so
  it waits during Ace missions (and anything else on a different map) and
  catches up afterwards. Adding the Ace mission map hashes would remove the
  wait.
- **Treasures** are counted the same way as the other bounties but have not
  been checked in game yet.
- Whether `Shop_UnlockItem` survives save/load without the client re-applying
  it. The runtime unlocks each item once per script VM and again after a load,
  so this only matters for the Python client while it is not running.

### Exploring the game

`python tools/recomp_repl.py` opens a console to the running game (disconnect
the in-game client first). Type Lua to run it in the game
(`=Player_GetMoney()` prints a value), or use:

- `:globals TEXT` to list script globals whose names contain TEXT,
- `:consts NAME` to list the constants of a script function (the globals it
  calls, its strings and numbers), read from the game's memory,
- `:shop`, `:poll` and `:install` for the AP runtime,
- `:read`, `:u32` and `:scan` for raw memory (`:scan step 1` and
  `:scan idle SECONDS` help rule out timers).

The full command list is at the top of the script.

## Known Issues and Limitations

Card verifications may not be registered by AP until the next time you open your
PDA in-game.

Messages and some items can only be delivered to Mercenaries at certain points
in execution, which means there may be a significant delay between getting
something in AP and it showing up in-game. This is particularly the case with
money, intel, and faction reputation adjustments. Wandering around the game and
doing things to force it to load/unload areas and NPCs tends to speed up this
process.

Combat logic only takes into account how many things you have unlocked, not what
things, e.g. it will not lock a mission where you fight helicopters behind
having access to anti-air support. Missions generally give you everything you
need on-site if you look around, so this is not a problem in practice.

Windows and OSX should work, but are completely untested.

## Future Work

Some of these are speculative, and depend on reverse engineering I haven't done
yet to figure out if they're viable; this is a wishlist, not a roadmap.

- New checks:
  - Mission bonus objectives
  - Challenges
  - Vehicles driven/destroyed catalogue entries
- New items:
  - Character skins
  - Health/ammo/grenade capacity upgrades
  - Health/ammo/grenade refills
- Improved logic:
  - Better mission logic, e.g. missions that want anti-air depending on having
    an AA vehicle, supply drop, or airstrike unlocked
