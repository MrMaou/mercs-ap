'''
Game backend for Mercenaries Recompiled (the native Windows port of the Xbox
version), via the local bridge of the Archipelago plugin in the recomp fork.

It implements the same interface as MercenariesIPC (the PCSX2 backend), so the
connector and location logic work unchanged. The difference is how it talks to
the game: almost everything is plain Lua run in the game's script VM (see
recomp_runtime.py), plus a few raw reads of Xbox guest memory to tell when the
player is in normal gameplay.

Xbox guest addresses below come from the recomp's own title code (dev mission
menu and mod gameplay hooks), which is tied to the one supported retail XBE.
'''

import itertools
import struct
import uuid
from contextlib import contextmanager

from CommonClient import logger

from ..data import recompdata
from ..items.shop import ShopItem
from .bridge import Bridge, BridgeError, LuaError
from .MercenariesIPC import IPCError
from .recomp_runtime import RUNTIME, RUNTIME_VERSION

# Guest state used to decide whether it is safe to change the game.
VM_POINTER = 0x003717BC         # master Lua VM (lua_State *)
TRANSITION_PENDING = 0x003717D6  # u8, set while a script-driven transition is queued
MAP_HASH = 0x00403970            # u32, hash of the loaded world map
MAP_SOUTH = 0x4A5220AF
MAP_NORTH = 0x4A364A32
GAMEPLAY_SENTINELS = 0x00413F68  # u32 pair, set to these values in normal gameplay
GAMEPLAY_SENTINEL_VALUES = (0xC2CBD863, 0x4249D707)

SUITS = ('clubs', 'diamonds', 'hearts', 'spades')
FACTIONS = ('allies', 'china', 'mafia', 'sk')


def suit_from_lua(name: str) -> str | None:
  lower = name.lower()
  for suit in SUITS:
    if suit[:-1] in lower:  # 'club', 'diamond', 'heart', 'spade'
      return suit
  return None


class RecompIPC:
  bridge: Bridge
  latest_chapter: int = 0

  def __init__(self, address: str = 'localhost:28012', bridge: Bridge = None, previous: 'RecompIPC' = None):
    self.bridge = bridge or Bridge(address)
    self.installed_vm = None
    self.intel_value = None
    self.floors = {}
    self.shop_names = None
    self.shop_txn = None
    if previous is not None:
      # Delivery ids must never repeat within a VM: the runtime answers 'dup'
      # for a known id without applying the delivery.
      self.delivery_prefix = previous.delivery_prefix
      self.delivery_ids = previous.delivery_ids
      self.pending_delivery = previous.pending_delivery
    else:
      self.delivery_prefix = uuid.uuid4().hex[:8]
      self.delivery_ids = itertools.count(1)
      self.pending_delivery = None
    self.warned_bounties = False
    self.doing_location_checks = False
    self.poll = None

  def __repr__(self):
    return f'RecompIPC({self.bridge.address})'

  def reset(self):
    '''Fresh state on the same connection, after an error. The bridge itself
    reconnects after transport errors, so the socket is kept. Delivery ids and
    any unconfirmed delivery carry over.'''
    return RecompIPC(bridge=self.bridge, previous=self)

  #### Game state ####

  def _call(self, function: str, *args) -> str:
    try:
      return self.bridge.call(function, *args)
    except LuaError as e:
      raise IPCError(f'{function} failed in game: {e}') from e
    except BridgeError as e:
      raise IPCError(str(e)) from e

  def in_gameplay(self) -> bool:
    try:
      sentinels = struct.unpack('<II', self.bridge.read(GAMEPLAY_SENTINELS, 8))
      map_hash = self.bridge.read_u32(MAP_HASH)
      transition = self.bridge.read_u8(TRANSITION_PENDING)
    except BridgeError as e:
      raise IPCError(str(e)) from e
    return (
      sentinels == GAMEPLAY_SENTINEL_VALUES
      and map_hash in (MAP_SOUTH, MAP_NORTH)
      and transition == 0
    )

  def validate(self):
    '''Raise IPCError unless the game is in normal gameplay with our runtime installed.'''
    if not self.in_gameplay():
      raise IPCError('Game is not in normal gameplay')
    try:
      vm = self.bridge.read_u32(VM_POINTER)
      version = self.bridge.lua('return AP_Version and AP_Version() or ""')
    except LuaError as e:
      raise IPCError(f'Script VM error: {e}') from e
    except BridgeError as e:
      raise IPCError(str(e)) from e
    if version != RUNTIME_VERSION or vm != self.installed_vm:
      self.inject(vm)

  def inject(self, vm: int):
    logger.info(f'Installing Archipelago runtime in script VM ${vm:08X}.')
    try:
      version = self.bridge.lua(RUNTIME)
    except BridgeError as e:
      raise IPCError(f'Could not install the Archipelago runtime: {e}') from e
    if version != RUNTIME_VERSION:
      raise IPCError(f'Runtime install returned {version!r}, expected {RUNTIME_VERSION!r}')
    # A new VM has none of our state; force everything idempotent to be re-sent.
    self.installed_vm = vm
    self.intel_value = None
    self.floors = {}
    self.shop_names = None
    self.shop_txn = None
    logger.info('Archipelago runtime installed.')

  def tick(self):
    '''Keep hooks and floors applied; lets the game react to AP intel.'''
    self.validate()
    self._call('AP_Tick')

  def current_chapter(self):
    if self.is_card_verified('spades', 1):
      return 5  # victory!
    elif self.is_card_verified('hearts', 1):
      return 4
    elif self.is_card_verified('diamonds', 1):
      return 3
    elif self.is_card_verified('clubs', 1):
      return 2
    else:
      return 1

  #### Location checks ####

  def _parse_poll(self, text: str):
    values = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
    cards = {suit: [1] * 13 for suit in SUITS}
    missions = {}
    for key, value in values.items():
      if key.startswith('card.'):
        suit_name, _, rank = key[5:].rpartition('.')
        suit = suit_from_lua(suit_name)
        if suit is None:
          continue
        rank = int(float(rank))
        if rank == 14:
          rank = 1  # the engine ranks aces above kings
        if 1 <= rank <= 13:
          cards[suit][rank - 1] = int(float(value))
      elif key.startswith('mission.'):
        missions[key[8:]] = int(float(value))
    north = values.get('quadrant', '').lower() == 'nw'
    return {
      'cards': cards,
      'missions': {f: missions.get(f, 0) + (6 if north else 0) for f in FACTIONS},
      'quadrant': values.get('quadrant', ''),
      'blocked_shop': int(float(values.get('blocked_shop', 0))),
    }

  @contextmanager
  def start_location_checks(self):
    self.validate()
    self.poll = self._parse_poll(self._call('AP_Poll'))
    self.card_cache = self.poll['cards']
    self.mission_cache = self.poll['missions']
    self.bounty_cache = self.read_bounties()
    self.doing_location_checks = True
    self.latest_chapter = self.current_chapter()
    try:
      yield self
    finally:
      self.end_location_checks()

  def end_location_checks(self):
    self.doing_location_checks = False
    self.bounty_cache = None
    self.mission_cache = None
    self.card_cache = None

  def read_bounties(self) -> dict[str, int]:
    if not recompdata.BOUNTY_COUNT_ADDRS:
      if not self.warned_bounties:
        logger.warning('Bounty counter addresses for the recomp are not known yet; bounty checks are disabled.')
        self.warned_bounties = True
      return dict.fromkeys(recompdata.BOUNTY_TYPES, 0)
    counts = {}
    for name in recompdata.BOUNTY_TYPES:
      addr = recompdata.BOUNTY_COUNT_ADDRS.get(name)
      if addr is None:
        counts[name] = 0
        continue
      try:
        raw = self.bridge.read(addr, recompdata.BOUNTY_COUNT_SIZE)
      except BridgeError as e:
        raise IPCError(str(e)) from e
      counts[name] = int.from_bytes(raw, 'little')
    return counts

  def is_checked(self, location):
    assert self.doing_location_checks
    return location.is_checked(self)

  def is_missed(self, location):
    assert self.doing_location_checks
    return location.is_missed(self)

  def is_card_verified(self, suit, rank):
    return self.card_cache[suit][rank - 1] > 1

  def is_card_captured(self, suit, rank):
    return self.card_cache[suit][rank - 1] > 2

  def is_mission_complete(self, faction: str, mission: int) -> bool:
    return mission < self.mission_cache.get(faction, 0)

  def is_bounty_collected(self, type: str, count: int) -> bool:
    return self.bounty_cache.get(type, 0) >= count

  #### Sending items ####

  def send_once(self, money: int = 0, message: str = '', support_item: str = ''):
    '''
    Deliver money, a HUD message and/or a support coupon exactly once.

    Returns True when delivered. A delivery that failed in transit is retried
    with the same id, so the runtime will not apply it twice in the same VM.
    '''
    self.validate()
    if not money and not message and not support_item:
      return False
    payload = (money, message, support_item)
    if self.pending_delivery is None or self.pending_delivery[1] != payload:
      self.pending_delivery = (f'{self.delivery_prefix}-{next(self.delivery_ids)}', payload)
    delivery_id = self.pending_delivery[0]
    self._call('AP_Deliver', delivery_id, money, message, support_item)
    self.pending_delivery = None
    return True

  def set_unlocked_shop_items(self, items: list[ShopItem], txn):
    self.validate()
    names = [item.template for item in items]
    if names == self.shop_names and txn == self.shop_txn:
      return
    result = self._call('AP_SetShop', names)
    if result == 'nohook':
      raise IPCError('Shop_UnlockItem is not available yet')
    applied, _, failed = result.partition('|')
    if applied not in ('', '0'):
      logger.info(f'Unlocked {applied} Merchant of Menace item(s).')
    if failed:
      # Retried on the next sync; the other item types are not held up.
      logger.warning(f'The game refused some shop unlocks (will retry): {failed}')
      return
    self.shop_names = names
    self.shop_txn = txn

  def set_intel(self, amount, target):
    self.validate()
    # The game compares the intel total against iTargetIntel (80 in retail).
    value = (amount / target) * 80.0
    if value != self.intel_value:
      self._call('AP_SetIntel', float(value))
      self.intel_value = value
    self._call('AP_Tick')

  def set_reputation_floor(self, faction, floor):
    self.validate()
    if self.floors.get(faction) == floor:
      return
    self.floors[faction] = floor
    self._call('AP_SetFloors', dict(self.floors))

  #### Diagnostics ####

  def shop_table(self) -> str:
    return self._call('AP_ShopTable')

  def lua(self, source: str) -> str:
    return self.bridge.lua(source)
