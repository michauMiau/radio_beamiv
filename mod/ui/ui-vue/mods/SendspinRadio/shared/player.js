// The Sendspin player singleton.
//
// One player per mod, shared by every surface (pause-menu card and full-screen
// route) so audio keeps running when the user moves between them. All audio work
// happens in the browser: WebSocket transport, AudioContext clock sync and
// AudioDecoder decoding. Lua is never involved in streaming.

import { reactive } from "vue"
import { SendspinPlayer } from "../lib/sendspin.js"
import { lua } from "@/bridge"
import { baseUrl, relayWsUrl, settings, saveSettings } from "./settings.js"

// Name of the Lua extension that owns the loopback relay. Kept in one place so
// the JS and the .lua file cannot drift apart.
const EXTENSION = "SendspinRadio"

export const playerState = reactive({
  /** "idle" | "connecting" | "connected" | "error" */
  status: "idle",
  error: "",
  isPlaying: false,
  muted: false,
  volume: settings.volume,
  groupName: "",
  trackTitle: "",
  trackArtist: "",
  trackAlbum: "",
  progressMs: null,
  durationMs: null,
  codec: "",
  syncErrorMs: null,
  framesSeen: 0,
  pairingPin: null,
  pairingDetail: "",
  hasPlayer: false,
})

let player = null
let progressTimer = null

function describeError(err) {
  if (!err) return "unknown error"
  if (err.name === "NotAllowedError") return "autoplay blocked — click Play"
  if (err instanceof TypeError) return "cannot reach server (sandbox or host down)"
  return err.message || String(err)
}

function syncFromState(state) {
  state.volume != null && (playerState.volume = state.volume)
  state.muted != null && (playerState.muted = state.muted)
  playerState.isPlaying = Boolean(state.isPlaying)

  const meta = state.serverState?.metadata
  if (meta) {
    playerState.trackTitle = meta.title || ""
    playerState.trackArtist = meta.artist || ""
    playerState.trackAlbum = meta.album || ""
    if (meta.progress) {
      playerState.progressMs = meta.progress.track_progress
      playerState.durationMs = meta.progress.track_duration
    }
  }

  const group = state.groupState
  if (group) {
    playerState.groupName = group.group_name || ""
  }
}

function startProgressTicker() {
  stopProgressTicker()
  progressTimer = window.setInterval(() => {
    if (!player) return
    try {
      const info = player.trackProgress
      if (info && typeof info.positionMs === "number") {
        playerState.progressMs = info.positionMs
        if (typeof info.durationMs === "number") playerState.durationMs = info.durationMs
      }
    } catch (e) {
      // trackProgress can throw while the stream is renegotiating.
    }
    // Sync error is read by the diagnostics panel, so it has to be sampled
    // here; a function that is never called leaves the readout stuck at "—".
    refreshSyncInfo()
  }, 500)
}

function stopProgressTicker() {
  if (progressTimer) {
    window.clearInterval(progressTimer)
    progressTimer = null
  }
}

function refreshSyncInfo() {
  if (!player) return
  try {
    const info = player.syncInfo
    if (info) playerState.syncErrorMs = info.syncErrorMs
  } catch (e) {
    // not fatal — sync info is informational only, so leave the last good
    // reading rather than blanking the readout.
  }
}

function createPlayer() {
  if (player) return player

  // The SDK normally opens its own socket to baseUrl, but BeamNG's CSP forbids
  // that. So we open a loopback WebSocket ourselves and hand it over: the SDK
  // adopts it (webSocket config, auto-reconnect disabled) and everything then
  // looks like ordinary loopback traffic to the browser.
  const sock = new WebSocket(relayWsUrl())

  player = new SendspinPlayer({
    // baseUrl is still required by the SDK even when webSocket is supplied.
    baseUrl: baseUrl(),
    webSocket: sock,
    clientName: "BeamNG Sendspin Radio",
    productName: "SendspinRadio",
    // NOTE: storage is deliberately left unset. Passing `storage: null` would
    // give the SDK an ephemeral identity, which disables pairing entirely. Left
    // alone it defaults to localStorage, so the client id and pairing PSK
    // survive a UI reload.
    correctionMode: settings.correctionMode,
    onStateChange: (state) => {
      syncFromState(state)
      if (playerState.status !== "connected") playerState.status = "connected"
      if (state.isPlaying) startProgressTicker()
      else stopProgressTicker()
    },
    onPairing: (event, detail) => {
      if (event === "pending") {
        playerState.pairingDetail = "pairing waiting for user gesture"
      } else if (event === "finalized") {
        playerState.pairingDetail = "paired"
        playerState.pairingPin = null
      } else if (event === "aborted") {
        playerState.pairingDetail = `pairing aborted${detail ? `: ${detail}` : ""}`
        playerState.pairingPin = null
      }
    },
    onPairingPin: (pin) => {
      // The server asks us to display a PIN that the operator types in.
      playerState.pairingPin = pin
    },
  })

  playerState.hasPlayer = true
  player.__sock = sock
  return player
}

function waitForSocketOpen(sock, timeoutMs = 5000) {
  return new Promise((resolve, reject) => {
    if (sock.readyState === WebSocket.OPEN) return resolve()
    if (sock.readyState === WebSocket.CLOSED) {
      return reject(new Error("relay socket already closed"))
    }

    let settled = false
    const finish = (fn, value) => {
      if (settled) return
      settled = true
      window.clearTimeout(timer)
      fn(value)
    }

    // The relay is a raw TCP pump, not an HTTP server, so there is nothing to
    // probe on the socket itself. Ask Lua instead: the extension already reports
    // its own state, which tells us *why* the port is dead instead of failing
    // blind after a timeout.
    const askLua = async () => {
      let report
      try {
        const ext = lua.extensions?.[EXTENSION]
        report = ext ? await ext.getStatus() : "Lua extension is not loaded"
      } catch (e) {
        report = `status call failed: ${e?.message || e}`
      }
      finish(reject, new Error(`relay unavailable — ${report}`))
    }

    sock.addEventListener("open", () => finish(resolve), { once: true })
    sock.addEventListener("error", () => askLua(), { once: true })
    sock.addEventListener("close", () => askLua(), { once: true })

    // The port can be open but silent, so also ask once the timeout expires.
    const timer = window.setTimeout(askLua, timeoutMs)
  })
}

export async function connect() {
  if (playerState.status === "connected" || playerState.status === "connecting") return

  playerState.status = "connecting"
  playerState.error = ""

  try {
    const p = createPlayer()
    // The SDK adopts the socket, so it has to be open first.
    await waitForSocketOpen(p.__sock)
    await p.connect()
    playerState.status = "connected"
    playerState.volume = p.volume
    p.setVolume(settings.volume)
    startProgressTicker()
  } catch (e) {
    playerState.status = "error"
    playerState.error = describeError(e)
    // A failed attempt leaves a half-initialised socket behind; drop it so the
    // next attempt starts from a clean object. `player` is the only live
    // reference to the socket, so closing the player is what closes it.
    if (player) {
      try {
        player.disconnect()
      } catch (closeError) {
        console.warn("Sendspin: disconnect after failed connect threw", closeError)
      }
    }
    player = null
    playerState.hasPlayer = false
  }
}

export function disconnect() {
  if (player) {
    // The SDK closes the socket it adopted, but this one was opened here, so
    // close it explicitly. Leaving it open makes the Lua relay see a stale
    // second connection, which is what surfaces as a socket error on reconnect.
    const sock = player.__sock
    // Both closes are best-effort: the teardown must continue even when the SDK
    // or the socket refuses, otherwise one failure strands the page. Swallowing
    // silently would hide a socket that never closes, so it is logged.
    try {
      player.disconnect()
    } catch (disconnectError) {
      console.warn("Sendspin: player.disconnect() threw during teardown", disconnectError)
    }
    if (sock && sock.readyState !== WebSocket.CLOSED) {
      try {
        sock.close()
      } catch (closeError) {
        console.warn("Sendspin: socket.close() threw during teardown", closeError)
      }
    }
  }
  stopProgressTicker()
  player = null
  playerState.hasPlayer = false
  playerState.status = "idle"
  playerState.isPlaying = false
}

// close() is asynchronous, so a reconnect issued right after it can race the
// old socket and hit "already in closing state" inside the browser.
function waitForSocketClosed(sock, timeoutMs = 1500) {
  if (!sock || sock.readyState === WebSocket.CLOSED) return Promise.resolve()
  return new Promise((resolve) => {
    const done = () => {
      sock.removeEventListener("close", done)
      resolve()
    }
    sock.addEventListener("close", done, { once: true })
    window.setTimeout(done, timeoutMs)
  })
}

export async function reconfigure() {
  // Host/port changes need a brand new socket, so tear the old one down first.
  const oldSock = player ? player.__sock : null
  disconnect()
  await waitForSocketClosed(oldSock)
  playerState.groupName = ""
  playerState.trackTitle = ""
  playerState.trackArtist = ""
  playerState.trackAlbum = ""
  playerState.progressMs = null
  playerState.durationMs = null
  playerState.codec = ""
  return connect()
}

// Autoplay policies require the audio context to be unlocked from a real user
// gesture, so this must be called synchronously from a click handler.
export async function unlockAudio() {
  if (!player) createPlayer()
  try {
    await player.unlock()
  } catch (e) {
    playerState.error = describeError(e)
  }
}

export async function sendCommand(command, params) {
  if (!player) return
  try {
    player.sendCommand(command, params)
  } catch (e) {
    // The SDK throws when the server does not advertise the command.
    playerState.error = describeError(e)
  }
}

export async function togglePlay() {
  if (!player) {
    await unlockAudio()
    await connect()
    return
  }
  if (playerState.isPlaying) await sendCommand("pause")
  else await sendCommand("play")
}

export function setVolume(value) {
  const clamped = Math.max(0, Math.min(100, Math.round(value)))
  playerState.volume = clamped
  settings.volume = clamped
  saveSettings(settings)
  if (player) {
    // The SDK throws if the socket is already gone; volume is a local pref too,
    // so keep the stored value and report the failure rather than lose it.
    try {
      player.setVolume(clamped)
    } catch (volumeError) {
      console.warn("Sendspin: setVolume threw; stored volume kept", volumeError)
    }
  }
}

export function toggleMute() {
  if (!player) return
  const next = !playerState.muted
  playerState.muted = next
  try {
    player.setMuted(next)
  } catch (muteError) {
    console.warn("Sendspin: setMuted threw; local mute state kept", muteError)
  }
}

export function openPairingWindow() {
  if (player) player.openPairingWindow()
}

export { baseUrl }
