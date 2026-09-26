<template>
  <div
    v-bng-scoped-nav="{
      scopeId: SCOPE_ID,
      canDeactivate: () => false,
      preferAutoFocus: true,
      trapPolicy: SCOPE_TRAP_POLICIES.ALWAYS,
    }"
    class="radio-screen"
    v-bng-blur
    tabindex="-1"
  >
    <header class="radio-screen__header">
      <BngButton
        class="radio-back"
        bng-scoped-nav-autofocus
        :accent="ACCENTS.custom_old"
        sound-class="bng_back_hover_generic"
        v-bng-on-ui-nav:back,menu.asMouse
        @click="goBack"
      >
        <TransportIcon name="back" />
        <BngBinding ui-event="back" controller track-ignore />
        {{ $tt("ui.common.back") }}
      </BngButton>
      <BngCardHeading type="ribbon" class="radio-screen__title">
        Sendspin Radio
      </BngCardHeading>
      <span class="radio-screen__status" :class="statusClass">{{ statusLabel }}</span>
    </header>

    <main class="radio-screen__body">
      <section class="radio-screen__panel">
        <h3 class="radio-screen__h3">Now playing</h3>

        <div v-if="playerState.pairingPin" class="radio-pin">
          Enter this PIN in Music Assistant to pair
          <strong>{{ playerState.pairingPin }}</strong>
        </div>

        <p v-if="playerState.error" class="radio-error">{{ playerState.error }}</p>

        <div class="radio-now">
          <div class="radio-now__title">{{ playerState.trackTitle || "Nothing playing" }}</div>
          <div class="radio-now__artist">{{ playerState.trackArtist }}</div>
          <div v-if="playerState.groupName" class="radio-now__group">
            Group: {{ playerState.groupName }}
          </div>

          <div v-if="playerState.progressMs !== null" class="radio-progress">
            <div class="radio-progress__bar">
              <div class="radio-progress__fill" :style="{ width: progressPercent }"></div>
            </div>
            <div class="radio-progress__times">
              <span>{{ formatTime(playerState.progressMs) }}</span>
              <span>{{ formatTime(playerState.durationMs) }}</span>
            </div>
          </div>
        </div>

        <div class="radio-controls">
          <BngButton
            class="radio-btn"
            :disabled="!canControl"
            title="Previous track"
            @click="sendCommand('previous')"
          >
            <TransportIcon name="previous" />
          </BngButton>
          <BngButton
            class="radio-btn radio-controls__play"
            :disabled="!connected"
            :title="playerState.isPlaying ? 'Pause' : 'Play'"
            @click="onPlayToggle"
          >
            <TransportIcon :name="playerState.isPlaying ? 'pause' : 'play'" />
          </BngButton>
          <BngButton
            class="radio-btn"
            :disabled="!canControl"
            title="Next track"
            @click="sendCommand('next')"
          >
            <TransportIcon name="next" />
          </BngButton>

          <div class="radio-controls__volume">
            <BngButton
              class="radio-btn"
              :title="isMuted ? 'Unmute' : 'Mute'"
              @click="toggleMute"
            >
              <TransportIcon :name="isMuted ? 'volumeOff' : 'volumeUp'" />
            </BngButton>
            <input
              class="radio-slider"
              type="range"
              min="0"
              max="100"
              :value="playerState.volume"
              @input="onVolume"
            />
            <span class="radio-controls__volvalue">{{ playerState.volume }}</span>
          </div>
        </div>
      </section>

      <section class="radio-screen__panel">
        <h3 class="radio-screen__h3">Server</h3>

        <label class="radio-field">
          <span>Music Assistant</span>
          <span class="radio-pair">
            <input v-model="host" class="radio-input radio-input--sm" type="text" @change="applySettings" />
            <input v-model.number="port" class="radio-input radio-input--sm" type="number" @change="applySettings" />
          </span>
        </label>
        <label class="radio-field">
          <span>Relay port (loopback)</span>
          <input v-model.number="relayPort" class="radio-input" type="number" @change="applySettings" />
        </label>
        <label class="radio-field">
          <span>Sync mode</span>
          <select v-model="correctionMode" class="radio-input" @change="applySettings">
            <option value="sync">Sync with other players</option>
            <option value="quality-local">Best local quality</option>
            <option value="quality">Quality (resync often)</option>
          </select>
        </label>

        <div class="radio-actions">
          <BngButton @click="reconnect">Reconnect</BngButton>
          <BngButton :disabled="!connected" @click="disconnect">Disconnect</BngButton>
        </div>

        <dl class="radio-diag">
          <div><dt>Endpoint</dt><dd>{{ endpoint }}</dd></div>
          <div><dt>Status</dt><dd>{{ playerState.status }}</dd></div>
          <div><dt>Codec</dt><dd>{{ playerState.codec || "—" }}</dd></div>
          <div><dt>Sync error</dt><dd>{{ syncText }}</dd></div>
          <div><dt>Player state</dt><dd>{{ playerState.status === "connected" ? "synchronized" : "—" }}</dd></div>
        </dl>
        <p v-if="playerState.pairingDetail" class="radio-pairing">
          {{ playerState.pairingDetail }}
        </p>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, ref } from "vue"
import { BngButton, BngCardHeading, BngBinding, ACCENTS } from "@/common/components/base"
import { vBngBlur, vBngScopedNav, vBngOnUiNav } from "@/common/directives"
import { SCOPE_TRAP_POLICIES } from "@/services/scopedNav/types"
import SysInfo from "@/services/sysInfo"
import { lua } from "@/bridge"
import TransportIcon from "../shared/TransportIcon.vue"
import {
  playerState,
  connect,
  disconnect,
  reconfigure,
  togglePlay,
  sendCommand,
  setVolume,
  toggleMute,
  unlockAudio,
} from "../shared/player.js"
import { settings, saveSettings, baseUrl } from "../shared/settings.js"

const SCOPE_ID = "sendspin-radio-route"
const host = ref(settings.host)
const port = ref(settings.port)
const relayPort = ref(settings.relayPort || 18124)
const correctionMode = ref(settings.correctionMode)

const connected = computed(() => playerState.status === "connected")
const canControl = computed(() => connected.value)
const endpoint = computed(() => baseUrl({ host: host.value, port: port.value }))

const isMuted = computed(() => playerState.muted || playerState.volume === 0)

const statusLabel = computed(() => {
  switch (playerState.status) {
    case "connected":
      return playerState.isPlaying ? "Playing" : "Paused"
    case "connecting":
      return "Connecting…"
    case "error":
      return "Error"
    default:
      return "Offline"
  }
})

const statusClass = computed(() => `radio-screen__status--${playerState.status}`)

const progressPercent = computed(() => {
  const { progressMs, durationMs } = playerState
  if (!durationMs || progressMs === null) return "0%"
  return `${Math.min(100, Math.max(0, (progressMs / durationMs) * 100))}%`
})

const syncText = computed(() => {
  if (playerState.syncErrorMs === null) return "—"
  return `${playerState.syncErrorMs.toFixed(1)} ms`
})

function formatTime(ms) {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "--:--"
  const total = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`
}

async function onPlayToggle() {
  if (!connected.value) {
    await unlockAudio()
    await connect()
    return
  }
  await togglePlay()
}

function onVolume(event) {
  setVolume(Number(event.target.value))
}

function applySettings() {
  settings.host = String(host.value).trim()
  settings.port = Number(port.value) || 8927
  settings.relayPort = Number(relayPort.value) || 18124
  settings.correctionMode = correctionMode.value
  saveSettings(settings)
  // A new host means a new socket, so rebuild it. The relay's upstream is
  // pointed at the new server from Lua as well.
  syncUpstreamToLua()
  reconfigure()
}

function reconnect() {
  reconfigure()
}

// Point the Lua relay's upstream at the configured Music Assistant, so the
// loopback socket keeps working when the host changes.
async function syncUpstreamToLua() {
  try {
    await lua.extensions.SendspinRadio.setUpstream(settings.host, settings.port)
  } catch (e) {
    // Extension absent: the next connect attempt will explain it.
    console.warn("SendspinRadio: could not reach the Lua relay", e)
  }
}

// bngVue lives on window; the fallback keeps the button safe if the game has
// not exposed it yet.
const bngVue = window.bngVue || { gotoGameState() {}, goBack() {} }

// This screen is reachable both from the main menu and in-game, so the back
// action has to differ: in-game it returns to the pause state.
async function goBack() {
  try {
    if (await SysInfo.isInGame()) {
      return bngVue.gotoGameState("pause")
    }
  } catch (e) {
    // isInGame is best-effort; fall through to a plain goBack.
  }
  return bngVue.goBack()
}
</script>

<style scoped lang="scss">
.radio-screen {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 2rem 4rem;
  overflow-y: auto;
  pointer-events: all;
  color: var(--bng-off-white);
  // The game view shows through unless the screen paints its own backdrop;
  // without this the HUD floats on the 3D scene.
  background-image:
    linear-gradient(115deg, rgba(var(--bng-cool-gray-900-rgb), 0.96), rgba(var(--bng-cool-gray-800-rgb), 0.82)),
    repeating-linear-gradient(135deg, transparent 0 2rem, rgba(var(--bng-orange-500-rgb), 0.05) 2rem 2.15rem);
}

// Give the back button a real button shape. Without explicit sizing the
// component collapses around its text and reads as plain words on the overlay.
.radio-back {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  min-width: 7.5rem;
  min-height: 2.4rem;
  padding: 0.35rem 1.1rem;
  flex-shrink: 0;
  font-size: 0.95rem;
  line-height: 1.2;
  color: var(--bng-off-white) !important;

  :deep(.transport-ico) {
    width: 1.05rem;
    height: 1.05rem;
    flex-shrink: 0;
  }
}

.radio-screen__header {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.radio-screen__title { flex: 1 1 auto; }

.radio-screen__status {
  padding: 0.2em 0.8em;
  border-radius: 1em;
  background: rgba(255, 255, 255, 0.1);
  font-size: 0.9em;

  &--connected { background: rgba(120, 190, 120, 0.25); }
  &--connecting { background: rgba(220, 180, 90, 0.25); }
  &--error { background: rgba(220, 110, 110, 0.25); }
}

.radio-screen__body {
  display: flex;
  flex-wrap: wrap;
  gap: 1.5rem;
  align-items: flex-start;
  overflow-y: auto;
}

.radio-screen__panel {
  flex: 1 1 22em;
  min-width: 20em;
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
}

.radio-screen__h3 { margin: 0; font-size: 1.05em; opacity: 0.85; }

.radio-error { color: #e08b8b; margin: 0; }

.radio-pin {
  padding: 0.5em 0.8em;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 0.3em;
  display: flex;
  justify-content: space-between;
  gap: 1em;
}

.radio-now { display: flex; flex-direction: column; gap: 0.25em; }

.radio-now__title { font-size: 1.3em; }
.radio-now__artist { opacity: 0.8; }
.radio-now__group { font-size: 0.85em; opacity: 0.6; }

.radio-progress { margin-top: 0.6em; }

.radio-progress__bar {
  height: 4px;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 2px;
  overflow: hidden;
}

.radio-progress__fill { height: 100%; background: #bbb; transition: width 0.3s linear; }

.radio-progress__times {
  display: flex;
  justify-content: space-between;
  font-size: 0.75em;
  opacity: 0.6;
  margin-top: 0.3em;
}

.radio-controls { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }

.radio-btn { min-width: 2.4em; }

.radio-controls__play { font-size: 1.2em; }

.radio-controls__volume {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1 1 12em;
  min-width: 0;
}

.radio-slider { flex: 1 1 auto; min-width: 0; accent-color: #bbb; }

.radio-controls__volvalue { width: 2em; text-align: right; font-size: 0.85em; opacity: 0.7; }

.radio-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1em;
}

.radio-input {
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: inherit;
  padding: 0.35em 0.5em;
  border-radius: 0.25em;
  font: inherit;
  min-width: 8em;
  text-align: right;
}

.radio-actions { display: flex; gap: 0.6rem; }

.radio-diag {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25em;
  font-size: 0.85em;

  div { display: flex; justify-content: space-between; gap: 1em; }
  dt { opacity: 0.6; margin: 0; }
  dd { margin: 0; text-align: right; word-break: break-all; }
}

.radio-pairing { font-size: 0.8em; opacity: 0.7; margin: 0; }
</style>
