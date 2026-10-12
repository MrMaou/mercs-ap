'''
Client for the Archipelago bridge plugin in the Mercenaries Recompiled fork.

The plugin listens on 127.0.0.1 and runs requests on the game thread during its
on_update callback. See ports/mercenaries/plugins/archipelago-bridge/bridge.c in
the recomp fork for the wire format.

Every call is synchronous and blocks until the game has handled the request.
Requests are only serviced while the game is running its input loop, so a call
can take a while during loading screens; it times out rather than hanging.
'''

import contextlib
import socket
import struct

# Status codes, mirroring MERC_LUA_* in mercenaries_plugin.h.
OK = 0
LUA_ERROR = 1
NOT_READY = 2
REJECTED = 3
NO_MEMORY = 4
BAD_RESULT = 5
UNKNOWN_KIND = 255

STATUS_NAMES = {
  OK: 'ok',
  LUA_ERROR: 'Lua error',
  NOT_READY: 'script VM not ready',
  REJECTED: 'rejected by host',
  NO_MEMORY: 'out of guest memory',
  BAD_RESULT: 'unsupported Lua result type',
  UNKNOWN_KIND: 'unknown request kind',
}

MAX_RAW = 64 * 1024


class BridgeError(RuntimeError):
  '''Transport failure or an unusable reply. The game may simply not be running.'''


class BridgeNotReady(BridgeError):
  '''The game is running but has no script VM yet (menus, loading, transitions).'''


class LuaError(BridgeError):
  '''The Lua chunk failed to compile or raised an error.'''


def lua_quote(text: str) -> str:
  '''Quote a Python string as a Lua 5.0 string literal.'''
  out = ['"']
  for byte in text.encode('utf-8'):
    ch = chr(byte)
    if ch == '\\':
      out.append('\\\\')
    elif ch == '"':
      out.append('\\"')
    elif 32 <= byte < 127:
      out.append(ch)
    else:
      # Lua 5.0 understands \ddd (decimal); pad to 3 digits so a following
      # digit cannot be absorbed into the escape.
      out.append(f'\\{byte:03d}')
  out.append('"')
  return ''.join(out)


def lua_value(value) -> str:
  '''Render a Python value as a Lua expression.'''
  if value is None:
    return 'nil'
  if isinstance(value, bool):
    return 'true' if value else 'false'
  if isinstance(value, int):
    return str(value)
  if isinstance(value, float):
    return repr(value)
  if isinstance(value, str):
    return lua_quote(value)
  if isinstance(value, (list, tuple, set, frozenset)):
    return '{' + ', '.join(lua_value(v) for v in value) + '}'
  if isinstance(value, dict):
    return '{' + ', '.join(f'[{lua_value(k)}] = {lua_value(v)}' for k, v in value.items()) + '}'
  raise TypeError(f'Cannot convert {type(value).__name__} to Lua')


class Bridge:
  '''Lazily connecting, auto-reconnecting client for the bridge plugin.'''

  def __init__(self, address: str = 'localhost:28012', timeout: float = 15.0):
    host, _, port = address.rpartition(':')
    self.host = host or 'localhost'
    self.port = int(port)
    self.timeout = timeout
    self.sock: socket.socket | None = None
    self.next_id = 1

  def __repr__(self):
    return f'Bridge({self.host}:{self.port})'

  @property
  def address(self) -> str:
    return f'{self.host}:{self.port}'

  def probe(self) -> bool:
    '''True if something is listening on the bridge port.'''
    try:
      self._connect(timeout=0.5)
      return True
    except BridgeError:
      return False

  def close(self):
    if self.sock is not None:
      with contextlib.suppress(OSError):
        self.sock.close()
    self.sock = None

  def _connect(self, timeout: float | None = None):
    if self.sock is not None:
      return
    try:
      sock = socket.create_connection((self.host, self.port), timeout=timeout or self.timeout)
    except OSError as e:
      raise BridgeError(f'Cannot reach the recomp bridge at {self.address}: {e}') from e
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.settimeout(self.timeout)
    self.sock = sock

  def _recv_exact(self, size: int) -> bytes:
    chunks = []
    while size:
      chunk = self.sock.recv(size)
      if not chunk:
        raise ConnectionError('bridge closed the connection')
      chunks.append(chunk)
      size -= len(chunk)
    return b''.join(chunks)

  def request(self, kind: bytes, payload: bytes = b'') -> tuple[int, bytes]:
    '''Send one request and wait for its reply. Returns (status, payload).'''
    assert len(kind) == 1
    self._connect()
    request_id = self.next_id
    self.next_id = (self.next_id + 1) & 0xFFFFFFFF or 1
    body = struct.pack('<I', request_id) + kind + payload
    try:
      self.sock.sendall(struct.pack('<I', len(body)) + body)
      while True:
        (length,) = struct.unpack('<I', self._recv_exact(4))
        if length < 5:
          raise ConnectionError(f'malformed reply length {length}')
        reply = self._recv_exact(length)
        (reply_id,) = struct.unpack_from('<I', reply)
        if reply_id == request_id:
          return reply[4], reply[5:]
        # A stale reply to a request that timed out earlier; skip it.
    except (OSError, ConnectionError, struct.error) as e:
      # Drop the connection; the plugin discards work queued for it and the
      # next request reconnects cleanly.
      self.close()
      raise BridgeError(f'Bridge request failed: {e}') from e

  #### High-level requests ####

  def info(self) -> dict[str, str]:
    status, data = self.request(b'I')
    if status != OK:
      raise BridgeError(f'info request failed: {STATUS_NAMES.get(status, status)}')
    pairs = (line.split('=', 1) for line in data.decode('utf-8', 'replace').splitlines() if '=' in line)
    return dict(pairs)

  def lua(self, source: str) -> str:
    '''Run a Lua chunk in the game's script VM and return its first result as text.'''
    status, data = self.request(b'L', source.encode('utf-8'))
    text = data.decode('utf-8', 'replace')
    if status == OK:
      return text
    if status == NOT_READY:
      raise BridgeNotReady('The game script VM is not ready.')
    if status == LUA_ERROR:
      raise LuaError(text or 'Lua error')
    raise BridgeError(f'Lua request failed: {STATUS_NAMES.get(status, status)} {text}'.strip())

  def call(self, function: str, *args) -> str:
    '''Call a global Lua function by name with Python arguments.'''
    return self.lua(f'return {function}({", ".join(lua_value(a) for a in args)})')

  def read(self, address: int, size: int) -> bytes:
    data = bytearray()
    while size > 0:
      chunk = min(size, MAX_RAW)
      status, payload = self.request(b'R', struct.pack('<II', address, chunk))
      if status != OK or len(payload) != chunk:
        raise BridgeError(f'Read of {chunk} bytes at ${address:08X} was rejected.')
      data += payload
      address += chunk
      size -= chunk
    return bytes(data)

  def write(self, address: int, data: bytes):
    while data:
      chunk = data[:MAX_RAW]
      status, _ = self.request(b'W', struct.pack('<I', address) + chunk)
      if status != OK:
        raise BridgeError(f'Write of {len(chunk)} bytes at ${address:08X} was rejected.')
      address += len(chunk)
      data = data[MAX_RAW:]

  def read_u8(self, address: int) -> int:
    return self.read(address, 1)[0]

  def read_u32(self, address: int) -> int:
    return struct.unpack('<I', self.read(address, 4))[0]
