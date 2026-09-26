/*
 * Sendspin Radio — Vue-only UI mod.
 *
 * Layout, following the official Anna's Toolbox example:
 *   1. A button in the shared "Mods" pause tab, rendering the compact player.
 *   2. A standalone full-screen route opened from that card.
 *
 * No Lua is needed: streaming runs entirely in the browser (WebSocket +
 * AudioContext + AudioDecoder) and both UI registries are reachable from the
 * Vue bridge.
 *
 * Note: onUnload is NOT called on an F5 UI reload, so the socket is also torn
 * down on the page's own beforeunload.
 */

import { useBridge } from "@/bridge"
import { ROUTE_SOURCE_ID, ROUTE_NAME, routeRecords } from "./routes.js"
import { disconnect } from "./shared/player.js"

const { lua, events } = useBridge()

const MOD_ROOT = "/ui/ui-vue/mods/SendspinRadio"
const TITLE = "Sendspin Radio"

function addMainMenuButton(addButton) {
  addButton({
    title: TITLE,
    iconId: "music_note",
    action: ROUTE_NAME,
  })
}

// Vue needs the live component; Lua only understands the serialisable shape.
function toLuaRoutes(records) {
  return records.map((record) => ({
    name: record.name,
    path: record.path,
    meta: record.meta,
    ...(record.children ? { children: toLuaRoutes(record.children) } : {}),
  }))
}

async function registerRoutes() {
  window.bngRoutes.add([{ path: ROUTE_SOURCE_ID, routes: routeRecords }])
  const result = await lua.extensions.ui_router_routeManager.registerModRoutes(
    ROUTE_SOURCE_ID,
    toLuaRoutes(routeRecords),
  )
  if (!result?.success) {
    window.bngRoutes.remove([ROUTE_SOURCE_ID])
    console.error("SendspinRadio: route registration failed", result?.errors)
  }
  return result
}

async function unregisterRoutes() {
  window.bngRoutes.remove([ROUTE_SOURCE_ID])
  await lua.extensions.ui_router_routeManager.unregisterModRoutes(ROUTE_SOURCE_ID, {
    fallbackRoute: "menu",
  })
}

// onUnload does not fire on F5, so make sure the socket does not survive it.
function installHotReloadCleanup() {
  if (window.__sendspinRadioCleanupInstalled) return
  window.__sendspinRadioCleanupInstalled = true
  window.addEventListener("beforeunload", () => {
    try {
      disconnect()
    } catch (e) {
      // nothing useful to do while the page is going away
    }
  })
}

export async function onLoad() {
  installHotReloadCleanup()

  const routeResult = await registerRoutes()
  if (routeResult?.success) {
    events.on("MainMenuButtons", addMainMenuButton)
    events.emit("BroadcastMainMenuButtons")
  }

  // One button in the shared "Mods" pause tab. That tab only shows while at
  // least one mod contributes to it.
  await lua.extensions.ui_pause_actions.registerModButton({
    id: "sendspin-radio-card",
    tabId: "mods",
    label: TITLE,
    icon: "music_note",
    componentName: `${MOD_ROOT}/cards/RadioCard.vue`,
  })
}

export async function onUnload() {
  events.off("MainMenuButtons", addMainMenuButton)
  events.emit("BroadcastMainMenuButtons")

  disconnect()
  await unregisterRoutes()

  await lua.extensions.ui_pause_actions.unregisterModButton("sendspin-radio-card")
}
