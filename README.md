# Mercenaries Archipelago

This is an [Archipelago Multiworld Randomizer](https://archipelago.gg) for the
PS2 game *Mercenaries: Playground of Destruction*.

## Features

### Checks

Completing missions and verifying members of the Deck of 52 will count as AP
checks. Collecting bounties will also produce checks, with the number of
bounties needed per check configurable in the yaml.

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

It needs the matching recomp fork, which adds plugin interface 2 and the
**Archipelago** plugin. The original recomp releases do not have them.

### Setup (in-game client)

1. Build the recomp fork (see its README) from your USA retail **Xbox** ISO.
2. Build the plugin from `ports/mercenaries/plugins/archipelago` (see its
   README) and copy its output folder to `mods/Archipelago/` beside
   `Mercenaries Recompiled.exe`.
3. Enable **Archipelago** in the mod selector, choose **Launch Modded**, and
   start a new game; a save with vanilla shop unlocks keeps them.
4. Press **F7**, enter server, slot and password, and **Connect**.

The client runs inside the game: no Python or Archipelago install is needed to
play. Generate seeds with this repository's `.apworld` as usual.

### Python client (optional)

`Mercenaries Client` from the AP launcher still works with the recomp, through
the plugin's local bridge on `localhost:28012`. Use it only while the in-game
client is disconnected; the bridge refuses changes while the in-game client is
active. Use `--game recomp` to skip PCSX2 detection, or `--recomp host:port` if
you changed the bridge port in `archipelago.ini`.

Both clients record delivered one-shot items (cash, free samples) under the same
per-slot data storage key, `mercs_sent_items_<team>_<slot>`. Older versions of
this client used the room-wide key `sent_items`; a seed started with an older
client receives its cash and free samples once more after updating.

### How it works

The PCSX2 backend patches Lua bytecode in emulated memory. The recomp backend
instead runs Lua source in the game's script VM through the bridge: see
`mercenaries/client/recomp_runtime.py`. Card status and mission progress come
from scribble memory; intel, faction floors, money, messages, free samples and
Merchant of Menace unlocks use the game's own script functions.

### Status

Tested here only against stubs and a fake bridge, not the real game yet.
Known gaps:

- **Bounty totals.** Bounties are counted from the scribble memory keys the
  game writes per bounty actor: 110 blueprints, 110 treasures, 55 listening
  posts and 20 monuments over both maps. The apworld defines up to 56 listening
  post and 21 monument checks; with `all` (or a number that reaches the top),
  the 56th listening post and 21st monument cannot be counted on the recomp.
  `vanilla` stops at 55 and 20 and is fine.
- **Shop template names** are taken from the game's `tMafiaShop` table, with a
  `template_support_<name>` fallback. Check them with `:shop` in the console.
- Whether `Shop_UnlockItem` survives save/load, and whether repeating it is
  harmless, still needs checking in game. The runtime unlocks each item once per
  script VM and again after a load.

### Exploring the game

`python tools/recomp_repl.py` opens a console to the running game. Type Lua to
run it in the game (`=Player_GetMoney()` prints a value), or use `:globals`,
`:shop`, `:poll`, `:read` and `:scan`. The full command list is at the top of the
script.

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
