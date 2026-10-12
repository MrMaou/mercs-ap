#!/usr/bin/env python3
'''
Export the apworld's item and location tables, and the recomp Lua runtime, as a
C++ include for the in-game Archipelago client (the "archipelago" plugin in the
Mercenaries Recompiled fork).

Run it with Archipelago's Python, from anywhere:

  python tools/export_recomp_plugin.py PATH/TO/Archipelago OUT/ap_data.inc

PATH/TO/Archipelago is an Archipelago source checkout (for BaseClasses etc).
The apworld is imported from this repository, not from the checkout.
Re-run it whenever items, locations or recomp_runtime.py change, and commit the
result in the recomp fork.
'''

import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
SUITS = ('clubs', 'diamonds', 'hearts', 'spades')
FACTIONS = {'A': 'allies', 'K': 'sk', 'M': 'mafia', 'C': 'china'}
BOUNTY_TYPES = ('listening post', 'blueprint', 'monument', 'treasure')
CHUNK = 3000  # MSVC limits each string literal piece to about 16 KB


def c_string(text: str) -> str:
  out = ['"']
  for ch in text:
    if ch in '\\"':
      out.append('\\' + ch)
    elif 32 <= ord(ch) < 127:
      out.append(ch)
    else:
      out.extend(f'\\x{b:02x}""' for b in ch.encode('utf-8'))
  out.append('"')
  return ''.join(out)


def raw_pieces(text: str) -> str:
  assert ')APLUA"' not in text
  lines = text.splitlines(keepends=True)
  pieces, current = [], ''
  for line in lines:
    if len(current) + len(line) > CHUNK and current:
      pieces.append(current)
      current = ''
    current += line
  pieces.append(current)
  return '\n'.join(f'R"APLUA({piece})APLUA"' for piece in pieces)


def main():
  if len(sys.argv) != 3:
    raise SystemExit(__doc__)
  # tools/ holds scratch scripts named like stdlib modules (inspect.py); keep it off the path.
  here = pathlib.Path(__file__).resolve().parent
  sys.path[:] = [p for p in sys.path if pathlib.Path(p or '.').resolve() != here]
  archipelago = pathlib.Path(sys.argv[1]).resolve()
  out_path = pathlib.Path(sys.argv[2])
  sys.path.insert(0, str(archipelago))
  sys.path.insert(0, str(REPO))
  import ModuleUpdate
  ModuleUpdate.update_ran = True
  # Loading worlds registers any installed Mercenaries apworld; drop it so this
  # repository's copy can register instead.
  from worlds.AutoWorld import AutoWorldRegister
  AutoWorldRegister.world_types.pop('Mercenaries', None)

  from mercenaries.client.recomp_runtime import RUNTIME, RUNTIME_VERSION
  from mercenaries.items import all_items
  from mercenaries.items.filler import CouponItem, MoneyItem, ReputationItem
  from mercenaries.items.intel import CardIntelItem, GenericIntelItem
  from mercenaries.items.shop import ShopItem
  from mercenaries.locations.bounties import BOUNTIES, BountyLocation
  from mercenaries.locations.cards import CARDS, CardLocation
  from mercenaries.locations.missions import MISSIONS, MissionLocation

  items = sorted(all_items(), key=lambda item: item.id)
  groups = set()
  for item in items:
    if isinstance(item, ShopItem):
      groups |= item.groups()
    elif isinstance(item, CouponItem):
      groups |= item.compatible
  group_names = sorted(groups)
  assert len(group_names) <= 64

  def mask(names):
    value = 0
    for name in names:
      value |= 1 << group_names.index(name)
    return f'0x{value:x}ull'

  item_rows = []
  for item in items:
    name = c_string(item.name())
    if isinstance(item, ShopItem):
      row = (f'ItemKind::ShopUnlock, {name}, {c_string(item.template)}, {mask(item.groups())}, '
             f'{item.tag}, 0, 0, -1, nullptr')
    elif isinstance(item, CouponItem):
      row = f'ItemKind::Coupon, {name}, nullptr, {mask(item.compatible)}, 0, 0, 0, -1, nullptr'
    elif isinstance(item, MoneyItem):
      row = f'ItemKind::Money, {name}, nullptr, 0, 0, {item.amount}, 0, -1, nullptr'
    elif isinstance(item, ReputationItem):
      row = f'ItemKind::Reputation, {name}, nullptr, 0, 0, 0, 0, -1, {c_string(item.faction())}'
    elif isinstance(item, (GenericIntelItem, CardIntelItem)):
      suit = SUITS.index(item.suit) if item.suit else -1
      row = f'ItemKind::Intel, {name}, nullptr, 0, 0, 0, {item.intel_amount()}, {suit}, nullptr'
    else:
      raise SystemExit(f'Unknown item type {type(item).__name__}; teach the exporter about it.')
    item_rows.append(f'  {{{item.id}, {row}}},')

  locations = sorted(
    [*CARDS.values(), *MISSIONS.values(), *BOUNTIES.values()], key=lambda location: location.id)
  location_rows = []
  for loc in locations:
    name = c_string(loc.name())
    short = c_string(loc.short_name())
    if isinstance(loc, CardLocation):
      hint = MISSIONS[loc.hint_mission].id if loc.hint_mission else 0
      never_missable = 'true' if loc.rank == 1 or loc.mission == 'A1' else 'false'
      row = (f'LocationKind::Card, {name}, {short}, {SUITS.index(loc.suit)}, {loc.rank}, '
             f'{loc.min_chapter}, {never_missable}, {hint}, nullptr, -1, 0')
    elif isinstance(loc, MissionLocation):
      row = (f'LocationKind::Mission, {name}, {short}, -1, {loc.rank}, {loc.min_chapter}, true, 0, '
             f'{c_string(FACTIONS[loc.faction])}, -1, 0')
    elif isinstance(loc, BountyLocation):
      row = (f'LocationKind::Bounty, {name}, {short}, -1, 0, 0, true, 0, nullptr, '
             f'{BOUNTY_TYPES.index(loc.type)}, {loc.count}')
    else:
      raise SystemExit(f'Unknown location type {type(loc).__name__}; teach the exporter about it.')
    location_rows.append(f'  {{{loc.id}, {row}}},')

  try:
    commit = subprocess.run(['git', '-C', str(REPO), 'describe', '--always', '--dirty'],
                            capture_output=True, text=True, check=True).stdout.strip()
  except (OSError, subprocess.CalledProcessError):
    commit = 'unknown'

  text = f'''// Generated by mercs-ap tools/export_recomp_plugin.py ({commit}). Do not edit.
// Item and location tables from the apworld, and the Lua runtime from
// mercenaries/client/recomp_runtime.py. Include after game_data.hpp.
namespace apdata {{

constexpr const char *GAME = "Mercenaries";
constexpr const char *RUNTIME_VERSION = {c_string(RUNTIME_VERSION)};
constexpr const char *RUNTIME =
{raw_pieces(RUNTIME)};

constexpr const char *GROUP_NAMES[] = {{{', '.join(c_string(g) for g in group_names)}}};
constexpr const char *BOUNTY_TYPES[] = {{{', '.join(c_string(t) for t in BOUNTY_TYPES)}}};

// id, kind, name, template, groups, tag, money, intel, intel suit, faction
constexpr Item ITEMS[] = {{
{chr(10).join(item_rows)}
}};

// id, kind, name, short name, suit, rank, min chapter, never missable,
// hint mission location id, mission faction, bounty type, bounty count
constexpr Location LOCATIONS[] = {{
{chr(10).join(location_rows)}
}};

}}  // namespace apdata
'''
  out_path.write_text(text, encoding='utf-8', newline='\n')
  print(f'Wrote {len(item_rows)} items and {len(location_rows)} locations to {out_path}')


if __name__ == '__main__':
  main()
