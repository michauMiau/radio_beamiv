<template>
  <svg
    class="transport-ico"
    :class="`transport-ico--${name}`"
    viewBox="0 0 24 24"
    aria-hidden="true"
    focusable="false"
  >
    <path v-if="name === 'play'" :d="PATHS.play" />
    <path v-else-if="name === 'pause'" :d="PATHS.pause" />
    <path v-else-if="name === 'previous'" :d="PATHS.previous" />
    <path v-else-if="name === 'next'" :d="PATHS.next" />
    <path v-else-if="name === 'volumeUp'" :d="PATHS.volumeUp" />
    <path v-else-if="name === 'volumeOff'" :d="PATHS.volumeOff" />
    <path v-else-if="name === 'back'" :d="PATHS.back" />
    <circle v-else cx="12" cy="12" r="3" />
  </svg>
</template>

<script setup>
// Inline SVG rather than the game's icon font: a mod cannot enumerate the
// bngIcons registry, and a missing entry renders as an empty button.
const props = defineProps({
  name: { type: String, default: "dot" },
})

// Material Design icon paths, which is what the game's own set is built from.
const PATHS = {
  play: "M8 5v14l11-7z",
  pause: "M6 5h4v14H6zM14 5h4v14h-4z",
  previous: "M6 6h2v12H6zM18 6v12l-9-6z",
  next: "M16 6h2v12h-2zM6 6l9 6-9 6z",
  volumeUp:
    "M4 9v6h4l5 5V4L8 9H4zm12.5 3a4.5 4.5 0 0 0-2.5-4v8a4.5 4.5 0 0 0 2.5-4z",
  volumeOff:
    "M4 9v6h4l5 5V4L8 9H4zm15.5 3 2.2-2.2-1.4-1.4-2.2 2.2-2.2-2.2-1.4 1.4 2.2 2.2-2.2 2.2 1.4 1.4 2.2-2.2 2.2 2.2 1.4-1.4-2.2-2.2z",
  back: "M20 11H7.8l5.6-5.6L12 4l-8 8 8 8 1.4-1.4L7.8 13H20v-2z",
}
</script>

<style scoped>
.transport-ico {
  width: 1.25em;
  height: 1.25em;
  display: block;
  fill: currentColor;
  flex: 0 0 auto;
}

.transport-ico--play,
.transport-ico--pause {
  width: 1.4em;
  height: 1.4em;
}
</style>
