#!/usr/bin/env python3
"""End-to-end regression test for the Sendspin Radio Lua relay.

Runs the REAL extension file (lua/ge/extensions/SendspinRadio.lua) under plain
lua5.1, driving its own lifecycle hooks exactly the way BeamNG does, and
checks that bytes actually cross the relay in both directions.

Why this is a separate script and not a unit test: the relay only exists to
move opaque bytes between two TCP sockets. Asserting anything less than
"the exact request arrived upstream and the real 101 came back" would repeat
the mistake that shipped a relay which connected successfully and forwarded
nothing.

Design rules learned the hard way (see the skill beamng-lua-relay-testing):
  * everything in ONE process, so there is a single log stream and no chance
    of reading a previous run's output file;
  * ports are allocated dynamically, so a zombie listener from a failed run
    cannot silently pass for a code bug;
  * the upstream accept loop handles many connections, otherwise a readiness
    probe eats the only one and the test reports a false failure;
  * page sockets are non-blocking, so a pump loop cannot stall on receive();
  * ports are injected into a scratch COPY of the extension, so the committed
    file is never rewritten and the user's real Music Assistant is untouched.

This test deliberately does NOT check for select() before read. That is
package_structure.py's job: a behaviour-only test cannot tell "drainUpstream
read the upstream speculatively" from a healthy link that happened to have
data, so it passed the exact regression that shipped a broken relay. Static
and behavioural checks cover different failures; neither substitutes for the
other.

Usage:  python3 tests/relay_e2e.py [-v]
Exit:   0 = all checks passed, 1 = at least one check failed.
"""
import argparse
import os
import re
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
EXT = os.path.join(REPO, "mod", "lua", "ge", "extensions", "SendspinRadio.lua")
TMP = os.path.join(HERE, ".tmp")

DELIM = b"\x0d\x0a\x0d\x0a"
HANDSHAKE = (
    b"GET /sendspin HTTP/1.1\r\n"
    b"Host: 127.0.0.1\r\n"
    b"Upgrade: websocket\r\n"
    b"Connection: Upgrade\r\n"
    b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
    b"Sec-WebSocket-Version: 13\r\n\r\n"
)
REPLY = (
    b"HTTP/1.1 101 Switching Protocols\r\n"
    b"Upgrade: websocket\r\n"
    b"Connection: Upgrade\r\n"
    b"Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n"
)
# A WebSocket binary frame whose payload is NOT valid UTF-8 and contains
# 0x00/0xFF/0x80. A relay that mangles text corrupts audio exactly here.
BIN_FRAME = bytes([
    0x81, 0x8E, 0x03, 0xF0, 0x9F, 0x92, 0xA9, 0x00,
    0xFF, 0x7F, 0x80, 0xC3, 0x28, 0x7F, 0xAB,
])

captured = []
lock = threading.Lock()
stop = threading.Event()
verbose = False


def log(*a):
    print(*a, flush=True)


def dbg(*a):
    if verbose:
        print("   ", *a, flush=True)


def free_port():
    """Ask the OS for a port nobody holds, then release it.

    Binding to 0 and closing leaves a small race window, which is acceptable:
    a collision shows up as a loud failure, not a silent pass.
    """
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def serve_one(conn, n):
    """Capture one upstream connection: handshake first, then any trailer."""
    conn.settimeout(20)
    handshake = b""
    try:
        while DELIM not in handshake:
            chunk = conn.recv(4096)
            if not chunk:
                log(f"[up] #{n} peer closed before the handshake finished")
                break
            handshake += chunk
    except socket.timeout:
        log(f"[up] #{n} no handshake within 20s")
    except OSError as e:
        log(f"[up] #{n} recv error: {e}")

    # Answer the handshake straight away, like a real WebSocket server would.
    if handshake:
        try:
            conn.sendall(REPLY)
            log(f"[up] #{n} replied 101 ({len(handshake)}B handshake)")
        except OSError as e:
            log(f"[up] #{n} reply failed: {e}")

    # Keep reading so a following binary frame is captured too. A short window
    # here would make a correct relay look like it dropped bytes.
    trailer = b""
    conn.settimeout(12)
    try:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            trailer += chunk
            dbg(f"#{n} post-handshake +{len(chunk)}B (trailer {len(trailer)}B)")
    except socket.timeout:
        dbg(f"#{n} trailer window closed, {len(trailer)}B captured")
    except OSError:
        pass

    with lock:
        captured.append((handshake, trailer))
    log(f"[up] #{n} handshake {len(handshake)}B complete={DELIM in handshake}, "
        f"trailer {len(trailer)}B")
    time.sleep(0.5)
    try:
        conn.close()
    except OSError:
        pass


def upstream_server(srv):
    n = 0
    while not stop.is_set():
        srv.settimeout(1.0)
        try:
            conn, addr = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        n += 1
        log(f"[up] connection #{n} from {addr}")
        threading.Thread(target=serve_one, args=(conn, n), daemon=True).start()
    try:
        srv.close()
    except OSError:
        pass


LUA_DRIVER = r'''
io.stdout:setvbuf('no')
local RELAY = tonumber(os.getenv('RELAY_PORT'))
local function emit(s) print(s) end

-- Patched in by the host: one definition of the handshake shared with Python.
local HANDSHAKE = __HANDSHAKE__
-- Byte constructor, patched in, so binary values survive the trip intact.
local BIN_FRAME = __BINFRAME__

-- Route the extension's own logging into this stream, so one run produces one
-- ordered log instead of splitting the story across two files.
_G.log = function(lvl, org, msg)
  emit('  lua ' .. tostring(lvl) .. ' ' .. tostring(org) .. ' | ' .. tostring(msg))
end

local socket = require('socket')
local ok, M = pcall(dofile, os.getenv('EXT_PATH'))
if not ok then emit('FATAL loading ext: ' .. tostring(M)); os.exit(1) end
-- The port must be set BEFORE the load hook, or startListener binds whatever
-- default the file happens to carry and every later connect() is refused.
M.LOCAL_PORT = RELAY
emit('ext loaded, local port=' .. tostring(M.LOCAL_PORT))
if M.onExtensionLoaded then M.onExtensionLoaded() end
emit('onExtensionLoaded done, isRunning=' .. tostring(M.isRunning()))
emit('status: ' .. tostring(M.getStatus()))

local function pumpFor(ticks)
  for _ = 1, ticks do
    pcall(M.onGuiUpdate, M)
    os.execute('sleep 0.02')
  end
end

local function waitOpen(port, tries)
  for i = 1, tries do
    local t = socket.tcp()
    if t then
      t:settimeout(1)
      if t:connect('127.0.0.1', port) then
        t:close()
        return true, i
      end
      t:close()
    end
    -- Drive the relay while waiting, the way the game would.
    pcall(M.onGuiUpdate, M)
    os.execute('sleep 0.1')
  end
  return false, tries
end

local function session(tag)
  local c = socket.tcp()
  c:settimeout(2)
  local connected, err = c:connect('127.0.0.1', M.LOCAL_PORT)
  emit('[' .. tag .. '] connect -> ' .. tostring(connected) .. ' ' .. tostring(err))
  if not connected then return nil end

  -- Let the handshake actually reach the relay before pumping starts. Sending
  -- and pumping in the same tick beats the bytes before TCP delivers them.
  os.execute('sleep 0.2')
  local _, serr = c:send(HANDSHAKE)
  emit('[' .. tag .. '] sent handshake (' .. #HANDSHAKE .. 'B), send=' .. tostring(serr or 'ok'))

  -- Non-blocking, and read INSIDE the pump loop. Reading only after pumping
  -- finished misses the reply entirely: the relay forwards it into the socket
  -- while we are busy sleeping.
  --
  -- All THREE receive() results matter. On a socket with no line terminator
  -- (binary audio) luasocket returns (nil, 'timeout', partial): the bytes are
  -- ONLY in the third result. Reading just the first would report "nothing
  -- received" while data is sitting right there, which is how a working relay
  -- gets mistaken for a broken one.
  c:settimeout(0)
  local got = ''
  local ticks = 0
  for i = 1, 400 do
    pcall(M.onGuiUpdate, M)
    local line, rerr, partial = c:receive(65536)
    local data = line
    if (not data or data == '') and partial and partial ~= '' then
      data = partial
    end
    if data and data ~= '' then
      got = got .. data
      ticks = i
    end
    if got:find('101 Switching Protocols', 1, true) then
      break
    end
    os.execute('sleep 0.02')
  end
  emit('[' .. tag .. '] total received: ' .. #got .. ' bytes (last data at tick ' ..
       tostring(ticks) .. ')')
  emit('[' .. tag .. '] saw 101 = ' ..
       tostring(got:find('101 Switching Protocols', 1, true) ~= nil))

  local _, berr = c:send(BIN_FRAME)
  emit('[' .. tag .. '] sent binary frame (' .. #BIN_FRAME .. 'B), err=' .. tostring(berr or 'none'))
  pumpFor(150)
  emit('[' .. tag .. '] binary frame pumped')
  c:close()
  return got
end

local opened, tries = waitOpen(RELAY, 60)
emit('relay port open after ' .. tostring(tries) .. ' attempts: ' .. tostring(opened))
if not opened then emit('FATAL: relay never opened its port'); os.exit(1) end

local g1 = session('session1')
os.execute('sleep 0.5')
local g2 = session('session2')

if M.onExtensionUnloaded then M.onExtensionUnloaded() end
emit('teardown done, isRunning=' .. tostring(M.isRunning()))
os.exit(0)
'''


def make_ext_copy(relay_port, upstream_port):
    """Rewrite a COPY of the extension to use loopback ports.

    The committed file keeps its real Music Assistant address; only the
    throwaway copy under tests/.tmp is redirected.
    """
    with open(EXT) as f:
        src = f.read()
    src, n_local = re.subn(r"M\.LOCAL_PORT = \d+", f"M.LOCAL_PORT = {relay_port}", src)
    src, n_host = re.subn(r"M\.UPSTREAM_HOST = '[^']*'", "M.UPSTREAM_HOST = '127.0.0.1'", src)
    src, n_up = re.subn(r"M\.UPSTREAM_PORT = \d+", f"M.UPSTREAM_PORT = {upstream_port}", src)
    if not (n_local and n_host and n_up):
        raise SystemExit(
            "Could not find the port constants in the extension. The relay's "
            "config lines changed shape; update make_ext_copy(). "
            f"(local={n_local} host={n_host} upstream={n_up})"
        )
    os.makedirs(TMP, exist_ok=True)
    copy = os.path.join(TMP, "SendspinRadio_relaytest.lua")
    with open(copy, "w") as f:
        f.write(src)
    return copy


def main():
    global verbose
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()
    verbose = args.verbose

    if not os.path.exists(EXT):
        raise SystemExit(f"extension not found: {EXT}")

    relay_port = free_port()
    upstream_port = free_port()
    log(f"[*] relay port {relay_port}, upstream port {upstream_port}")

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", upstream_port))
    srv.listen(8)
    threading.Thread(target=upstream_server, args=(srv,), daemon=True).start()

    ext_copy = make_ext_copy(relay_port, upstream_port)
    driver = os.path.join(TMP, "driver.lua")
    # str.encode('unicode_escape') is not safe for arbitrary bytes, so the
    # binary frame is written as an explicit byte constructor instead.
    bin_ctor = "string.char(" + ", ".join("0x%02X" % b for b in BIN_FRAME) + ")"
    with open(driver, "w") as f:
        f.write(LUA_DRIVER.replace("__HANDSHAKE__", repr(HANDSHAKE.decode()))
                             .replace("__BINFRAME__", bin_ctor))
    log(f"[*] scratch copy: {ext_copy}")

    env = dict(os.environ, RELAY_PORT=str(relay_port), EXT_PATH=ext_copy)
    proc = subprocess.Popen(
        ["lua5.1", driver],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=env, text=True,
    )
    try:
        out, _ = proc.communicate(timeout=args.timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        rc = "timeout"
    stop.set()
    time.sleep(0.3)

    log("----- lua -----")
    log(out.strip() or "(no output)")
    log("----- /lua -----")
    log(f"[*] lua exit={rc}")

    with lock:
        conns = list(captured)

    failures = []
    if rc != 0:
        failures.append(f"lua driver exited with {rc}")
    if not conns:
        failures.append("upstream saw no connection at all")
    if "saw 101 = true" not in out:
        failures.append("the page never received a 101 from the relay")

    complete = [c for c in conns if DELIM in c[0]]
    if not complete:
        failures.append("no complete WebSocket upgrade request reached upstream")

    exact = [c for c in conns if c[0] == HANDSHAKE]
    if len(exact) < 2:
        failures.append(f"expected 2 byte-exact handshakes upstream, got {len(exact)}")
    else:
        log(f"[ok] {len(exact)} handshakes arrived byte-for-byte "
            f"({len(HANDSHAKE)}B each)")

    binaries = [c for c in conns if BIN_FRAME in c[1]]
    if len(binaries) < 2:
        failures.append(f"expected 2 intact binary frames upstream, got {len(binaries)}")
    else:
        log(f"[ok] {len(binaries)} binary frames survived unmodified "
            f"(0x00/0xFF/0x80, invalid UTF-8)")

    if "teardown done, isRunning=false" in out:
        log("[ok] teardown closed the listener")
    else:
        failures.append("teardown did not report a stopped relay")

    for f in failures:
        log(f"[FAIL] {f}")
    if failures:
        log(f"\nRELAY E2E: FAIL ({len(failures)} problem(s))")
        return 1
    log("\nRELAY E2E: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
