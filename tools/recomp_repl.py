#!/usr/bin/env python3
'''
Interactive console for Mercenaries Recompiled through the Archipelago plugin's
local bridge. Use it to explore the game's Lua globals and to find memory
addresses. While the in-game client is connected, only reads (:read, :u32,
:scan) work; Lua is refused so the two cannot both change the game.

  python tools/recomp_repl.py [host:port]

Input is Lua 5.0, run in the game's master script VM:
  return Player_GetMoney()
  =Player_GetMoney()          shorthand: print the value of an expression
  =tMafiaShop                 tables are printed one level deep

Commands start with a colon:
  :info                       bridge status
  :install                    install the Archipelago runtime (AP_* functions)
  :poll                       run AP_Poll and print the result
  :shop                       list tMafiaShop entries (index=template)
  :globals TEXT               list global names containing TEXT (case-insensitive)
  :read ADDR LEN              hex dump guest memory
  :u32 ADDR                   read one little-endian u32
  :scan start                 snapshot all readable guest RAM
  :scan inc | dec | changed | unchanged
                              keep candidates that changed that way since the last snapshot
  :scan eq N                  keep candidates whose value is now N
  :scan step N                keep candidates that changed by exactly N (e.g. 1 after one pickup)
  :scan idle SECONDS          watch the candidates that long, dropping any that change
                              (timers and clocks); do nothing in game meanwhile
  :scan width 1|2|4           counter width (default 4); applies to the next :scan start
  :scan list                  show the remaining candidates (up to 50)
  :quit
'''

import importlib.util
import pathlib
import struct
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
CLIENT = HERE.parent / 'mercenaries' / 'client'


def load(name):
  spec = importlib.util.spec_from_file_location(name, CLIENT / f'{name}.py')
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


bridge_mod = load('bridge')
runtime_mod = load('recomp_runtime')

DUMP_EXPR = '''
local v = ({expr})
if type(v) ~= 'table' then return tostring(v) end
local out, n = {{}}, 0
for k, x in pairs(v) do
  n = n + 1
  if n > 200 then table.insert(out, '...') break end
  table.insert(out, tostring(k) .. ' = ' .. tostring(x))
end
return table.concat(out, '\\n')
'''

# The game's Lua has no string library, so names are filtered here instead.
GLOBALS = '''
local out = {}
for k, v in pairs(_G) do
  if type(k) == 'string' then table.insert(out, k .. ' : ' .. type(v)) end
end
table.sort(out)
return table.concat(out, '\\n')
'''

RAM_START = 0x00010000
RAM_END = 0x04000000
CHUNK = bridge_mod.MAX_RAW
FORMATS = {1: 'B', 2: 'H', 4: 'I'}


class Scanner:
  def __init__(self, bridge):
    self.bridge = bridge
    self.width = 4
    self.snapshot = None  # address -> bytes chunk
    self.candidates = None  # address -> last value

  def read_all(self):
    chunks = {}
    for address in range(RAM_START, RAM_END, CHUNK):
      try:
        chunks[address] = self.bridge.read(address, CHUNK)
      except bridge_mod.BridgeError:
        continue
    return chunks

  def unpack(self, data):
    count = len(data) // self.width
    return struct.unpack(f'<{count}{FORMATS[self.width]}', data[:count * self.width])

  def start(self):
    print('Reading guest RAM...')
    self.snapshot = self.read_all()
    self.candidates = None
    print(f'Snapshot: {len(self.snapshot) * CHUNK // 1024} KiB readable. Now change the value in game.')

  def filter(self, test, name):
    if self.snapshot is None:
      print('Run :scan start first.')
      return
    if self.candidates is None and name == 'unchanged':
      print('Narrow with inc, dec, changed or eq first.')
      return
    print('Reading guest RAM...')
    now = self.read_all()
    found = {}
    if self.candidates is None:
      for base, new_chunk in now.items():
        old_chunk = self.snapshot.get(base)
        if old_chunk is None or (name != 'eq' and old_chunk == new_chunk):
          continue
        for i, (old, new) in enumerate(zip(self.unpack(old_chunk), self.unpack(new_chunk), strict=True)):
          if test(old, new):
            found[base + i * self.width] = new
    else:
      fmt = '<' + FORMATS[self.width]
      for address, old in self.candidates.items():
        base = address - (address - RAM_START) % CHUNK
        chunk = now.get(base)
        if chunk is None:
          continue
        new = struct.unpack_from(fmt, chunk, address - base)[0]
        if test(old, new):
          found[address] = new
    self.candidates = found
    self.snapshot = now
    print(f'{len(found)} candidate(s) left.')

  def idle(self, seconds):
    if not self.candidates:
      print('Narrow with inc, dec, changed, step or eq first.')
      return
    fmt = '<' + FORMATS[self.width]
    print(f'Watching {len(self.candidates)} candidate(s) for {seconds:g}s; leave the game alone...')
    end = time.monotonic() + seconds
    while True:
      bases = {address - (address - RAM_START) % CHUNK for address in self.candidates}
      chunks = {}
      for base in bases:
        try:
          chunks[base] = self.bridge.read(base, CHUNK)
        except bridge_mod.BridgeError:
          pass
      self.candidates = {
        address: old for address, old in self.candidates.items()
        if (base := address - (address - RAM_START) % CHUNK) in chunks
        and struct.unpack_from(fmt, chunks[base], address - base)[0] == old
      }
      if not self.candidates or time.monotonic() >= end:
        break
      time.sleep(1)
    self.snapshot = self.read_all()
    print(f'{len(self.candidates)} candidate(s) left.')

  def list(self):
    if not self.candidates:
      print('No candidates.')
      return
    for addr, value in list(self.candidates.items())[:50]:
      print(f'  ${addr:08X} = {value}')


def main():
  address = sys.argv[1] if len(sys.argv) > 1 else 'localhost:28012'
  bridge = bridge_mod.Bridge(address)
  scanner = Scanner(bridge)
  print(f'Mercenaries Recompiled console, bridge {address}. :quit to exit.')
  while True:
    try:
      line = input('lua> ').strip()
    except (EOFError, KeyboardInterrupt):
      print()
      break
    if not line:
      continue
    try:
      if line.startswith(':'):
        words = line[1:].split()
        cmd, args = words[0], words[1:]
        if cmd in ('quit', 'q', 'exit'):
          break
        elif cmd == 'info':
          for key, value in bridge.info().items():
            print(f'  {key} = {value}')
        elif cmd == 'install':
          print(bridge.lua(runtime_mod.RUNTIME))
        elif cmd == 'poll':
          print(bridge.lua('return AP_Poll()'))
        elif cmd == 'shop':
          print(bridge.lua('return AP_ShopTable()'))
        elif cmd == 'globals':
          text = args[0].lower() if args else ''
          names = bridge.lua(GLOBALS).split('\n')
          print('\n'.join(n for n in names if text in n.split(' : ')[0].lower()))
        elif cmd == 'read':
          addr, length = int(args[0], 0), int(args[1], 0) if len(args) > 1 else 64
          data = bridge.read(addr, length)
          for i in range(0, len(data), 16):
            row = data[i:i + 16]
            text = ''.join(chr(b) if 32 <= b < 127 else '.' for b in row)
            print(f'  {addr + i:08X}  {row.hex(" "):<47}  {text}')
        elif cmd == 'u32':
          addr = int(args[0], 0)
          value = bridge.read_u32(addr)
          print(f'  ${addr:08X} = {value} (0x{value:08X})')
        elif cmd == 'scan':
          sub = args[0] if args else 'list'
          tests = {
            'inc': lambda old, new: new > old,
            'dec': lambda old, new: new < old,
            'changed': lambda old, new: new != old,
            'unchanged': lambda old, new: new == old,
          }
          if sub == 'start':
            scanner.start()
          elif sub in tests:
            scanner.filter(tests[sub], sub)
          elif sub == 'eq':
            target = int(args[1], 0)
            scanner.filter(lambda old, new, target=target: new == target, 'eq')
          elif sub == 'step':
            delta = int(args[1], 0)
            mask = (1 << (8 * scanner.width)) - 1
            scanner.filter(lambda old, new, delta=delta: new == (old + delta) & mask, 'step')
          elif sub == 'idle':
            scanner.idle(float(args[1]) if len(args) > 1 else 60)
          elif sub == 'width':
            scanner.width = int(args[1])
            print(f'Width set to {scanner.width}; run :scan start.')
          else:
            scanner.list()
        else:
          print(f'Unknown command :{cmd}')
      elif line.startswith('='):
        print(bridge.lua(DUMP_EXPR.format(expr=line[1:])))
      else:
        result = bridge.lua(line)
        if result:
          print(result)
    except bridge_mod.BridgeError as e:
      print(f'! {e}')
    except (ValueError, IndexError) as e:
      print(f'! bad command: {e}')


if __name__ == '__main__':
  main()
