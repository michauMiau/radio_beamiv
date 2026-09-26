# Sendspin Radio — Vue UI mod for BeamNG.drive

Streams music from a **Music Assistant** Sendspin server into the game, with
multi-device sync. Vue 3 SFCs on BeamNG's `ui-vue` mod path (0.39+).

## Why there is a Lua file

BeamNG's Vue page runs under a strict **Content Security Policy** whose
`connect-src` allows loopback only:

```
connect-src 'self' http://localhost:* ws://localhost:* ws://127.0.0.1:* ...
```

A WebSocket to the LAN — `ws://192.168.1.198:8927/sendspin` — is blocked by the
browser. This is **not** the network sandbox, and `-nosandbox` does not change
it. BeamMP hits the same wall and solves it with a separate localhost launcher.

So this mod ships a small **Lua relay** that connects outbound (Lua is not
subject to the page's CSP) and pumps bytes between the Vue page's loopback
socket and the real Music Assistant server. BeamNG bundles LuaSocket, so no
extra dependency is needed.

```
Vue page  ──ws://127.0.0.1:18124──▶  SendspinRadio.lua  ──tcp──▶  192.168.1.198:8927
```

## Install

Unzip so the layout becomes:

```
<BeamNG.drive>/
├── lua/ge/extensions/SendspinRadio.lua
└── ui/ui-vue/mods/SendspinRadio/
```

Windows: `Documents/BeamNG.drive/` · Linux: `~/.local/share/BeamNG.drive/`

Both parts are required — without the Lua extension the page cannot reach the
relay port and the player reports exactly that.

## Use it

- Pause menu → **Mods** tab → *Sendspin Radio*, then press play.
- *Open full player* → server settings and live diagnostics.
- Also reachable from the main menu.

Defaults: Music Assistant `192.168.1.198:8927`, relay `127.0.0.1:18124`. Change
them in the full player's Server panel; they persist in localStorage, and the
host/port change is pushed to the Lua relay automatically.

## Diagnostics

The full player shows the live state, which is what to look at when something
is wrong:

| Message | Meaning |
| --- | --- |
| `no relay on the loopback port…` | Lua extension did not load, or port mismatch |
| `cannot reach server` | Relay is up, but Music Assistant is not accepting |
| `autoplay blocked — click Play` | Browser policy; press play again |

Check the game's own log for `[SendspinRadio]` lines: the relay logs when it
binds, when the page connects, and why an upstream connect failed.

## Layout

```
lua/ge/extensions/SendspinRadio.lua     loopback ↔ LAN byte pump (non-blocking)
ui/ui-vue/mods/SendspinRadio/
├── index.js              onLoad/onUnload: routes, pause button, cleanup
├── routes.js             Vue route record (carries the live component)
├── lib/sendspin.js       bundled @sendspin/sendspin-js 5.0.0 (ESM, minified)
├── shared/
│   ├── player.js         player singleton, reactive state, loopback socket
│   └── settings.js       host/port/relayPort/volume, localStorage-backed
├── cards/RadioCard.vue   compact player for the Mods pause tab
└── views/RadioScreen.vue full-screen player with settings + diagnostics
```

## Notes

- One player singleton is shared by both surfaces, so audio continues when
  moving between the pause card and the full screen.
- Audio needs a real user gesture; it unlocks on the first press of play.
- `onUnload` does not run on an F5 UI reload, so `index.js` also hooks
  `beforeunload` to close the socket.
- The relay never blocks the game loop: every socket is non-blocking and pumped
  from `onUpdate`, with `socket.select` polling.
