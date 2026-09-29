#!/usr/bin/env python3
"""Structural checks on the mod package.

These are the failure modes that shipped to a user and produced a blank
screen or a silently dead relay, and that no runtime test would catch because
the runtime test drives the file directly:

  * the Lua extension must define onExtensionLoaded, or the listener never
    starts and the page reports "relay unavailable";
  * the extension must NOT define onCfxUpdate, which is a FiveM hook that
    BeamNG never calls (using it meant accept/pump never ran);
  * it must NOT use extensions.core.log, which does not exist, or every log
    line is discarded and the game log shows nothing;
  * a mod script must exist, because a file merely sitting in
    lua/ge/extensions/ is never executed;
  * the Vue mod must live in ui/ui-vue/mods/, not the legacy AngularJS path;
  * the two sides must agree on the relay port, or the SDK dials a port nobody
    listens on;
  * onUnload is never fired, so onExtensionUnloaded has to exist too.

Run:  python3 tests/package_structure.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MOD = os.path.join(REPO, "mod")
EXT = os.path.join(MOD, "lua", "ge", "extensions", "SendspinRadio.lua")
SCRIPT = os.path.join(MOD, "scripts", "sendspin_radio", "modScript.lua")
SETTINGS = os.path.join(MOD, "ui", "ui-vue", "mods", "SendspinRadio", "shared", "settings.js")
INDEX = os.path.join(MOD, "ui", "ui-vue", "mods", "SendspinRadio", "index.js")

failures = []


def check(condition, message):
    if condition:
        return True
    failures.append(message)
    return False


def read(path):
    with open(path) as f:
        return f.read()


def strip_comments(src):
    """Remove Lua comments so greps match real code, not prose.

    The extension documents its past mistakes in comments, and a check that
    matched those comments would fail a correct file - or worse, pass a broken
    one whose only remaining mention is a comment.
    """
    src = re.sub(r"--\[\[.*?\]\]", "", src, flags=re.S)
    return "\n".join(re.sub(r"--.*$", "", line) for line in src.splitlines())


def main():
    for path in (EXT, SCRIPT, SETTINGS, INDEX):
        if not os.path.exists(path):
            print(f"[FAIL] missing required file: {os.path.relpath(path, REPO)}")
            return 1

    ext = read(EXT)
    code = strip_comments(ext)

    check(re.search(r"^\s*M\.onExtensionLoaded\s*=", code, re.M) is not None,
          "extension lacks M.onExtensionLoaded: the listener would never start "
          "and the page shows 'relay unavailable'")
    check(re.search(r"^\s*M\.onExtensionUnloaded\s*=", code, re.M) is not None,
          "extension lacks M.onExtensionUnloaded: sockets survive a level "
          "change and the next bind fails")
    check(re.search(r"^\s*M\.onGuiUpdate\s*=", code, re.M) is not None,
          "extension lacks M.onGuiUpdate: the page's WebSocket is pumped in "
          "the UI thread, so audio would stall while paused")

    # A speculative read on a non-blocking socket returns 'closed' for a
    # healthy link and used to tear connections down in a cycle. This exact
    # regression passed the behavioural E2E test, because a link that happens
    # to have data queued reads fine - so the check has to be static.
    selects = re.findall(r"socket\.select\(\{\s*(\w+)\s*\}", code)
    check("upstream" in selects,
          "drainUpstream no longer calls socket.select({ upstream }): reading "
          "it speculatively returns 'closed' for a healthy connection and "
          "tears the link down in a cycle")
    check("listener" in selects,
          "acceptPage no longer calls socket.select({ listener }): without it "
          "the accept path bails out immediately and no page is ever served")
    check("pageSock" in selects,
          "pump no longer calls socket.select({ pageSock }): page bytes would "
          "never be forwarded upstream")
    check(re.search(r"#readable\s*(==|>)\s*0", code) is not None,
          "no select() result is compared with #readable, so the read happens "
          "whether or not data is ready")
    check(re.search(r"pcall\((upstream|pageSock)\.receive", code) is not None,
          "extension calls receive() outside pcall, so a socket error raises "
          "into the game loop")
    check("extensions.core.log" not in code,
          "extension calls extensions.core.log, which does not exist, so every "
          "log line is discarded silently")
    check("M.onCfxUpdate" not in code,
          "extension defines onCfxUpdate, a FiveM hook BeamNG never calls")
    check(re.search(r"_G\.log", code) is not None,
          "extension does not call the global log() the GELua host injects")

    script = read(SCRIPT)
    check("loadManualUnloadExtensions" in script,
          "modScript.lua never calls loadManualUnloadExtensions(): a file in "
          "lua/ge/extensions/ is not executed by itself")
    check("SendspinRadio" in script,
          "modScript.lua does not name the SendspinRadio extension")

    check(not os.path.exists(os.path.join(MOD, "ui", "modules")),
          "legacy ui/modules/ (AngularJS) is present; Vue mods live in "
          "ui/ui-vue/mods/")
    check(os.path.isdir(os.path.join(MOD, "ui", "ui-vue", "mods", "SendspinRadio")),
          "Vue mod is not under ui/ui-vue/mods/SendspinRadio/")

    ext_port = re.search(r"M\.LOCAL_PORT = (\d+)", ext)
    js_port = re.search(r"relayPort:\s*(\d+)", read(SETTINGS))
    check(ext_port is not None, "cannot find M.LOCAL_PORT in the extension")
    check(js_port is not None, "cannot find relayPort in settings.js")
    lua_port = ext_port.group(1) if ext_port else "?"
    page_port = js_port.group(1) if js_port else "?"
    if ext_port and js_port:
        check(ext_port.group(1) == js_port.group(1),
              f"relay port mismatch: Lua listens on {lua_port}, the page "
              f"dials {page_port}")

    if failures:
        for f in failures:
            print(f"[FAIL] {f}")
        print(f"\nPACKAGE STRUCTURE: FAIL ({len(failures)} problem(s))")
        return 1
    print("[ok] extension lifecycle, logging, select-before-read and pcall")
    print("[ok] mod script loads the extension explicitly")
    print("[ok] Vue mod path, no legacy AngularJS tree")
    print(f"[ok] relay port {page_port} agrees on both sides")
    print("\nPACKAGE STRUCTURE: PASS")
    return 0

if __name__ == "__main__":
    sys.exit(main())
