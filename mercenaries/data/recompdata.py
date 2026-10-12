'''
Xbox guest-memory locations for Mercenaries Recompiled that have no Lua API.

Everything else the recomp backend needs comes from Lua (see
client/recomp_runtime.py). Bounty counts are kept by the native PDA stats code,
so they must be read from memory, and their Xbox addresses are not known yet.

To find one, run tools/recomp_repl.py while playing, then:
  scan start
  (collect one bounty of the type you are hunting)
  scan inc
  (repeat collect / scan inc until one or two addresses remain)
  scan list
and enter the address here. BOUNTY_COUNT_SIZE is the width of the counter.
'''

# Bounty type names, matching the PCSX2 backend and the location definitions.
BOUNTY_TYPES = ('listening post', 'blueprint', 'monument', 'treasure')

# type -> guest address of the collected count. Empty disables bounty checks.
BOUNTY_COUNT_ADDRS: dict[str, int] = {}

BOUNTY_COUNT_SIZE = 4
