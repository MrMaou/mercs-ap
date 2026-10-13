'''
Recomp backend data that does not come from Lua.

Bounty counts come from AP_Poll (see client/recomp_runtime.py): the game marks
each collected or destroyed bounty with a scribble memory key, and the runtime
counts them per type. BOUNTY_POLL_KEYS maps the poll's short keys to the bounty
type names used by the locations.
'''

# Bounty type names, matching the PCSX2 backend and the location definitions.
BOUNTY_TYPES = ('listening post', 'blueprint', 'monument', 'treasure')

BOUNTY_POLL_KEYS = {
  'lp': 'listening post',
  'bp': 'blueprint',
  'mon': 'monument',
  'tr': 'treasure',
}
