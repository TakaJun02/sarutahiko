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
  viewBox: {
    type: String,
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
  ariaLabel: {
    type: String,
    required: true,
  },
})

const emit = defineEmits(['origin-selected'])

const isAskOrigin = computed(() => props.payload.mode === 'ask_origin')
const pathNodes = computed(() => new Set(props.payload.path?.nodes || []))
const pathEdges = computed(() => new Set(props.payload.path?.edges || []))
const destinationNode = computed(() => props.payload.destination?.node || null)
const destinationLabel = computed(() => destinationBadge(props.payload.destination))
const groundNotes = computed(() => new Map(
  CAMPUS_NODES
    .filter((node) => pathNodes.value.has(node.id) && node.groundFloor && node.groundFloor !== 1)
    .map((node) => [node.id, `${node.groundFloor}階が地上`]),
))

function nodeClass(node) {
  return {
    'campus-map-node--active': pathNodes.value.has(node.id) || destinationNode.value === node.id,
    'campus-map-node--destination': destinationNode.value === node.id,
    'campus-map-node--interactive': isAskOrigin.value && props.interactive,
    'campus-map-node--selected': props.selectedNodeId === node.id,
  }
}

function nodeAriaLabel(node) {
  if (!isAskOrigin.value) {
    return node.label
  }
  const selected = props.selectedNodeId === node.id ? '、選択済み' : ''
  return `現在地を${node.selectionLabel}にする${selected}`
}

function selectNode(node) {
  if (!isAskOrigin.value || !props.interactive) {
    return
  }
  emit('origin-selected', { node: node.id, label: node.selectionLabel })
}

function onNodeKeydown(event, node) {
  if (event.key !== 'Enter' && event.key !== ' ') {
    return
  }
  event.preventDefault()
  selectNode(node)
}
</script>

<template>
  <svg
    class="campus-map-graphic"
    :viewBox="viewBox"
    preserveAspectRatio="xMidYMid meet"
    :role="isAskOrigin ? 'group' : 'img'"
    :aria-label="ariaLabel"
  >
    <rect class="campus-map-ground" x="0" y="0" width="671" height="720" />

    <g class="campus-map-roads" aria-hidden="true">
      <path
        class="campus-map-road campus-map-road--edge"
        d="M104 248V126C104 91 126 75 166 65C252 43 340 46 425 80H579C634 80 663 111 663 166V535C663 608 628 646 559 649H158C119 647 100 625 100 588V403"
      />
      <path
        class="campus-map-road campus-map-road--lane"
        d="M104 248V126C104 91 126 75 166 65C252 43 340 46 425 80H579C634 80 663 111 663 166V535C663 608 628 646 559 649H158C119 647 100 625 100 588V403"
      />
      <path class="campus-map-road campus-map-road--edge" d="M327 720V491M327 428V348" />
      <path class="campus-map-road campus-map-road--lane" d="M327 720V491M327 428V348" />
      <circle class="campus-map-rotary campus-map-rotary--edge" cx="327" cy="460" r="31" />
      <circle class="campus-map-rotary campus-map-rotary--lane" cx="327" cy="460" r="25" />
      <path class="campus-map-road campus-map-road--edge" d="M296 456C263 454 244 440 224 413M358 456C391 454 407 441 421 415" />
      <path class="campus-map-road campus-map-road--lane" d="M296 456C263 454 244 440 224 413M358 456C391 454 407 441 421 415" />
    </g>

    <g class="campus-map-parking" aria-hidden="true">
      <rect x="8" y="308" width="76" height="338" rx="4" />
      <path d="M20 324v302M72 324v302M28 327h35M28 345h35M28 363h35M28 381h35M28 399h35M28 417h35M28 435h35M28 453h35M28 471h35M28 489h35M28 507h35M28 525h35M28 543h35M28 561h35M28 579h35M28 597h35M28 615h35" />
      <rect x="492" y="301" width="161" height="151" rx="4" />
      <path d="M510 318h124M510 346h124M510 374h124M510 402h124M510 430h124M521 310v132M557 310v132M593 310v132M629 310v132" />
      <g class="campus-map-parking-sign">
        <rect x="31" y="404" width="48" height="66" rx="5" />
        <text x="55" y="438" text-anchor="middle">P</text>
        <rect x="525" y="305" width="62" height="54" rx="5" />
        <text x="556" y="338" text-anchor="middle">P</text>
      </g>
    </g>

    <g class="campus-map-buildings" aria-hidden="true">
      <path class="campus-map-building" d="M214 72V42H241V49H303V57H318V101H217V91H207V72Z" />
      <path class="campus-map-building campus-map-building--quiet" d="M132 91H168V101H177V215H165V224H132Z" />
      <path class="campus-map-building campus-map-building--minor" d="M132 226H167V264H132Z" />
      <path class="campus-map-building" d="M204 120H246V128H255V242H247V250H211V244H195V128H204Z" />
      <path class="campus-map-building" d="M291 120H328V128H338V241H329V249H291V242H282V129H291Z" />
      <path class="campus-map-building campus-map-building--quiet" d="M352 118H412V127H419V217H359V198H352Z" />
      <path class="campus-map-building campus-map-building--quiet" d="M361 247H386V269H379V370H361Z" />
      <circle class="campus-map-building campus-map-building--round" cx="329" cy="319" r="28" />
      <path class="campus-map-building campus-map-building--common" d="M169 370L195 337C232 367 272 385 315 388C345 390 371 379 390 357L425 409L388 427L366 414C340 427 311 431 281 426C241 420 204 401 169 370Z" />
      <path class="campus-map-building campus-map-building--minor" d="M362 389H404V427H362Z" />
      <rect class="campus-map-zone" x="455" y="91" width="188" height="126" rx="13" />
    </g>

    <g class="campus-map-landmark-labels" aria-hidden="true">
      <text x="277" y="112" text-anchor="middle">大学院棟</text>
      <text x="151" y="192" text-anchor="middle">特別実験棟</text>
      <text x="224" y="213" text-anchor="middle">学部棟Ⅰ</text>
      <text x="310" y="213" text-anchor="middle">学部棟Ⅱ</text>
      <text x="385" y="198" text-anchor="middle">体育館</text>
      <text x="402" y="285" text-anchor="middle">メディア</text>
      <text x="402" y="305" text-anchor="middle">交流棟</text>
      <text x="329" y="325" text-anchor="middle">食堂</text>
      <text x="268" y="414" text-anchor="middle">共通施設棟</text>
      <text x="545" y="194" text-anchor="middle">南側多目的広場</text>
      <text class="campus-map-minor-label" x="151" y="248" text-anchor="middle">創造工房</text>
      <text class="campus-map-minor-label" x="383" y="414" text-anchor="middle">AVホール</text>
      <text class="campus-map-minor-label" x="351" y="486">ロータリー</text>
    </g>

    <g class="campus-map-edges" aria-hidden="true">
      <path
        v-for="edge in CAMPUS_EDGES"
        :key="edge.id"
        :d="edgePath(edge)"
        class="campus-map-edge"
        :class="{ 'campus-map-edge--active': pathEdges.has(edge.id) }"
      />
    </g>

    <g v-for="edge in CAMPUS_EDGES" :key="`${edge.id}-badge`" aria-hidden="true">
      <g
        v-if="pathEdges.has(edge.id) && edgeBadgeText(edge) && edge.badge"
        class="campus-map-edge-badge"
        :transform="`translate(${edge.badge[0]} ${edge.badge[1]})`"
      >
        <rect x="-56" y="-18" width="112" height="36" rx="18" />
        <text text-anchor="middle" dominant-baseline="central">{{ edgeBadgeText(edge) }}</text>
      </g>
    </g>

    <g
      v-for="node in CAMPUS_NODES"
      :key="node.id"
      class="campus-map-node"
      :class="nodeClass(node)"
      :transform="`translate(${node.x} ${node.y})`"
      :role="isAskOrigin ? 'button' : undefined"
      :tabindex="isAskOrigin && interactive ? 0 : undefined"
      :aria-label="nodeAriaLabel(node)"
      :aria-disabled="isAskOrigin ? String(!interactive) : undefined"
      :aria-pressed="isAskOrigin ? String(selectedNodeId === node.id) : undefined"
      @click.stop="selectNode(node)"
      @keydown="onNodeKeydown($event, node)"
    >
      <circle class="campus-map-node__target" cy="-12" r="45" />
      <g class="campus-map-node__pin" transform="translate(0 -20)">
        <path class="campus-map-node__shadow" d="M0 20C-4 13-18 1-18-10a18 18 0 1 1 36 0c0 11-14 23-18 30z" />
        <path class="campus-map-node__surface" d="M0 20C-4 13-18 1-18-10a18 18 0 1 1 36 0c0 11-14 23-18 30z" />
        <circle class="campus-map-node__core" cy="-10" r="11" />
        <text class="campus-map-node__code" text-anchor="middle" dominant-baseline="central" y="-10">
          {{ node.displayCode }}
        </text>
      </g>

      <g v-if="selectedNodeId === node.id" class="campus-map-selected" transform="translate(18 -39)">
        <circle r="13" />
        <path d="M-4 0l3 3 6-7" />
      </g>
      <g v-if="groundNotes.has(node.id)" class="campus-map-floor-badge" transform="translate(48 -30)">
        <rect x="-50" y="-18" width="100" height="36" rx="18" />
        <text text-anchor="middle" dominant-baseline="central">{{ groundNotes.get(node.id) }}</text>
      </g>
      <g
        v-if="destinationNode === node.id && destinationLabel"
        class="campus-map-destination-badge"
        transform="translate(0 39)"
      >
        <rect x="-62" y="-18" width="124" height="36" rx="18" />
        <text text-anchor="middle" dominant-baseline="central">{{ destinationLabel }}</text>
      </g>
    </g>
  </svg>
</template>

<style scoped>
.campus-map-graphic {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
  background: #0b1113;
  font-family: "Space Grotesk", "Noto Sans JP", "Hiragino Sans", "Yu Gothic UI", sans-serif;
}

.campus-map-ground {
  fill: #0b1113;
}

.campus-map-road {
  fill: none;
  stroke-linecap: round;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
}

.campus-map-road--edge {
  stroke: #334044;
  stroke-width: 22;
}

.campus-map-road--lane {
  stroke: #151d20;
  stroke-width: 15;
}

.campus-map-rotary {
  fill: none;
  vector-effect: non-scaling-stroke;
}

.campus-map-rotary--edge {
  stroke: #334044;
  stroke-width: 8;
}

.campus-map-rotary--lane {
  stroke: #151d20;
  stroke-width: 4;
}

.campus-map-parking rect {
  fill: #10181b;
  stroke: #364247;
  stroke-width: 1.5;
  vector-effect: non-scaling-stroke;
}

.campus-map-parking > path {
  fill: none;
  stroke: #344045;
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.campus-map-parking-sign rect {
  fill: #17252b;
  stroke: #60727a;
}

.campus-map-parking-sign text {
  fill: #98aab0;
  font-size: 23px;
  font-weight: 650;
}

.campus-map-building {
  fill: #263237;
  stroke: #728087;
  stroke-width: 1.6;
  vector-effect: non-scaling-stroke;
}

.campus-map-building--quiet {
  fill: #222e33;
}

.campus-map-building--common {
  fill: #302f33;
  stroke: #8a858b;
}

.campus-map-building--minor {
  fill: #202a2e;
  stroke: #57656b;
}

.campus-map-building--round {
  fill: #2d383b;
}

.campus-map-zone {
  fill: #111a1d;
  stroke: #617076;
  stroke-dasharray: 7 6;
  stroke-width: 1.5;
  vector-effect: non-scaling-stroke;
}

.campus-map-landmark-labels text {
  fill: #d6dedf;
  font-size: 18px;
  font-weight: 610;
  letter-spacing: -0.02em;
  paint-order: stroke;
  stroke: rgba(11, 17, 19, 0.72);
  stroke-width: 2px;
  stroke-linejoin: round;
}

.campus-map-landmark-labels .campus-map-minor-label {
  fill: #849298;
  font-size: 15px;
  font-weight: 500;
}

.campus-map-edge {
  fill: none;
  stroke: rgba(146, 162, 167, 0.25);
  stroke-dasharray: 3 7;
  stroke-linecap: round;
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
}

.campus-map-edge--active {
  stroke: #ff7657;
  stroke-dasharray: 9 6;
  stroke-width: 5;
  filter: drop-shadow(0 0 5px rgba(255, 118, 87, 0.88));
  animation: campus-route-flow 1.25s linear infinite;
}

.campus-map-node {
  color: #fff8f3;
  outline: none;
}

.campus-map-node__target {
  fill: transparent;
  pointer-events: all;
}

.campus-map-node__shadow {
  fill: rgba(0, 0, 0, 0.5);
  transform: translate(2px, 3px);
}

.campus-map-node__surface {
  fill: #1a2326;
  stroke: #c7d0d1;
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
  transition: fill 160ms ease, stroke 160ms ease, transform 160ms ease;
}

.campus-map-node__core {
  fill: #d8e0e1;
  stroke: #263135;
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.campus-map-node__code {
  fill: #172024;
  font-size: 11px;
  font-weight: 760;
  letter-spacing: -0.04em;
  pointer-events: none;
}

.campus-map-node--active .campus-map-node__surface,
.campus-map-node--selected .campus-map-node__surface {
  fill: #ff7657;
  stroke: #fff4ed;
  stroke-width: 2.5;
}

.campus-map-node--active .campus-map-node__core,
.campus-map-node--selected .campus-map-node__core {
  fill: #3b1c16;
  stroke: rgba(255, 255, 255, 0.35);
}

.campus-map-node--active .campus-map-node__code,
.campus-map-node--selected .campus-map-node__code {
  fill: #fff7f2;
}

.campus-map-node--interactive {
  cursor: pointer;
}

.campus-map-node--interactive:hover .campus-map-node__surface,
.campus-map-node--interactive:focus-visible .campus-map-node__surface {
  fill: #354348;
  stroke: #ff9b83;
  transform: translateY(-2px);
}

.campus-map-node--interactive:focus-visible .campus-map-node__target {
  fill: rgba(255, 118, 87, 0.12);
  stroke: #ff9b83;
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
}

.campus-map-floor-badge rect,
.campus-map-edge-badge rect {
  fill: #182125;
  stroke: rgba(222, 231, 232, 0.5);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.campus-map-floor-badge text,
.campus-map-edge-badge text {
  fill: #edf2f2;
  font-size: 15px;
  font-weight: 670;
}

.campus-map-destination-badge rect {
  fill: #ff7657;
  stroke: #ffd3c7;
  stroke-width: 1;
  filter: drop-shadow(0 2px 5px rgba(0, 0, 0, 0.48));
  vector-effect: non-scaling-stroke;
}

.campus-map-destination-badge text {
  fill: #28130e;
  font-size: 15px;
  font-weight: 780;
}

.campus-map-selected circle {
  fill: #eef2f1;
  stroke: #ff7657;
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
}

.campus-map-selected path {
  fill: none;
  stroke: #6f2d1d;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2.4;
  vector-effect: non-scaling-stroke;
}

@keyframes campus-route-flow {
  to { stroke-dashoffset: -30; }
}

@media (prefers-reduced-motion: reduce) {
  .campus-map-edge--active {
    animation: none !important;
  }

  .campus-map-node__surface {
    transition: none !important;
  }

  .campus-map-node--interactive:hover .campus-map-node__surface,
  .campus-map-node--interactive:focus-visible .campus-map-node__surface {
    transform: none;
  }
}
</style>
