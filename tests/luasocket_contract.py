#!/usr/bin/env python3
"""Regression tests for the luasocket read contract the relay depends on.

These exist because the relay shipped a defect that no amount of HTTP
handshake testing could reveal: on a socket whose data has no line
terminator, luasocket's receive() returns (nil, 'timeout', partial) — the
bytes are ONLY in the third result. Reading the first result looks exactly
like an empty socket, which is how a working relay gets mistaken for a
broken one and, worse, how a real regression gets waved through.

Run:  python3 tests/luasocket_contract.py
"""
import socket
import subprocess
import sys
import threading
import time
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

BIN = bytes([0x82, 0x0F, 0x03, 0xF0, 0x9F, 0x92, 0xA9, 0x00,
             0xFF, 0x7F, 0x80, 0xC3, 0x28, 0x7F, 0xAB])

# Reads a binary payload the way the relay does, and reports what came back.
PROBE = r'''
local socket = require('socket')
local port = tonumber(arg[1])
local c = socket.tcp()
c:settimeout(2)
assert(c:connect('127.0.0.1', port))
c:settimeout(0)
os.execute('sleep 0.4')

local readable = socket.select({ c }, nil, 0)
if type(readable) ~= 'table' or #readable == 0 then
  print('NOT_READABLE')
  os.exit(3)
end

local line, err, partial = c:receive(65536)
local data = line
if (not data or data == '') and partial and partial ~= '' then data = partial end
if not data or data == '' then
  print('EMPTY err=' .. tostring(err))
  os.exit(1)
end
print('GOT ' .. #data)
for i = 1, #data do io.write(string.format('%02X', data:byte(i))) end
print()
c:close()
os.exit(0)
'''


def serve_binary(port, ready):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen(1)
    s.settimeout(20)
    ready.set()
    try:
        c, _ = s.accept()
    except socket.timeout:
        s.close()
        return
    time.sleep(0.4)
    c.sendall(BIN)
    time.sleep(3)
    try:
        c.close()
    except OSError:
        pass
    s.close()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    probe = os.path.join(HERE, ".tmp", "contract_probe.lua")
    os.makedirs(os.path.dirname(probe), exist_ok=True)
    with open(probe, "w") as f:
        f.write(PROBE)

    port = free_port()
    ready = threading.Event()
    t = threading.Thread(target=serve_binary, args=(port, ready), daemon=True)
    t.start()
    ready.wait(5)

    proc = subprocess.run(["lua5.1", probe, str(port)],
                          capture_output=True, text=True, timeout=30)
    t.join(timeout=2)
    out = proc.stdout.strip()
    expected_hex = "".join(f"{b:02X}" for b in BIN)

    print(f"[*] sent {len(BIN)} raw binary bytes (no line terminator)")
    print(f"[*] probe said: {out or '(no output)'}")

    failures = []
    if proc.returncode != 0:
        failures.append(f"probe exited {proc.returncode}")
    if "GOT" not in out:
        failures.append(
            "receive() returned nothing readable even though select() reported "
            "the socket as readable")
    elif expected_hex not in out.replace(" ", ""):
        failures.append("bytes came back altered, not byte-for-byte")
    else:
        print(f"[ok] all {len(BIN)} bytes recovered byte-for-byte via the "
              f"third receive() result")

    if "third receive() result" not in (open(__file__).read()):
        failures.append("the docstring no longer documents the partial contract")

    for f in failures:
        print(f"[FAIL] {f}")
    if failures:
        print(f"\nLUASOCKET CONTRACT: FAIL ({len(failures)} problem(s))")
        return 1
    print("\nLUASOCKET CONTRACT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
