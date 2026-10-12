'''
Client entry point.

This just contains the startup code; the actual implementation is everywhere
else in this directory.
'''

import asyncio
import os
from os import path
import platform

import Utils
from CommonClient import get_base_parser, gui_enabled, logger, server_loop

from .MercenariesClient import MercenariesContext, tracker_loaded

RECOMP_BRIDGE = 'localhost:28012'

def get_pine_path():
  match platform.system():
    case 'Linux':
      return path.join(os.environ.get('XDG_RUNTIME_DIR', '/tmp'), 'pcsx2.sock')
    case 'Darwin':
      return path.join(os.environ.get('TMPDIR', '/tmp'), 'pcsx2.sock')
    case 'Windows':
      return 'localhost:28011'


def make_ipc(game: str, pine_path: str, bridge_address: str):
  '''
  Pick the game backend. 'auto' prefers a running Mercenaries Recompiled bridge,
  then PCSX2, and otherwise waits for the recomp bridge to appear.
  '''
  from .bridge import Bridge
  from .RecompIPC import RecompIPC

  if game == 'recomp':
    logger.info(f'Using Mercenaries Recompiled via the bridge at {bridge_address}.')
    return RecompIPC(bridge_address)
  if game == 'pcsx2':
    from .MercenariesIPC import MercenariesIPC
    return MercenariesIPC(pine_path)

  bridge = Bridge(bridge_address)
  if bridge.probe():
    logger.info(f'Found Mercenaries Recompiled bridge at {bridge_address}.')
    return RecompIPC(bridge=bridge)
  try:
    from .MercenariesIPC import MercenariesIPC
    ipc = MercenariesIPC(pine_path)
    logger.info('Found PCSX2 via PINE.')
    return ipc
  except OSError:
    pass
  logger.info(f'Neither the recomp bridge ({bridge_address}) nor PCSX2 is running yet; '
              'waiting for Mercenaries Recompiled. Use --game pcsx2 to wait for PCSX2 instead.')
  return RecompIPC(bridge=bridge)


def main(*args):
  Utils.init_logging('MercenariesClient')

  async def actual_main(args):
    ipc = make_ipc(args.game, args.pcsx2, args.recomp)
    ctx = MercenariesContext(args.connect, args.name, args.password, ipc)
    ctx.server_task = asyncio.create_task(server_loop(ctx), name='ServerLoop')
    if tracker_loaded:
      logger.info('Initializing tracker...')
      ctx.run_generator()
    if gui_enabled:
      ctx.run_gui()
    ctx.run_cli()

    await ctx.exit_event.wait()
    await ctx.shutdown()

  import colorama

  parser = get_base_parser()
  parser.add_argument('--pcsx2', default=get_pine_path(), help='Absolute path (unix) or host:port (windows) for PCSX2 PINE connection')
  parser.add_argument('--name', default=None, help='Slot name')
  parser.add_argument('--game', choices=('auto', 'pcsx2', 'recomp'), default='auto',
                      help='Which game to connect to: PS2 version in PCSX2, Mercenaries Recompiled, or auto-detect')
  parser.add_argument('--recomp', default=RECOMP_BRIDGE,
                      help='host:port of the Mercenaries Recompiled Archipelago plugin bridge')

  colorama.init()
  args = parser.parse_args(args)
  asyncio.run(
    actual_main(args),
    debug=True)
  colorama.deinit()


if __name__ == '__main__':
  main()
