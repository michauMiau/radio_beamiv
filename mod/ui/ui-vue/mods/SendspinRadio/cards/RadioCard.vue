<template>
  <div class="radio-card">
    <div class="radio-head">
      <BngCardHeading type="ribbon">
        <img class="radio-icon" :src="icon" alt="" />
        Sendspin Radio
      </BngCardHeading>
      <span class="radio-status" :class="statusClass">{{ statusLabel }}</span>
    </div>

    <div v-if="playerState.pairingPin" class="radio-pin">
      <span class="radio-pin-label">Type this PIN in Music Assistant</span>
      <strong class="radio-pin-value">{{ playerState.pairingPin }}</strong>
    </div>

    <div class="radio-now">
      <div v-if="playerState.trackTitle" class="radio-track">
        <div class="radio-title">{{ playerState.trackTitle }}</div>
        <div v-if="playerState.trackArtist" class="radio-artist">{{ playerState.trackArtist }}</div>
        <div v-if="playerState.progressMs !== null" class="radio-progress">
          <div class="radio-progress-bar">
            <div
              class="radio-progress-fill"
              :style="{ width: progressPercent }"
            ></div>
          </div>
          <div class="radio-times">
            <span>{{ formatTime(playerState.progressMs) }}</span>
            <span>{{ formatTime(playerState.durationMs) }}</span>
          </div>
        </div>
      </div>
      <div v-else class="radio-idle">
        {{ playerState.error || idleHint }}
      </div>
    </div>

    <div class="radio-controls">
      <BngButton
        class="radio-btn"
        :disabled="!canControl"
        title="Previous track"
        @click="previous"
      >
        <TransportIcon name="previous" />
      </BngButton>
      <BngButton
        class="radio-btn radio-play"
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
        @click="next"
      >
        <TransportIcon name="next" />
      </BngButton>

      <div class="radio-volume">
        <BngButton
          class="radio-btn radio-mute"
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
          :disabled="!connected"
          @input="onVolume"
        />
      </div>
    </div>

    <div class="radio-foot">
      <span v-if="playerState.groupName" class="radio-group">{{ playerState.groupName }}</span>
      <span v-if="playerState.codec" class="radio-codec">{{ playerState.codec }}</span>
      <button class="radio-link" @click="openFullScreen">Open full player</button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from "vue"
import { BngButton, BngCardHeading } from "@/common/components/base"
import { lua } from "@/bridge"
import TransportIcon from "../shared/TransportIcon.vue"
import {
  playerState,
  connect,
  togglePlay,
  sendCommand,
  setVolume,
  toggleMute,
  unlockAudio,
} from "../shared/player.js"

import icon from "./radio.png"

const isMuted = computed(() => playerState.muted || playerState.volume === 0)

const ROUTE_NAME = "sendspinRadio.full"

const isConnecting = ref(false)

const connected = computed(() => playerState.status === "connected")
const canControl = computed(() => connected.value && !isConnecting.value)

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

const statusClass = computed(() => `radio-status--${playerState.status}`)

const idleHint = computed(() => {
  if (playerState.status === "idle") return "Press play to connect to Music Assistant"
  return "Nothing playing"
})

const progressPercent = computed(() => {
  const { progressMs, durationMs } = playerState
  if (!durationMs || progressMs === null) return "0%"
  return `${Math.min(100, Math.max(0, (progressMs / durationMs) * 100))}%`
})

function formatTime(ms) {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "--:--"
  const total = Math.max(0, Math.floor(ms / 1000))
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${String(s).padStart(2, "0")}`
}

// The audio context must be unlocked from a real click, so do it first thing.
async function onPlayToggle() {
  isConnecting.value = true
  try {
    if (!connected.value) {
      await unlockAudio()
      await connect()
    } else {
      await togglePlay()
    }
  } finally {
    isConnecting.value = false
  }
}

async function previous() {
  await sendCommand("previous")
}

async function next() {
  await sendCommand("next")
}

function onVolume(event) {
  setVolume(Number(event.target.value))
}

function openFullScreen() {
  lua.extensions.ui_router.push(ROUTE_NAME)
}
</script>

<style scoped lang="scss">
.radio-card {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 0.4rem 0.2rem;
  color: var(--bng-off-white);
}

.radio-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.radio-icon {
  width: 1.4em;
  height: 1.4em;
  margin-right: 0.4em;
  vertical-align: text-bottom;
  object-fit: contain;
}

.radio-status {
  font-size: 0.8em;
  padding: 0.15em 0.6em;
  border-radius: 1em;
  background: rgba(255, 255, 255, 0.1);
  white-space: nowrap;

  &--connected { background: rgba(120, 190, 120, 0.25); }
  &--connecting { background: rgba(220, 180, 90, 0.25); }
  &--error { background: rgba(220, 110, 110, 0.25); }
}

.radio-pin {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.4em 0.6em;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 0.3em;
}

.radio-pin-label { font-size: 0.8em; opacity: 0.8; }
.radio-pin-value { font-size: 1.1em; letter-spacing: 0.1em; }

.radio-now { min-height: 3.2em; }

.radio-track { display: flex; flex-direction: column; gap: 0.2em; }

.radio-title {
  font-size: 1em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.radio-artist {
  font-size: 0.85em;
  opacity: 0.75;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.radio-progress { margin-top: 0.3em; }

.radio-progress-bar {
  height: 3px;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 2px;
  overflow: hidden;
}

.radio-progress-fill {
  height: 100%;
  background: var(--bng-rgba-190-190-190-0-6);
  transition: width 0.3s linear;
}

.radio-times {
  display: flex;
  justify-content: space-between;
  font-size: 0.7em;
  opacity: 0.6;
  margin-top: 0.2em;
}

.radio-idle {
  font-size: 0.85em;
  opacity: 0.7;
  display: flex;
  align-items: center;
}

.radio-controls {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.radio-btn { min-width: 2.2em; }

.radio-play { font-size: 1.1em; }

.radio-volume {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex: 1 1 auto;
  min-width: 0;
}

.radio-slider {
  flex: 1 1 auto;
  min-width: 0;
  accent-color: #bbb;
}

.radio-foot {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  font-size: 0.75em;
  opacity: 0.7;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  padding-top: 0.4em;
}

.radio-group,
.radio-codec {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 40%;
}

.radio-link {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--bng-rgba-190-190-190-0-6);
  cursor: pointer;
  text-decoration: underline;
  font: inherit;
  padding: 0;
}
</style>
