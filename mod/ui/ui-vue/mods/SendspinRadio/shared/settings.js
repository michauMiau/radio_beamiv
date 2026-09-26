// Connection settings and the shared reactive player singleton.
//
// Streaming is pure browser-side work (WebSocket + AudioContext + AudioDecoder),
// so nothing here touches Lua. The bridge is only used to register UI surfaces.

const SETTINGS_KEY = "sendspinRadio.settings"

export const DEFAULTS = {
  // Music Assistant's built-in Sendspin server (reached through the Lua relay).
  host: "192.168.1.198",
  port: 8927,
  // Loopback port the Lua extension listens on for the Vue page's WebSocket.
  relayPort: 18124,
  volume: 70,
  // "sync" keeps multi-device playback aligned; "quality-local" trades sync for local quality.
  correctionMode: "sync",
}

function loadSettings() {
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY)
    if (!raw) return { ...DEFAULTS }
    return { ...DEFAULTS, ...JSON.parse(raw) }
  } catch (e) {
    return { ...DEFAULTS }
  }
}

export function saveSettings(settings) {
  try {
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings))
  } catch (e) {
    // Persistence is a convenience, never a hard requirement.
  }
}

export const settings = loadSettings()

export function baseUrl(s = settings) {
  return `http://${s.host}:${s.port}`
}

export function sendspinWsUrl(s = settings) {
  return `ws://${s.host}:${s.port}/sendspin`
}

// BeamNG's page CSP only allows loopback in connect-src, so the page never talks
// to the LAN directly. It talks to this loopback relay, which the Lua extension
// (SendspinRadio.lua) pumps through to the real Music Assistant server.
export function relayWsUrl(s = settings) {
  const port = s.relayPort || 18124
  return `ws://127.0.0.1:${port}/sendspin`
}
