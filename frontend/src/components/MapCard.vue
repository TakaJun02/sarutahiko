<script setup>
import { computed } from 'vue'

import campusMapImage from '../assets/honjo-campus-map.png'
import {
  CAMPUS_EDGES,
  CAMPUS_MAP_IMAGE_SIZE,
  CAMPUS_MAP_VIEWBOX,
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
  selectedNodeId: {
    type: String,
    default: '',
  },
  cancelled: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['origin-selected', 'origin-cancelled'])

const isAskOrigin = computed(() => props.payload.mode === 'ask_origin')
const isRoute = computed(() => props.payload.mode === 'route')
const active = computed(() => isAskOrigin.value && props.interactive)
const pathNodes = computed(() => new Set(props.payload.path?.nodes || []))
const pathEdges = computed(() => new Set(props.payload.path?.edges || []))
const destinationNode = computed(() => props.payload.destination?.node || null)
const destinationLabel = computed(() => destinationBadge(props.payload.destination))
const selectedNode = computed(() => (
  CAMPUS_NODES.find((node) => node.id === props.selectedNodeId) || null
))
const groundNotes = computed(() => new Map(
  CAMPUS_NODES
    .filter((node) => pathNodes.value.has(node.id) && node.groundFloor && node.groundFloor !== 1)
    .map((node) => [node.id, `${node.groundFloor}階が地上`]),
))
const cardTitle = computed(() => {
  if (isAskOrigin.value) {
    return 'いま、どこにいますか？'
  }
  if (props.payload.mode === 'place') {
    return props.payload.destination?.label || '場所マップ'
  }
  return `${props.payload.origin?.label || '出発地'} → ${props.payload.destination?.label || '目的地'}`
})
const modeCode = computed(() => {
  if (isAskOrigin.value) return 'YOU ARE HERE'
  if (isRoute.value) return 'ROUTE GUIDE'
  return 'PLACE GUIDE'
})
const stateLabel = computed(() => {
  if (!isAskOrigin.value) {
    return isRoute.value ? '経路案内' : '場所'
  }
  if (active.value) return '選択受付中'
  if (props.selectedNodeId) return '選択済み'
  if (props.cancelled) return '受付終了'
  return '履歴'
})
const inactiveNote = computed(() => {
  if (props.selectedNodeId && selectedNode.value) {
    return `${selectedNode.value.selectionLabel}を現在地として選択しました`
  }
  if (props.cancelled) {
    return '現在地を選ばずに受付を終了しました'
  }
  return '履歴の現在地カードです（再選択はできません）'
})

function nodeClass(node) {
  return {
    'map-node--active': pathNodes.value.has(node.id) || destinationNode.value === node.id,
    'map-node--destination': destinationNode.value === node.id,
    'map-node--interactive': active.value,
    'map-node--selected': props.selectedNodeId === node.id,
  }
}

function selectNode(node) {
  if (!active.value) {
    return
  }
  emit('origin-selected', { node: node.id, label: node.selectionLabel })
}

function cancelSelection() {
  if (active.value) {
    emit('origin-cancelled')
  }
}

function nodeAriaLabel(node) {
  if (isAskOrigin.value) {
    const selected = props.selectedNodeId === node.id ? '、選択済み' : ''
    return `現在地を${node.selectionLabel}にする${selected}`
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
    :class="{
      'map-card--ask-active': active,
      'map-card--inactive': isAskOrigin && !active,
      'map-card--route': isRoute,
      'map-card--place': payload.mode === 'place',
    }"
    :aria-label="cardTitle"
  >
    <div class="map-card__signal" aria-hidden="true"></div>

    <header class="map-card__header">
      <div class="map-card__heading-lockup">
        <span class="map-card__icon" aria-hidden="true">
          <svg v-if="isAskOrigin || payload.mode === 'place'" viewBox="0 0 24 24" fill="none">
            <path d="M12 21s6-5.35 6-11a6 6 0 1 0-12 0c0 5.65 6 11 6 11z" stroke="currentColor" stroke-width="1.65" />
            <circle cx="12" cy="10" r="2.15" fill="currentColor" />
          </svg>
          <svg v-else viewBox="0 0 24 24" fill="none">
            <circle cx="5" cy="18" r="2" stroke="currentColor" stroke-width="1.65" />
            <circle cx="19" cy="6" r="2" stroke="currentColor" stroke-width="1.65" />
            <path d="M7 18h3.2a2.8 2.8 0 0 0 2.8-2.8V8.8A2.8 2.8 0 0 1 15.8 6H17" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" />
          </svg>
        </span>
        <div class="map-card__heading-copy">
          <p class="map-card__eyebrow">HONJO CAMPUS / {{ modeCode }}</p>
          <h3 class="map-card__title">{{ cardTitle }}</h3>
        </div>
      </div>
      <span class="map-card__mode" :class="{ 'map-card__mode--live': active }">
        <span aria-hidden="true"></span>{{ stateLabel }}
      </span>
    </header>

    <div v-if="isAskOrigin" class="map-card__instruction">
      <p>{{ payload.prompt || 'いまいる場所をマップでタップしてください' }}</p>
      <span v-if="active">地図か施設名ボタンから、1か所選んでください</span>
      <span v-else>{{ inactiveNote }}</span>
    </div>

    <div v-else class="map-card__summary" :aria-label="isRoute ? '経路の概要' : '場所の概要'">
      <template v-if="isRoute">
        <div>
          <span>FROM</span>
          <strong>{{ payload.origin?.label || '出発地' }}</strong>
        </div>
        <svg aria-hidden="true" viewBox="0 0 52 12" preserveAspectRatio="none">
          <path d="M1 6h47M44 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        <div>
          <span>TO</span>
          <strong>{{ payload.destination?.label || '目的地' }}</strong>
          <small v-if="destinationLabel">{{ destinationLabel }}</small>
        </div>
      </template>
      <template v-else>
        <div>
          <span>DESTINATION</span>
          <strong>{{ payload.destination?.label || '目的地' }}</strong>
          <small v-if="destinationLabel">{{ destinationLabel }}</small>
        </div>
      </template>
    </div>

    <div class="map-card__canvas">
      <svg
        class="map-card__svg"
        :viewBox="CAMPUS_MAP_VIEWBOX"
        :role="isAskOrigin ? 'group' : 'img'"
        :aria-label="`${cardTitle}の本荘キャンパスマップ`"
      >
        <image
          class="map-card__image"
          :href="campusMapImage"
          aria-hidden="true"
          x="0"
          y="0"
          :width="CAMPUS_MAP_IMAGE_SIZE.width"
          :height="CAMPUS_MAP_IMAGE_SIZE.height"
          preserveAspectRatio="none"
        />
        <rect
          class="map-card__paper-edge"
          x="90.75"
          y="40.75"
          width="579.5"
          height="458.5"
          rx="3"
          aria-hidden="true"
        />

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
            <rect x="-47" y="-14" width="94" height="28" rx="14" />
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
          :aria-pressed="isAskOrigin ? String(selectedNodeId === node.id) : undefined"
          @click="selectNode(node)"
          @keydown="onNodeKeydown($event, node)"
        >
          <circle class="map-node__target" cy="-12" r="45" />
          <g class="map-node__pin" transform="translate(0 -20)">
            <path
              class="map-node__shadow"
              d="M0 20C-4 13-18 1-18-10a18 18 0 1 1 36 0c0 11-14 23-18 30z"
            />
            <path
              class="map-node__surface"
              d="M0 20C-4 13-18 1-18-10a18 18 0 1 1 36 0c0 11-14 23-18 30z"
            />
            <circle class="map-node__core" cy="-10" r="11" />
            <text class="map-node__code" text-anchor="middle" dominant-baseline="central" y="-10">
              {{ node.displayCode }}
            </text>
          </g>

          <g v-if="selectedNodeId === node.id" class="map-selected-marker" transform="translate(18 -39)">
            <circle r="12" />
            <path d="M-4 0l3 3 6-7" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" />
          </g>
          <g
            v-if="groundNotes.has(node.id)"
            class="map-floor-badge"
            transform="translate(40 -27)"
          >
            <rect x="-42" y="-14" width="84" height="28" rx="14" />
            <text text-anchor="middle" dominant-baseline="central">{{ groundNotes.get(node.id) }}</text>
          </g>
          <g
            v-if="destinationNode === node.id && destinationLabel"
            class="map-destination-badge"
            transform="translate(0 34)"
          >
            <rect x="-52" y="-14" width="104" height="28" rx="14" />
            <text text-anchor="middle" dominant-baseline="central">{{ destinationLabel }}</text>
          </g>
        </g>
      </svg>
    </div>

    <p class="map-card__schematic-note">
      <svg aria-hidden="true" viewBox="0 0 16 16" fill="none">
        <circle cx="8" cy="8" r="6.25" stroke="currentColor" stroke-width="1.2" />
        <path d="M8 7.1v4M8 4.7h.01" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
      </svg>
      ※経路線は建物間のつながりを模式的に示したものです（実際の通路とは異なる場合があります）
    </p>

    <div v-if="isAskOrigin" class="map-card__selection-panel">
      <div class="map-card__selection-heading">
        <span>現在地を施設名から選ぶ</span>
        <small>{{ active ? '8 LOCATIONS' : stateLabel }}</small>
      </div>
      <div class="map-card__chips" aria-label="現在地をノード名から選択">
        <button
          v-for="node in CAMPUS_NODES"
          :key="`${node.id}-chip`"
          type="button"
          class="map-card__chip"
          :class="{ 'map-card__chip--selected': selectedNodeId === node.id }"
          :disabled="!active"
          :aria-label="`現在地を${node.selectionLabel}にする`"
          :aria-pressed="selectedNodeId === node.id"
          @click="selectNode(node)"
        >
          <span class="map-card__chip-marker" aria-hidden="true">
            <svg v-if="selectedNodeId === node.id" viewBox="0 0 16 16" fill="none">
              <path d="M3.5 8.2l2.8 2.7 6.2-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            <span v-else></span>
          </span>
          <span>{{ node.selectionLabel }}</span>
        </button>
      </div>
      <button
        v-if="active"
        type="button"
        class="map-card__cancel"
        @click="cancelSelection"
      >
        現在地を選ばずに続ける
      </button>
      <p v-else class="map-card__inactive-note" role="status">{{ inactiveNote }}</p>
    </div>

    <details v-if="isRoute && payload.steps?.length" class="map-card__steps" open>
      <summary>
        <span class="map-card__steps-label">
          <small>STEP BY STEP</small>
          <strong>経路ステップ</strong>
        </span>
        <span class="map-card__steps-count">{{ payload.steps.length }}</span>
        <svg aria-hidden="true" viewBox="0 0 24 24">
          <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" />
        </svg>
      </summary>
      <ol class="map-card__step-list">
        <li v-for="(step, index) in payload.steps" :key="`${index}-${step}`">
          <span aria-hidden="true">{{ String(index + 1).padStart(2, '0') }}</span>
          <p>{{ step }}</p>
        </li>
      </ol>
    </details>
  </section>
</template>

<style scoped>
.map-card {
  --map-signal: #ff7657;
  --map-signal-soft: #ffad98;
  --map-paper: #f2f1ec;
  position: relative;
  width: 100%;
  max-width: 100%;
  overflow: hidden;
  border: 1px solid rgba(244, 243, 237, 0.14);
  border-radius: 1.5rem;
  background:
    radial-gradient(circle at 92% 0%, rgba(255, 118, 87, 0.07), transparent 28%),
    linear-gradient(150deg, rgba(29, 32, 29, 0.98), rgba(18, 21, 19, 0.99));
  box-shadow:
    0 24px 70px -42px rgba(0, 0, 0, 0.96),
    inset 0 1px rgba(255, 255, 255, 0.035);
  color: var(--map-paper);
  isolation: isolate;
}

.map-card__signal {
  position: absolute;
  inset: 0 auto 0 0;
  z-index: 3;
  width: 3px;
  background: linear-gradient(to bottom, var(--map-signal), rgba(255, 118, 87, 0.12) 34%, transparent 76%);
  opacity: 0.72;
}

.map-card--ask-active {
  border-color: rgba(255, 118, 87, 0.34);
  box-shadow:
    0 28px 76px -42px rgba(0, 0, 0, 0.98),
    0 0 0 1px rgba(255, 118, 87, 0.06),
    0 0 34px -22px rgba(255, 118, 87, 0.74),
    inset 0 1px rgba(255, 255, 255, 0.045);
}

.map-card--ask-active .map-card__signal {
  width: 4px;
  opacity: 1;
  animation: map-signal-breathe 1.8s ease-in-out infinite alternate;
}

.map-card__header {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1rem 1rem 0.7rem 1.1rem;
}

.map-card__heading-lockup {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.7rem;
}

.map-card__icon {
  display: grid;
  width: 2.3rem;
  height: 2.3rem;
  flex: none;
  place-items: center;
  border: 1px solid rgba(255, 118, 87, 0.28);
  border-radius: 0.78rem;
  background: rgba(255, 118, 87, 0.09);
  color: var(--map-signal-soft);
  box-shadow: inset 0 1px rgba(255, 255, 255, 0.045);
}

.map-card__icon svg {
  width: 1.15rem;
  height: 1.15rem;
}

.map-card__heading-copy {
  min-width: 0;
}

.map-card__eyebrow,
.map-card__selection-heading small,
.map-card__summary span,
.map-card__steps-label small {
  font-family: "Space Grotesk", sans-serif;
  font-variant-numeric: tabular-nums;
}

.map-card__eyebrow {
  overflow: hidden;
  color: rgba(242, 241, 236, 0.4);
  font-size: 0.57rem;
  font-weight: 650;
  letter-spacing: 0.145em;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.map-card__title {
  margin-top: 0.16rem;
  overflow-wrap: anywhere;
  color: rgba(242, 241, 236, 0.96);
  font-size: clamp(0.88rem, 3.8vw, 1rem);
  font-weight: 650;
  letter-spacing: -0.018em;
  line-height: 1.45;
}

.map-card__mode {
  display: inline-flex;
  min-height: 1.8rem;
  flex: none;
  align-items: center;
  gap: 0.38rem;
  border: 1px solid rgba(244, 243, 237, 0.12);
  border-radius: 999px;
  background: rgba(244, 243, 237, 0.045);
  padding: 0.28rem 0.58rem;
  color: rgba(242, 241, 236, 0.58);
  font-size: 0.62rem;
  font-weight: 650;
  white-space: nowrap;
}

.map-card__mode > span {
  width: 0.36rem;
  height: 0.36rem;
  border-radius: 999px;
  background: currentColor;
}

.map-card__mode--live {
  border-color: rgba(255, 118, 87, 0.3);
  background: rgba(255, 118, 87, 0.09);
  color: #ffb09c;
}

.map-card__mode--live > span {
  box-shadow: 0 0 0 4px rgba(255, 118, 87, 0.1);
  animation: map-live-dot 1.5s ease-out infinite;
}

.map-card__instruction {
  margin: 0 1rem 0.85rem 1.1rem;
  border-left: 1px solid rgba(255, 118, 87, 0.38);
  padding: 0.05rem 0 0.05rem 0.75rem;
}

.map-card__instruction p {
  color: rgba(242, 241, 236, 0.82);
  font-size: 0.8rem;
  font-weight: 590;
  line-height: 1.55;
}

.map-card__instruction span {
  display: block;
  margin-top: 0.15rem;
  color: rgba(242, 241, 236, 0.43);
  font-size: 0.67rem;
  line-height: 1.55;
}

.map-card__summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 2.2rem minmax(0, 1fr);
  align-items: center;
  gap: 0.55rem;
  margin: 0 1rem 0.75rem 1.1rem;
  border: 1px solid rgba(244, 243, 237, 0.08);
  border-radius: 0.9rem;
  background: rgba(8, 10, 9, 0.2);
  padding: 0.65rem 0.75rem;
}

.map-card--place .map-card__summary {
  grid-template-columns: minmax(0, 1fr);
}

.map-card__summary div {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.18rem 0.45rem;
}

.map-card__summary span {
  width: 100%;
  color: rgba(242, 241, 236, 0.34);
  font-size: 0.52rem;
  font-weight: 680;
  letter-spacing: 0.14em;
}

.map-card__summary strong {
  overflow: hidden;
  color: rgba(242, 241, 236, 0.84);
  font-size: 0.72rem;
  font-weight: 610;
  line-height: 1.4;
  text-overflow: ellipsis;
}

.map-card__summary small {
  border-radius: 999px;
  background: var(--map-signal);
  padding: 0.12rem 0.35rem;
  color: #27120c;
  font-size: 0.55rem;
  font-weight: 780;
}

.map-card__summary > svg {
  width: 100%;
  height: 0.75rem;
  color: rgba(255, 118, 87, 0.58);
}

.map-card__canvas {
  position: relative;
  width: calc(100% - 1.25rem);
  overflow: hidden;
  margin: 0 0.625rem;
  border: 1px solid rgba(244, 243, 237, 0.13);
  border-radius: 1.1rem;
  background:
    linear-gradient(145deg, rgba(244, 243, 237, 0.1), rgba(244, 243, 237, 0.025)),
    #111411;
  box-shadow:
    0 17px 36px -27px rgba(0, 0, 0, 0.9),
    inset 0 1px rgba(255, 255, 255, 0.075);
  padding: 0.38rem;
}

.map-card__svg {
  position: relative;
  display: block;
  width: 100%;
  height: auto;
  max-width: 100%;
  overflow: hidden;
  border-radius: 0.75rem;
  background: #f8f8f5;
  box-shadow:
    0 8px 20px -13px rgba(0, 0, 0, 0.78),
    0 0 0 1px rgba(20, 23, 20, 0.22);
}

.map-card__image {
  pointer-events: none;
}

.map-card__paper-edge {
  fill: none;
  stroke: rgba(30, 34, 30, 0.24);
  stroke-width: 1.5;
  vector-effect: non-scaling-stroke;
  pointer-events: none;
}

.map-edge {
  fill: none;
  stroke: rgba(24, 28, 24, 0.28);
  stroke-dasharray: 2 5;
  stroke-linecap: round;
  stroke-width: 1.8;
  vector-effect: non-scaling-stroke;
}

.map-edge--active {
  stroke: var(--map-signal);
  stroke-dasharray: 7 5;
  stroke-width: 4;
  filter:
    drop-shadow(0 1px 0 rgba(40, 17, 11, 0.88))
    drop-shadow(0 0 3px rgba(255, 118, 87, 0.62));
  animation: map-route-flow 1.2s linear infinite;
}

.map-node {
  color: #f7f4ed;
  outline: none;
}

.map-node__target {
  fill: transparent;
  pointer-events: all;
}

.map-node__shadow {
  fill: rgba(0, 0, 0, 0.42);
  transform: translate(2px, 3px);
}

.map-node__surface {
  fill: #252925;
  stroke: rgba(255, 255, 252, 0.96);
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
  transition: fill 180ms ease, stroke 180ms ease, transform 180ms cubic-bezier(0.16, 1, 0.3, 1);
}

.map-node__core {
  fill: #f7f4ed;
  stroke: rgba(20, 23, 20, 0.22);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
  transition: fill 180ms ease;
}

.map-node__code {
  fill: #222622;
  font-family: "Space Grotesk", sans-serif;
  font-size: 9px;
  font-weight: 780;
  letter-spacing: -0.025em;
  pointer-events: none;
}

.map-node--active .map-node__surface,
.map-node--selected .map-node__surface {
  fill: var(--map-signal);
  stroke: #fff7f2;
  stroke-width: 2.4;
}

.map-node--active .map-node__core,
.map-node--selected .map-node__core {
  fill: #462118;
  stroke: rgba(255, 255, 255, 0.3);
}

.map-node--active .map-node__code,
.map-node--selected .map-node__code {
  fill: #fff7f2;
}

.map-node--interactive {
  cursor: pointer;
}

.map-node--interactive:hover .map-node__surface,
.map-node--interactive:focus-visible .map-node__surface {
  fill: #343a34;
  stroke: var(--map-signal);
  transform: translateY(-2px);
}

.map-node--interactive:hover .map-node__core,
.map-node--interactive:focus-visible .map-node__core {
  fill: #ffe0d8;
}

.map-node--interactive:focus-visible .map-node__target {
  fill: rgba(255, 118, 87, 0.12);
  stroke: var(--map-signal-soft);
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
}

.map-floor-badge rect,
.map-edge-badge rect {
  fill: #2a2e2a;
  stroke: rgba(244, 243, 237, 0.2);
  stroke-width: 0.7;
}

.map-floor-badge text,
.map-edge-badge text {
  fill: rgba(242, 241, 236, 0.82);
  font-family: "Space Grotesk", sans-serif;
  font-size: 9px;
  font-weight: 680;
}

.map-destination-badge rect {
  fill: var(--map-signal);
  filter: drop-shadow(0 2px 3px rgba(0, 0, 0, 0.3));
}

.map-destination-badge text {
  fill: #29120c;
  font-family: "Space Grotesk", sans-serif;
  font-size: 9px;
  font-weight: 780;
}

.map-selected-marker circle {
  fill: var(--map-paper);
  stroke: var(--map-signal);
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
}

.map-selected-marker path {
  color: #6f2d1d;
}

.map-card__schematic-note {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  margin: 0.55rem 1rem 0.8rem 1.1rem;
  color: rgba(242, 241, 236, 0.4);
  font-size: 0.625rem;
  line-height: 1.5;
}

.map-card__schematic-note svg {
  width: 0.85rem;
  height: 0.85rem;
  flex: none;
}

.map-card__selection-panel {
  border-top: 1px solid rgba(244, 243, 237, 0.085);
  background: rgba(8, 10, 9, 0.16);
  padding: 0.8rem 1rem 0.75rem 1.1rem;
}

.map-card__selection-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.6rem;
  color: rgba(242, 241, 236, 0.72);
  font-size: 0.72rem;
  font-weight: 620;
}

.map-card__selection-heading small {
  color: rgba(242, 241, 236, 0.34);
  font-size: 0.52rem;
  font-weight: 670;
  letter-spacing: 0.13em;
}

.map-card__chips {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.42rem;
}

.map-card__chip {
  display: flex;
  min-width: 0;
  min-height: 44px;
  align-items: center;
  gap: 0.5rem;
  border: 1px solid rgba(244, 243, 237, 0.11);
  border-radius: 0.75rem;
  background: rgba(244, 243, 237, 0.035);
  padding: 0.42rem 0.58rem;
  color: rgba(242, 241, 236, 0.72);
  font-size: 0.67rem;
  line-height: 1.35;
  text-align: left;
  transition:
    transform 160ms cubic-bezier(0.16, 1, 0.3, 1),
    background 160ms ease,
    border-color 160ms ease,
    color 160ms ease;
}

.map-card__chip-marker {
  display: grid;
  width: 1.15rem;
  height: 1.15rem;
  flex: none;
  place-items: center;
  border: 1px solid rgba(244, 243, 237, 0.19);
  border-radius: 999px;
}

.map-card__chip-marker > span {
  width: 0.26rem;
  height: 0.26rem;
  border-radius: 999px;
  background: rgba(242, 241, 236, 0.34);
}

.map-card__chip-marker svg {
  width: 0.8rem;
  height: 0.8rem;
}

.map-card__chip:hover:not(:disabled),
.map-card__chip:focus-visible:not(:disabled) {
  border-color: rgba(255, 118, 87, 0.48);
  background: rgba(255, 118, 87, 0.09);
  color: #fff4ef;
  transform: translateY(-1px);
}

.map-card__chip--selected {
  border-color: rgba(255, 118, 87, 0.52);
  background: rgba(255, 118, 87, 0.12);
  color: #fff4ef;
}

.map-card__chip--selected .map-card__chip-marker {
  border-color: var(--map-signal);
  background: var(--map-signal);
  color: #2b120c;
}

.map-card__chip:disabled {
  cursor: default;
  opacity: 0.46;
}

.map-card__chip--selected:disabled {
  opacity: 0.9;
}

.map-card__cancel {
  display: flex;
  min-height: 44px;
  width: 100%;
  align-items: center;
  justify-content: center;
  margin-top: 0.55rem;
  border-radius: 0.7rem;
  color: rgba(242, 241, 236, 0.46);
  font-size: 0.69rem;
  text-decoration: underline;
  text-decoration-color: rgba(242, 241, 236, 0.18);
  text-underline-offset: 0.22rem;
  transition: background 150ms ease, color 150ms ease;
}

.map-card__cancel:hover,
.map-card__cancel:focus-visible {
  background: rgba(244, 243, 237, 0.04);
  color: rgba(242, 241, 236, 0.82);
}

.map-card__inactive-note {
  display: flex;
  min-height: 2.5rem;
  align-items: center;
  margin-top: 0.55rem;
  border-radius: 0.7rem;
  background: rgba(244, 243, 237, 0.025);
  padding: 0.45rem 0.7rem;
  color: rgba(242, 241, 236, 0.4);
  font-size: 0.66rem;
  line-height: 1.5;
}

.map-card__steps {
  border-top: 1px solid rgba(244, 243, 237, 0.085);
  background: rgba(8, 10, 9, 0.16);
  padding: 0.35rem 0.9rem 0.8rem 1rem;
}

.map-card__steps summary {
  display: flex;
  min-height: 44px;
  width: 100%;
  align-items: center;
  gap: 0.65rem;
  border-radius: 0.7rem;
  padding: 0.35rem 0.25rem;
  color: rgba(242, 241, 236, 0.62);
  cursor: pointer;
  list-style: none;
}

.map-card__steps summary::-webkit-details-marker {
  display: none;
}

.map-card__steps-label {
  display: grid;
  flex: 1;
  gap: 0.05rem;
}

.map-card__steps-label small {
  color: rgba(242, 241, 236, 0.31);
  font-size: 0.5rem;
  font-weight: 670;
  letter-spacing: 0.14em;
}

.map-card__steps-label strong {
  color: rgba(242, 241, 236, 0.7);
  font-size: 0.74rem;
  font-weight: 630;
}

.map-card__steps-count {
  display: grid;
  width: 1.5rem;
  height: 1.5rem;
  place-items: center;
  border: 1px solid rgba(255, 118, 87, 0.25);
  border-radius: 999px;
  color: var(--map-signal-soft);
  font-family: "Space Grotesk", sans-serif;
  font-size: 0.62rem;
  font-weight: 700;
}

.map-card__steps summary > svg {
  width: 1rem;
  height: 1rem;
  transition: transform 180ms ease;
}

.map-card__steps:not([open]) summary > svg {
  transform: rotate(-90deg);
}

.map-card__step-list {
  position: relative;
  display: grid;
  gap: 0;
  padding: 0.25rem 0.25rem 0.1rem;
}

.map-card__step-list li {
  position: relative;
  display: grid;
  grid-template-columns: 1.65rem minmax(0, 1fr);
  gap: 0.6rem;
  align-items: start;
  padding-bottom: 0.72rem;
}

.map-card__step-list li:not(:last-child)::after {
  position: absolute;
  top: 1.45rem;
  bottom: 0;
  left: 0.79rem;
  width: 1px;
  background: linear-gradient(to bottom, rgba(255, 118, 87, 0.3), rgba(244, 243, 237, 0.06));
  content: "";
}

.map-card__step-list li > span {
  display: grid;
  width: 1.65rem;
  height: 1.65rem;
  place-items: center;
  border: 1px solid rgba(255, 118, 87, 0.3);
  border-radius: 0.55rem;
  background: #24231f;
  color: var(--map-signal-soft);
  font-family: "Space Grotesk", sans-serif;
  font-size: 0.56rem;
  font-weight: 700;
}

.map-card__step-list p {
  padding-top: 0.1rem;
  color: rgba(242, 241, 236, 0.7);
  font-size: 0.76rem;
  line-height: 1.65;
}

.map-card--inactive .map-card__canvas,
.map-card--inactive .map-card__instruction {
  opacity: 0.67;
}

@keyframes map-route-flow {
  to { stroke-dashoffset: -18; }
}

@keyframes map-signal-breathe {
  from { opacity: 0.62; }
  to { opacity: 1; }
}

@keyframes map-live-dot {
  0% { box-shadow: 0 0 0 0 rgba(255, 118, 87, 0.28); }
  70%, 100% { box-shadow: 0 0 0 5px rgba(255, 118, 87, 0); }
}

@media (min-width: 560px) {
  .map-card__chips {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 374px) {
  .map-card__header {
    flex-direction: column;
  }

  .map-card__mode {
    margin-left: 3rem;
  }

  .map-card__summary {
    gap: 0.35rem;
    padding-inline: 0.55rem;
  }

  .map-card__chips {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (prefers-reduced-motion: reduce) {
  .map-card--ask-active .map-card__signal,
  .map-card__mode--live > span,
  .map-edge--active {
    animation: none !important;
  }

  .map-node__surface,
  .map-card__chip,
  .map-card__cancel,
  .map-card__steps summary > svg {
    transition: none !important;
  }

  .map-card__chip:hover:not(:disabled),
  .map-card__chip:focus-visible:not(:disabled),
  .map-node--interactive:hover .map-node__surface,
  .map-node--interactive:focus-visible .map-node__surface {
    transform: none;
  }
}
</style>
