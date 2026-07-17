<script setup>
import { computed } from 'vue'

import {
  CAMPUS_EDGES,
  CAMPUS_NODES,
  destinationBadge,
  edgeBadgeText,
  edgePath,
} from '../utils/campusMap'

const props = defineProps({
  payload: {
    type: Object,
    required: true,
  },
  interactive: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['origin-selected'])

const isAskOrigin = computed(() => props.payload.mode === 'ask_origin')
const active = computed(() => isAskOrigin.value && props.interactive)
const pathNodes = computed(() => new Set(props.payload.path?.nodes || []))
const pathEdges = computed(() => new Set(props.payload.path?.edges || []))
const destinationNode = computed(() => props.payload.destination?.node || null)
const destinationLabel = computed(() => destinationBadge(props.payload.destination))
const groundNotes = computed(() => new Map(
  CAMPUS_NODES
    .filter((node) => pathNodes.value.has(node.id) && node.groundFloor && node.groundFloor !== 1)
    .map((node) => [node.id, `${node.groundFloor}階が地上`]),
))
const cardTitle = computed(() => {
  if (props.payload.mode === 'ask_origin') {
    return '現在地を教えてください'
  }
  if (props.payload.mode === 'place') {
    return props.payload.destination?.label || '場所マップ'
  }
  return `${props.payload.origin?.label || '出発地'} → ${props.payload.destination?.label || '目的地'}`
})

function nodeClass(node) {
  return {
    'map-node--active': pathNodes.value.has(node.id) || destinationNode.value === node.id,
    'map-node--destination': destinationNode.value === node.id,
    'map-node--interactive': active.value,
  }
}

function selectNode(node) {
  if (!active.value) {
    return
  }
  emit('origin-selected', { node: node.id, label: node.selectionLabel })
}

function nodeAriaLabel(node) {
  if (isAskOrigin.value) {
    return `現在地を${node.selectionLabel}にする`
  }
  return node.label
}

function onNodeKeydown(event, node) {
  if (event.key !== 'Enter' && event.key !== ' ') {
    return
  }
  event.preventDefault()
  selectNode(node)
}

function edgeBadge(edge) {
  return edgeBadgeText(edge)
}
</script>

<template>
  <section
    class="map-card"
    :class="{ 'map-card--inactive': isAskOrigin && !active }"
    :aria-label="cardTitle"
  >
    <header class="map-card__header">
      <div>
        <p class="map-card__eyebrow">CAMPUS ROUTE</p>
        <h3 class="map-card__title">{{ cardTitle }}</h3>
      </div>
      <span v-if="payload.mode === 'route'" class="map-card__mode">経路</span>
      <span v-else-if="payload.mode === 'place'" class="map-card__mode">場所</span>
      <span v-else class="map-card__mode">現在地</span>
    </header>

    <p v-if="payload.prompt" class="map-card__prompt">{{ payload.prompt }}</p>

    <div class="map-card__canvas">
      <svg
        class="map-card__svg"
        viewBox="0 0 360 328"
        :role="isAskOrigin ? 'group' : 'img'"
        :aria-label="`${cardTitle}のキャンパス模式図（縮尺・方位なし）`"
      >
        <g class="map-edges" aria-hidden="true">
          <path
            v-for="edge in CAMPUS_EDGES"
            :key="edge.id"
            :d="edgePath(edge)"
            class="map-edge"
            :class="{ 'map-edge--active': pathEdges.has(edge.id) }"
          />
        </g>

        <g v-for="edge in CAMPUS_EDGES" :key="`${edge.id}-badge`" aria-hidden="true">
          <g
            v-if="pathEdges.has(edge.id) && edgeBadge(edge) && edge.badge"
            class="map-edge-badge"
            :transform="`translate(${edge.badge[0]} ${edge.badge[1]})`"
          >
            <rect x="-25" y="-8" width="50" height="16" rx="8" />
            <text text-anchor="middle" dominant-baseline="central">{{ edgeBadge(edge) }}</text>
          </g>
        </g>

        <g
          v-for="node in CAMPUS_NODES"
          :key="node.id"
          class="map-node"
          :class="nodeClass(node)"
          :transform="`translate(${node.x} ${node.y})`"
          :role="isAskOrigin ? 'button' : undefined"
          :tabindex="active ? 0 : undefined"
          :aria-label="nodeAriaLabel(node)"
          :aria-disabled="isAskOrigin ? String(!active) : undefined"
          @click="selectNode(node)"
          @keydown="onNodeKeydown($event, node)"
        >
          <rect class="map-node__target" x="-37" y="-29" width="74" height="58" rx="12" />
          <rect class="map-node__surface" x="-32" y="-20" width="64" height="40" rx="10" />
          <text v-if="!node.lines" class="map-node__label" text-anchor="middle" dominant-baseline="central">
            {{ node.label }}
          </text>
          <text v-else class="map-node__label" text-anchor="middle">
            <tspan x="0" y="-3">{{ node.lines[0] }}</tspan>
            <tspan x="0" y="9">{{ node.lines[1] }}</tspan>
          </text>

          <g
            v-if="groundNotes.has(node.id)"
            class="map-floor-badge"
            transform="translate(0 -27)"
          >
            <rect x="-22" y="-7" width="44" height="14" rx="7" />
            <text text-anchor="middle" dominant-baseline="central">{{ groundNotes.get(node.id) }}</text>
          </g>
          <g
            v-if="destinationNode === node.id && destinationLabel"
            class="map-destination-badge"
            transform="translate(0 28)"
          >
            <rect x="-27" y="-8" width="54" height="16" rx="8" />
            <text text-anchor="middle" dominant-baseline="central">{{ destinationLabel }}</text>
          </g>
        </g>
      </svg>
    </div>

    <p class="map-card__schematic-note">※模式図（縮尺・方位は実際と異なります）</p>

    <div v-if="isAskOrigin" class="map-card__chips" aria-label="現在地をノード名から選択">
      <button
        v-for="node in CAMPUS_NODES"
        :key="`${node.id}-chip`"
        type="button"
        class="map-card__chip"
        :disabled="!active"
        :aria-label="`現在地を${node.selectionLabel}にする`"
        @click="selectNode(node)"
      >
        {{ node.selectionLabel }}
      </button>
    </div>
    <p v-if="isAskOrigin && !active" class="map-card__inactive-note">
      この現在地カードは受付を終了しました
    </p>

    <details v-if="payload.mode === 'route' && payload.steps?.length" class="map-card__steps" open>
      <summary>
        <span>経路ステップ {{ payload.steps.length }}件</span>
        <svg aria-hidden="true" viewBox="0 0 24 24">
          <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" />
        </svg>
      </summary>
      <ol class="map-card__step-list">
        <li v-for="(step, index) in payload.steps" :key="`${index}-${step}`">
          <span aria-hidden="true">{{ index + 1 }}</span>
          <p>{{ step }}</p>
        </li>
      </ol>
    </details>
  </section>
</template>

<style scoped>
.map-card {
  width: 100%;
  max-width: 100%;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.11);
  border-radius: 1.25rem;
  background: linear-gradient(145deg, rgba(31, 32, 43, 0.88), rgba(17, 18, 27, 0.94));
  box-shadow: 0 18px 45px rgba(0, 0, 0, 0.2);
}

.map-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1rem 1rem 0.5rem;
}

.map-card__eyebrow {
  color: rgba(255, 255, 255, 0.38);
  font-size: 0.625rem;
  font-weight: 700;
  letter-spacing: 0.16em;
}

.map-card__title {
  margin-top: 0.2rem;
  color: rgba(255, 255, 255, 0.92);
  font-size: 0.95rem;
  font-weight: 650;
  line-height: 1.4;
}

.map-card__mode {
  flex: none;
  border: 1px solid rgba(255, 143, 112, 0.26);
  border-radius: 999px;
  background: rgba(255, 143, 112, 0.09);
  padding: 0.25rem 0.55rem;
  color: #ffb09a;
  font-size: 0.65rem;
  font-weight: 700;
}

.map-card__prompt {
  padding: 0 1rem 0.5rem;
  color: rgba(255, 255, 255, 0.68);
  font-size: 0.8rem;
  line-height: 1.6;
}

.map-card__canvas {
  width: 100%;
  overflow: hidden;
  padding: 0 0.45rem;
}

.map-card__svg {
  display: block;
  width: 100%;
  height: auto;
  max-width: 100%;
}

.map-card__schematic-note {
  margin: -0.1rem 1rem 0.7rem;
  color: rgba(255, 255, 255, 0.38);
  font-size: 0.625rem;
  line-height: 1.5;
}

.map-edge {
  fill: none;
  stroke: rgba(255, 255, 255, 0.13);
  stroke-linecap: round;
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
}

.map-edge--active {
  stroke: #ff8f70;
  stroke-width: 4;
  filter: drop-shadow(0 0 4px rgba(255, 143, 112, 0.45));
  animation: map-route-glow 1.8s ease-in-out infinite alternate;
}

.map-node {
  color: rgba(255, 255, 255, 0.72);
  outline: none;
}

.map-node__target {
  fill: transparent;
  pointer-events: all;
}

.map-node__surface {
  fill: #222431;
  stroke: rgba(255, 255, 255, 0.14);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.map-node__label {
  fill: currentColor;
  font-size: 7px;
  font-weight: 650;
  pointer-events: none;
}

.map-node--active .map-node__surface {
  fill: rgba(255, 143, 112, 0.16);
  stroke: #ff8f70;
  stroke-width: 2;
}

.map-node--active {
  color: #fff4ef;
}

.map-node--destination .map-node__surface {
  fill: rgba(255, 143, 112, 0.25);
}

.map-node--interactive {
  cursor: pointer;
}

.map-node--interactive:hover .map-node__surface,
.map-node--interactive:focus .map-node__surface {
  fill: rgba(255, 255, 255, 0.12);
  stroke: rgba(255, 255, 255, 0.52);
}

.map-floor-badge rect,
.map-edge-badge rect {
  fill: #30323f;
  stroke: rgba(255, 255, 255, 0.16);
  stroke-width: 0.7;
}

.map-floor-badge text,
.map-edge-badge text {
  fill: rgba(255, 255, 255, 0.72);
  font-size: 5px;
  font-weight: 700;
}

.map-destination-badge rect {
  fill: #ff8f70;
}

.map-destination-badge text {
  fill: #21130f;
  font-size: 5.5px;
  font-weight: 800;
}

.map-card__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  padding: 0 1rem 0.85rem;
}

.map-card__chip {
  min-height: 44px;
  flex: none;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.045);
  padding: 0.45rem 0.75rem;
  color: rgba(255, 255, 255, 0.76);
  font-size: 0.72rem;
  transition: background 160ms ease, border-color 160ms ease, color 160ms ease;
}

.map-card__chip:hover:not(:disabled),
.map-card__chip:focus-visible:not(:disabled) {
  border-color: rgba(255, 143, 112, 0.52);
  background: rgba(255, 143, 112, 0.12);
  color: white;
  outline: none;
}

.map-card__chip:disabled {
  cursor: not-allowed;
  opacity: 0.38;
}

.map-card__inactive-note {
  padding: 0 1rem 0.85rem;
  color: rgba(255, 255, 255, 0.38);
  font-size: 0.7rem;
}

.map-card__steps {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding: 0.35rem 0.75rem 0.75rem;
}

.map-card__steps summary {
  display: flex;
  min-height: 44px;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.35rem 0.25rem;
  color: rgba(255, 255, 255, 0.58);
  font-size: 0.75rem;
  font-weight: 650;
  cursor: pointer;
  list-style: none;
}

.map-card__steps summary::-webkit-details-marker {
  display: none;
}

.map-card__steps summary svg {
  width: 1rem;
  height: 1rem;
  transition: transform 180ms ease;
}

.map-card__step-list {
  display: grid;
  gap: 0.55rem;
  padding: 0.25rem 0.25rem 0.2rem;
}

.map-card__step-list li {
  display: grid;
  grid-template-columns: 1.35rem minmax(0, 1fr);
  gap: 0.55rem;
  align-items: start;
}

.map-card__step-list li > span {
  display: grid;
  width: 1.35rem;
  height: 1.35rem;
  place-items: center;
  border: 1px solid rgba(255, 143, 112, 0.28);
  border-radius: 999px;
  background: rgba(255, 143, 112, 0.09);
  color: #ffad96;
  font-size: 0.62rem;
  font-weight: 750;
}

.map-card__step-list p {
  color: rgba(255, 255, 255, 0.7);
  font-size: 0.78rem;
  line-height: 1.65;
}

.map-card--inactive .map-card__canvas {
  opacity: 0.62;
}

@keyframes map-route-glow {
  from { opacity: 0.72; }
  to { opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .map-edge--active {
    animation: none !important;
  }

  .map-card__chip,
  .map-card__steps summary svg {
    animation: none !important;
    transition: none;
  }
}
</style>
