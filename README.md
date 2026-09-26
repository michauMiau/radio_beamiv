# Sendspin Radio for BeamNG.drive

Internet radio player using the Sendspin protocol, streaming from a Music
Assistant server on your LAN.

A compact card lives in the pause-menu **Mods** tab; clicking it opens a
full-screen player. Both surfaces share one player instance, so audio keeps
playing while you move between them.

## Architecture

Three parts, and the middle one is the interesting bit:

1. **Music Assistant** (on your LAN) — runs the Sendspin server on port `8927`
2. **Lua relay** (`mod/lua/ge/extensions/SendspinRadio.lua`) — a loopback TCP
   pump inside BeamNG, forwarding bytes to Music Assistant
3. **Vue UI** (`mod/ui/ui-vue/mods/SendspinRadio/`) — the player UI and the
   official `@sendspin/sendspin-js` client

No custom proxy server, and no Python in the loop. Music Assistant speaks
Sendspin natively.

### Why the Lua relay exists

BeamNG's Vue page runs under a strict Content Security Policy:

```text
connect-src 'self' http://localhost:* ... ws://127.0.0.1:* wss://127.0.0.1:*
```

Only loopback is reachable from the page. A WebSocket aimed straight at
`ws://192.168.1.198:8927/sendspin` is blocked by the browser, and `-nosandbox`
does **not** relax CSP — that flag governs the network sandbox, a separate
mechanism.

So the page connects to `ws://127.0.0.1:18124`, which satisfies CSP, and the
Lua extension makes the LAN connection instead. Lua is not subject to the
page's CSP. This mirrors what BeamMP does with its localhost launcher, just in
the other direction.

## Requirements

- Music Assistant reachable from the BeamNG machine, Sendspin server enabled
- BeamNG.drive with the modern Vue UI (v0.39+)

## Install

Copy the zip into your mods folder — **do not extract it**:

```text
C:\Users\<you>\AppData\Local\BeamNG.drive\current\mods\repo\sendspin-radio.zip
```

Put it in `repo` if you want updates from the BeamNG repository; `mods` works
too. The zip contains both the Lua extension and the Vue UI, and they must ship
together — the UI alone cannot reach the network.

## Configure

Defaults live in `mod/ui/ui-vue/mods/SendspinRadio/shared/settings.js`:

- Music Assistant host — `192.168.1.198`
- Sendspin port — `8927`
- Loopback relay port — `18124`
- Initial volume

You can also change the host and port from the full-screen player's settings
panel at runtime; the relay is re-pointed through the Lua bridge.

## Use

Open the pause menu, go to the **Mods** tab, and press the Sendspin Radio card.
"Open full player" goes to the full view with settings and diagnostics.

The status line reports what the relay is doing, e.g.
`relay 127.0.0.1:18124 -> 192.168.1.198:8927 ok`. When something is wrong it
says why — missing LuaSocket, a failed bind, or no upstream — rather than a
bare connection error.

## Build

The mod ships as a zip; the source of truth is the `mod/` folder.

```bash
cd mod
zip -r ../sendspin-radio.zip lua ui README.md -x "*.DS_Store"
```

`sendspin-radio.zip` is deliberately git-ignored, since it is generated from
`mod/`.

## Troubleshooting

**"Lua extension is not loaded"** — the zip is not installed, or only the `ui/`
part was copied. The Lua extension and the UI must be in the same zip.

**"LuaSocket could not be loaded in this build"** — this BeamNG build does not
expose LuaSocket to `lua/ge/extensions`. Check the log for which import paths
were tried.

**"relay is not listening ... (bind or listen failed)"** — port `18124` is
already taken, usually by a second copy of the mod or a stale game process.

**Connection works, no audio** — the page decodes in the browser. Confirm the
codec field in the diagnostics panel; an unsupported codec means the browser
lacks the matching `AudioDecoder` support.

## License

The mod code is original. `@sendspin/sendspin-js` is bundled in
`mod/ui/ui-vue/mods/SendspinRadio/lib/sendspin.js` under its own license.
