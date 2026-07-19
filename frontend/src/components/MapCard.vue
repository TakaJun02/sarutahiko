<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue'

import campusMapImage from '../assets/honjo-campus-map.png'
import {
  CAMPUS_NODES,
  destinationBadge,
  fitMapViewBox,
  fullMapViewBox,
} from '../utils/campusMap'
import {
  constrainMapTransform,
  isMapDoubleTap,
  pinchMapAt,
  zoomMapAt,
} from '../utils/mapViewport'
import CampusMapGraphic from './CampusMapGraphic.vue'

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

const canvasRef = ref(null)
const expandButtonRef = ref(null)
const viewerRef = ref(null)
const viewerCloseRef = ref(null)
const viewerViewportRef = ref(null)
const canvasAspect = ref(1)
const viewerAspect = ref(1)
const viewerOpen = ref(false)
const viewerSource = ref('vector')
const viewerScale = ref(1)
const viewerX = ref(0)
const viewerY = ref(0)
const viewerAnimated = ref(false)
const prefersReducedMotion = ref(false)

const isAskOrigin = computed(() => props.payload.mode === 'ask_origin')
const isRoute = computed(() => props.payload.mode === 'route')
const active = computed(() => isAskOrigin.value && props.interactive)
const selectedNode = computed(() => (
  CAMPUS_NODES.find((node) => node.id === props.selectedNodeId) || null
))
const destinationLabel = computed(() => destinationBadge(props.payload.destination))
const cardTitle = computed(() => {
  if (isAskOrigin.value) {
    return 'いま、どこにいますか？'
  }
  if (props.payload.mode === 'place') {
    return props.payload.destination?.label || '場所マップ'
  }
  return `${props.payload.origin?.label || '出発地'}から${props.payload.destination?.label || '目的地'}へ`
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
const mapAriaLabel = computed(() => `${cardTitle.value}の本荘キャンパスマップ`)
const cardViewBox = computed(() => fitMapViewBox(props.payload, canvasAspect.value))
const viewerViewBox = computed(() => fullMapViewBox(viewerAspect.value))
const viewerTransformStyle = computed(() => ({
  transform: `translate3d(${viewerX.value}px, ${viewerY.value}px, 0) scale(${viewerScale.value})`,
}))
const viewerZoomLabel = computed(() => `${Math.round(viewerScale.value * 100)}%`)

let canvasResizeObserver = null
let viewerResizeObserver = null
let motionMediaQuery = null
let viewerReturnFocus = null
let animationTimer = null
let selectionReleaseTimer = null
const activePointers = new Map()
let gesture = null
let gestureMoved = false
let suppressViewerSelection = false
let lastTap = null

function updateAspect(element, target) {
  if (!element || !element.clientWidth || !element.clientHeight) {
    return
  }
  target.value = element.clientWidth / element.clientHeight
}

function selectNode(node) {
  if (!active.value) {
    return
  }
  if (viewerOpen.value && suppressViewerSelection) {
    return
  }
  if (viewerOpen.value) {
    closeViewer(false)
  }
  emit('origin-selected', { node: node.node, label: node.label })
}

function cancelSelection() {
  if (active.value) {
    emit('origin-cancelled')
  }
}

function setViewerAnimation(enabled) {
  viewerAnimated.value = enabled && !prefersReducedMotion.value
  if (animationTimer) {
    window.clearTimeout(animationTimer)
  }
  if (viewerAnimated.value) {
    animationTimer = window.setTimeout(() => {
      viewerAnimated.value = false
      animationTimer = null
    }, 220)
  }
}

function resetViewerTransform(animate = false) {
  setViewerAnimation(animate)
  viewerScale.value = 1
  viewerX.value = 0
  viewerY.value = 0
}

function openViewer(event) {
  viewerReturnFocus = event?.currentTarget instanceof HTMLElement
    ? event.currentTarget
    : expandButtonRef.value
  viewerSource.value = 'vector'
  resetViewerTransform(false)
  viewerOpen.value = true
  nextTick(() => {
    updateAspect(viewerViewportRef.value, viewerAspect)
    viewerCloseRef.value?.focus({ preventScroll: true })
    if (typeof ResizeObserver !== 'undefined' && viewerViewportRef.value) {
      viewerResizeObserver?.disconnect()
      viewerResizeObserver = new ResizeObserver(() => {
        updateAspect(viewerViewportRef.value, viewerAspect)
        constrainViewerTransform()
      })
      viewerResizeObserver.observe(viewerViewportRef.value)
    }
  })
}

function closeViewer(restoreFocus = true) {
  viewerOpen.value = false
  viewerResizeObserver?.disconnect()
  activePointers.clear()
  gesture = null
  lastTap = null
  if (restoreFocus) {
    const focusTarget = viewerReturnFocus?.isConnected ? viewerReturnFocus : expandButtonRef.value
    nextTick(() => focusTarget?.focus({ preventScroll: true }))
  }
  viewerReturnFocus = null
}

function switchViewerSource(source) {
  if (viewerSource.value === source) {
    return
  }
  viewerSource.value = source
  resetViewerTransform(false)
}

function setViewerTransform(scale, x, y, animate = false) {
  const viewport = viewerViewportRef.value
  if (!viewport) {
    return
  }
  const constrained = constrainMapTransform({
    scale,
    x,
    y,
    width: viewport.clientWidth,
    height: viewport.clientHeight,
  })
  setViewerAnimation(animate)
  viewerScale.value = constrained.scale
  viewerX.value = constrained.x
  viewerY.value = constrained.y
}

function constrainViewerTransform() {
  setViewerTransform(viewerScale.value, viewerX.value, viewerY.value, false)
}

function zoomAt(clientX, clientY, targetScale, animate = true) {
  const viewport = viewerViewportRef.value
  if (!viewport) {
    return
  }
  const rect = viewport.getBoundingClientRect()
  const anchorX = clientX - (rect.left + rect.width / 2)
  const anchorY = clientY - (rect.top + rect.height / 2)
  const next = zoomMapAt({
    scale: viewerScale.value,
    x: viewerX.value,
    y: viewerY.value,
    targetScale,
    anchorX,
    anchorY,
    width: viewport.clientWidth,
    height: viewport.clientHeight,
  })
  setViewerTransform(next.scale, next.x, next.y, animate)
}

function zoomFromCenter(delta) {
  const viewport = viewerViewportRef.value
  if (!viewport) {
    return
  }
  const rect = viewport.getBoundingClientRect()
  zoomAt(
    rect.left + rect.width / 2,
    rect.top + rect.height / 2,
    viewerScale.value + delta,
    true,
  )
}

function pointerCenter(points) {
  const [first, second] = points
  return {
    x: (first.x + second.x) / 2,
    y: (first.y + second.y) / 2,
  }
}

function pointerDistance(points) {
  const [first, second] = points
  return Math.hypot(second.x - first.x, second.y - first.y)
}

function startGesture() {
  const points = [...activePointers.values()]
  gestureMoved = false
  if (points.length >= 2) {
    const pair = points.slice(0, 2)
    gesture = {
      type: 'pinch',
      center: pointerCenter(pair),
      distance: Math.max(1, pointerDistance(pair)),
      scale: viewerScale.value,
      x: viewerX.value,
      y: viewerY.value,
    }
    return
  }
  if (points.length === 1) {
    gesture = {
      type: 'pan',
      point: points[0],
      x: viewerX.value,
      y: viewerY.value,
    }
  }
}

function onViewerPointerDown(event) {
  if (event.pointerType === 'mouse' && event.button !== 0) {
    return
  }
  event.currentTarget.setPointerCapture?.(event.pointerId)
  if (activePointers.size === 0) {
    suppressViewerSelection = false
  }
  activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
  setViewerAnimation(false)
  startGesture()
}

function onViewerPointerMove(event) {
  if (!activePointers.has(event.pointerId)) {
    return
  }
  const previous = activePointers.get(event.pointerId)
  activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
  if (Math.hypot(event.clientX - previous.x, event.clientY - previous.y) > 2) {
    gestureMoved = true
    suppressViewerSelection = true
  }

  const viewport = viewerViewportRef.value
  if (!viewport || !gesture) {
    return
  }
  const rect = viewport.getBoundingClientRect()
  if (gesture.type === 'pinch' && activePointers.size >= 2) {
    const pair = [...activePointers.values()].slice(0, 2)
    const center = pointerCenter(pair)
    const next = pinchMapAt({
      startScale: gesture.scale,
      startX: gesture.x,
      startY: gesture.y,
      startCenter: gesture.center,
      currentCenter: center,
      distanceRatio: pointerDistance(pair) / gesture.distance,
      viewportCenter: {
        x: rect.left + rect.width / 2,
        y: rect.top + rect.height / 2,
      },
      width: viewport.clientWidth,
      height: viewport.clientHeight,
    })
    setViewerTransform(next.scale, next.x, next.y, false)
    return
  }

  if (gesture.type === 'pan' && activePointers.size === 1 && viewerScale.value > 1) {
    const point = [...activePointers.values()][0]
    setViewerTransform(
      viewerScale.value,
      gesture.x + point.x - gesture.point.x,
      gesture.y + point.y - gesture.point.y,
      false,
    )
  }
}

function registerViewerTap(event) {
  const tap = { time: Date.now(), x: event.clientX, y: event.clientY }
  if (isMapDoubleTap(lastTap, tap)) {
    const targetScale = viewerScale.value > 1.2 ? 1 : 2.5
    zoomAt(tap.x, tap.y, targetScale, true)
    lastTap = null
    return
  }
  lastTap = tap
}

function onViewerPointerEnd(event) {
  const wasSingleTap = activePointers.size === 1 && !gestureMoved
  activePointers.delete(event.pointerId)
  event.currentTarget.releasePointerCapture?.(event.pointerId)
  if (wasSingleTap) {
    registerViewerTap(event)
  }
  startGesture()
  if (activePointers.size === 0 && suppressViewerSelection) {
    if (selectionReleaseTimer) {
      window.clearTimeout(selectionReleaseTimer)
    }
    selectionReleaseTimer = window.setTimeout(() => {
      suppressViewerSelection = false
      selectionReleaseTimer = null
    }, 0)
  }
}

function onViewerWheel(event) {
  const direction = event.deltaY < 0 ? 0.35 : -0.35
  zoomAt(event.clientX, event.clientY, viewerScale.value + direction, false)
}

function onViewerKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    closeViewer()
    return
  }
  if (event.key !== 'Tab' || !viewerRef.value) {
    return
  }
  const focusable = [...viewerRef.value.querySelectorAll(
    'button:not(:disabled), [href], [tabindex="0"]',
  )].filter((element) => !element.hasAttribute('aria-hidden'))
  if (!focusable.length) {
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

function syncMotionPreference(event) {
  prefersReducedMotion.value = event.matches
  if (event.matches) {
    setViewerAnimation(false)
  }
}

onMounted(() => {
  updateAspect(canvasRef.value, canvasAspect)
  if (typeof ResizeObserver !== 'undefined' && canvasRef.value) {
    canvasResizeObserver = new ResizeObserver(() => updateAspect(canvasRef.value, canvasAspect))
    canvasResizeObserver.observe(canvasRef.value)
  }
  motionMediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  prefersReducedMotion.value = motionMediaQuery.matches
  motionMediaQuery.addEventListener?.('change', syncMotionPreference)
})

watch(() => props.payload, () => resetViewerTransform(false), { deep: true })

onBeforeUnmount(() => {
  canvasResizeObserver?.disconnect()
  viewerResizeObserver?.disconnect()
  motionMediaQuery?.removeEventListener?.('change', syncMotionPreference)
  if (animationTimer) {
    window.clearTimeout(animationTimer)
  }
  if (selectionReleaseTimer) {
    window.clearTimeout(selectionReleaseTimer)
  }
})
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
    <header class="map-card__header">
      <div class="map-card__heading-copy">
        <h3 class="map-card__title">{{ cardTitle }}</h3>
        <p class="map-card__state" :class="{ 'map-card__state--live': active }">
          <span aria-hidden="true"></span>{{ stateLabel }}
        </p>
      </div>
    </header>

    <div v-if="isAskOrigin" class="map-card__instruction">
      <p>{{ payload.prompt || 'いまいる場所をマップでタップしてください' }}</p>
      <span v-if="active">地図か施設名ボタンから、1か所選んでください</span>
      <span v-else>{{ inactiveNote }}</span>
    </div>

    <div v-else class="map-card__summary" :aria-label="isRoute ? '経路の概要' : '場所の概要'">
      <template v-if="isRoute">
        <strong>{{ payload.origin?.label || '出発地' }}</strong>
        <svg aria-hidden="true" viewBox="0 0 44 12">
          <path d="M1 6h38M35 2l4 4-4 4" />
        </svg>
        <strong>{{ payload.destination?.label || '目的地' }}</strong>
      </template>
      <strong v-else>{{ payload.destination?.label || '目的地' }}</strong>
      <small v-if="destinationLabel">{{ destinationLabel }}</small>
    </div>

    <div
      ref="canvasRef"
      class="map-card__canvas"
      :aria-label="`${mapAriaLabel}。タップすると全画面で開きます`"
      @click="openViewer"
    >
      <CampusMapGraphic
        :payload="payload"
        :view-box="cardViewBox"
        :interactive="active"
        :selected-node-id="selectedNodeId"
        :aria-label="mapAriaLabel"
        @origin-selected="selectNode"
      />
      <button
        ref="expandButtonRef"
        type="button"
        class="map-card__expand"
        aria-haspopup="dialog"
        :aria-label="`${cardTitle}の地図を全画面で開く`"
        @click.stop="openViewer"
      >
        <svg aria-hidden="true" viewBox="0 0 24 24">
          <path d="M8.5 4H4v4.5M15.5 4H20v4.5M20 15.5V20h-4.5M8.5 20H4v-4.5" />
        </svg>
        <span>拡大</span>
      </button>
    </div>

    <p class="map-card__schematic-note">
      <svg aria-hidden="true" viewBox="0 0 16 16">
        <circle cx="8" cy="8" r="6.25" />
        <path d="M8 7.1v4M8 4.7h.01" />
      </svg>
      ※経路線は建物間のつながりを模式的に示したものです（実際の通路とは異なる場合があります）
    </p>

    <div v-if="isAskOrigin" class="map-card__selection-panel">
      <p class="map-card__selection-heading">現在地を施設名から選ぶ</p>
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
          @click="selectNode({ node: node.id, label: node.selectionLabel })"
        >
          <span class="map-card__chip-marker" aria-hidden="true">
            <svg v-if="selectedNodeId === node.id" viewBox="0 0 16 16">
              <path d="M3.5 8.2l2.8 2.7 6.2-6" />
            </svg>
            <span v-else></span>
          </span>
          <span>{{ node.selectionLabel }}</span>
        </button>
      </div>
      <button v-if="active" type="button" class="map-card__cancel" @click="cancelSelection">
        現在地を選ばずに続ける
      </button>
      <p v-else class="map-card__inactive-note" role="status">{{ inactiveNote }}</p>
    </div>

    <details v-if="isRoute && payload.steps?.length" class="map-card__steps" open>
      <summary>
        <strong>経路ステップ</strong>
        <span>{{ payload.steps.length }}</span>
        <svg aria-hidden="true" viewBox="0 0 24 24">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </summary>
      <ol class="map-card__step-list">
        <li v-for="(step, index) in payload.steps" :key="`${index}-${step}`">
          <span aria-hidden="true">{{ index + 1 }}</span>
          <p>{{ step }}</p>
        </li>
      </ol>
    </details>

    <Teleport to=".chat-shell">
      <Transition name="map-viewer-fade">
        <section
          v-if="viewerOpen"
          ref="viewerRef"
          class="map-viewer"
          role="dialog"
          aria-modal="true"
          :aria-label="`${cardTitle}の全画面マップ`"
          @keydown="onViewerKeydown"
        >
          <header class="map-viewer__header">
            <div>
              <h3>{{ cardTitle }}</h3>
              <p>{{ viewerSource === 'vector' ? 'キャンパスマップ' : '大学公式マップ' }}</p>
            </div>
            <div class="map-viewer__source-switch" aria-label="表示するマップを切り替え">
              <button
                type="button"
                :aria-pressed="viewerSource === 'vector'"
                @click="switchViewerSource('vector')"
              >
                見やすい地図
              </button>
              <button
                type="button"
                :aria-pressed="viewerSource === 'official'"
                @click="switchViewerSource('official')"
              >
                公式マップを見る
              </button>
            </div>
            <button
              ref="viewerCloseRef"
              type="button"
              class="map-viewer__close"
              aria-label="全画面マップを閉じる"
              @click="closeViewer()"
            >
              <svg aria-hidden="true" viewBox="0 0 24 24">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </header>

          <div
            ref="viewerViewportRef"
            class="map-viewer__viewport"
            :aria-label="`${viewerSource === 'vector' ? 'ベクター' : '公式'}マップ。ピンチ、ダブルタップ、ドラッグで拡大移動できます`"
            @pointerdown="onViewerPointerDown"
            @pointermove="onViewerPointerMove"
            @pointerup="onViewerPointerEnd"
            @pointercancel="onViewerPointerEnd"
            @wheel.prevent="onViewerWheel"
          >
            <div
              class="map-viewer__transform"
              :class="{ 'map-viewer__transform--animated': viewerAnimated }"
              :style="viewerTransformStyle"
            >
              <CampusMapGraphic
                v-if="viewerSource === 'vector'"
                :payload="payload"
                :view-box="viewerViewBox"
                :interactive="active"
                :selected-node-id="selectedNodeId"
                :aria-label="mapAriaLabel"
                @origin-selected="selectNode"
              />
              <img
                v-else
                class="map-viewer__official-map"
                :src="campusMapImage"
                alt="秋田県立大学 本荘キャンパス公式マップ"
                draggable="false"
              />
            </div>

            <div class="map-viewer__zoom-controls" aria-label="地図のズーム操作">
              <button type="button" aria-label="地図を縮小" :disabled="viewerScale <= 1" @click="zoomFromCenter(-0.5)">−</button>
              <span aria-live="polite">{{ viewerZoomLabel }}</span>
              <button type="button" aria-label="地図を拡大" :disabled="viewerScale >= 4" @click="zoomFromCenter(0.5)">＋</button>
              <button type="button" aria-label="地図の表示を元に戻す" :disabled="viewerScale === 1" @click="resetViewerTransform(true)">
                <svg aria-hidden="true" viewBox="0 0 24 24">
                  <path d="M5 8V4m0 0h4M5 4l3.2 3.2A7 7 0 1 1 5.6 14" />
                </svg>
              </button>
            </div>

            <p class="map-viewer__gesture-hint">ピンチ・ダブルタップで拡大</p>
          </div>

          <div v-if="isAskOrigin" class="map-viewer__origin-panel">
            <p>{{ active ? '現在地を選んでください' : inactiveNote }}</p>
            <div class="map-viewer__origin-chips" aria-label="全画面マップで現在地を選択">
              <button
                v-for="node in CAMPUS_NODES"
                :key="`${node.id}-viewer-chip`"
                type="button"
                :disabled="!active"
                :aria-label="`現在地を${node.selectionLabel}にする`"
                :aria-pressed="selectedNodeId === node.id"
                @click="selectNode({ node: node.id, label: node.selectionLabel })"
              >
                {{ node.selectionLabel }}
              </button>
            </div>
          </div>
        </section>
      </Transition>
    </Teleport>
  </section>
</template>

<style scoped>
.map-card {
  --map-signal: #ff7657;
  --map-signal-soft: #ffad98;
  position: relative;
  width: 100%;
  max-width: 100%;
  overflow: hidden;
  border: 1px solid rgba(222, 231, 232, 0.13);
  border-radius: 1.45rem;
  background: #111719;
  box-shadow: 0 28px 72px -48px rgba(0, 0, 0, 0.96);
  color: #edf1ef;
  font-family: "Space Grotesk", "Noto Sans JP", "Hiragino Sans", "Yu Gothic UI", sans-serif;
}

.map-card--ask-active {
  border-color: rgba(255, 118, 87, 0.34);
}

.map-card__header {
  padding: 1.1rem 1.1rem 0.35rem;
}

.map-card__heading-copy {
  display: flex;
  min-width: 0;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.85rem;
}

.map-card__title {
  min-width: 0;
  overflow-wrap: anywhere;
  color: rgba(242, 245, 243, 0.96);
  font-size: clamp(0.98rem, 4.1vw, 1.12rem);
  font-weight: 650;
  letter-spacing: -0.025em;
  line-height: 1.45;
}

.map-card__state {
  display: inline-flex;
  min-height: 1.5rem;
  flex: none;
  align-items: center;
  gap: 0.42rem;
  color: rgba(219, 227, 227, 0.48);
  font-size: 0.68rem;
  font-weight: 580;
  white-space: nowrap;
}

.map-card__state > span {
  width: 0.38rem;
  height: 0.38rem;
  border-radius: 999px;
  background: currentColor;
}

.map-card__state--live {
  color: var(--map-signal-soft);
}

.map-card__instruction {
  padding: 0 1.1rem 0.95rem;
}

.map-card__instruction p {
  color: rgba(230, 235, 233, 0.82);
  font-size: 0.82rem;
  font-weight: 560;
  line-height: 1.55;
}

.map-card__instruction span {
  display: block;
  margin-top: 0.18rem;
  color: rgba(213, 222, 221, 0.46);
  font-size: 0.7rem;
  line-height: 1.5;
}

.map-card__summary {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.55rem;
  padding: 0.12rem 1.1rem 0.95rem;
  color: rgba(222, 229, 228, 0.62);
}

.map-card__summary strong {
  min-width: 0;
  overflow: hidden;
  font-size: 0.75rem;
  font-weight: 590;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.map-card__summary svg {
  width: 2.25rem;
  height: 0.75rem;
  flex: none;
}

.map-card__summary path {
  fill: none;
  stroke: var(--map-signal);
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.5;
}

.map-card__summary small {
  flex: none;
  border-radius: 999px;
  background: var(--map-signal);
  padding: 0.18rem 0.45rem;
  color: #28130e;
  font-size: 0.66rem;
  font-weight: 760;
}

.map-card__canvas {
  position: relative;
  width: 100%;
  height: clamp(21.75rem, 94vw, 27rem);
  min-height: 348px;
  overflow: hidden;
  border-block: 1px solid rgba(222, 231, 232, 0.12);
  background: #0b1113;
  cursor: zoom-in;
}

.map-card__expand {
  position: absolute;
  top: 0.75rem;
  right: 0.75rem;
  display: inline-flex;
  min-height: 44px;
  align-items: center;
  gap: 0.38rem;
  border: 1px solid rgba(224, 232, 232, 0.24);
  border-radius: 999px;
  background: rgba(11, 17, 19, 0.82);
  padding: 0.4rem 0.72rem;
  color: rgba(240, 243, 242, 0.84);
  font-size: 0.7rem;
  font-weight: 620;
  box-shadow: 0 8px 24px -14px rgba(0, 0, 0, 0.9);
  backdrop-filter: blur(8px);
  transition: background 160ms ease, color 160ms ease;
}

.map-card__expand svg {
  width: 1rem;
  height: 1rem;
}

.map-card__expand path {
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
}

.map-card__expand:hover,
.map-card__expand:focus-visible {
  background: rgba(31, 41, 44, 0.96);
  color: white;
}

.map-card__schematic-note {
  display: flex;
  align-items: flex-start;
  gap: 0.38rem;
  padding: 0.65rem 1.1rem 0.8rem;
  color: rgba(210, 220, 219, 0.43);
  font-size: 0.65rem;
  line-height: 1.55;
}

.map-card__schematic-note svg {
  width: 0.9rem;
  height: 0.9rem;
  flex: none;
  margin-top: 0.08rem;
}

.map-card__schematic-note circle,
.map-card__schematic-note path {
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-width: 1.3;
}

.map-card__selection-panel,
.map-card__steps {
  border-top: 1px solid rgba(222, 231, 232, 0.09);
  padding: 0.9rem 1.1rem 0.85rem;
}

.map-card__selection-heading {
  margin-bottom: 0.62rem;
  color: rgba(228, 234, 232, 0.72);
  font-size: 0.75rem;
  font-weight: 610;
}

.map-card__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}

.map-card__chip {
  display: inline-flex;
  min-width: 0;
  min-height: 44px;
  max-width: 100%;
  align-items: center;
  gap: 0.5rem;
  border: 1px solid rgba(222, 231, 232, 0.13);
  border-radius: 999px;
  background: transparent;
  padding: 0.42rem 0.7rem;
  color: rgba(226, 232, 230, 0.7);
  font-size: 0.7rem;
  line-height: 1.35;
  text-align: left;
  transition: border-color 150ms ease, background 150ms ease, color 150ms ease;
}

.map-card__chip-marker {
  display: grid;
  width: 1.1rem;
  height: 1.1rem;
  flex: none;
  place-items: center;
  border: 1px solid rgba(222, 231, 232, 0.22);
  border-radius: 999px;
}

.map-card__chip-marker > span {
  width: 0.26rem;
  height: 0.26rem;
  border-radius: 999px;
  background: rgba(222, 231, 232, 0.42);
}

.map-card__chip-marker svg {
  width: 0.75rem;
  height: 0.75rem;
}

.map-card__chip-marker path {
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
}

.map-card__chip:hover:not(:disabled),
.map-card__chip:focus-visible:not(:disabled),
.map-card__chip--selected {
  border-color: rgba(255, 118, 87, 0.56);
  background: rgba(255, 118, 87, 0.09);
  color: #fff4ef;
}

.map-card__chip--selected .map-card__chip-marker {
  border-color: var(--map-signal);
  background: var(--map-signal);
  color: #2b120c;
}

.map-card__chip:disabled {
  cursor: default;
  opacity: 0.42;
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
  color: rgba(222, 231, 230, 0.48);
  font-size: 0.7rem;
  text-decoration: underline;
  text-decoration-color: rgba(222, 231, 230, 0.2);
  text-underline-offset: 0.22rem;
  transition: color 150ms ease;
}

.map-card__cancel:hover,
.map-card__cancel:focus-visible {
  color: rgba(241, 244, 243, 0.86);
}

.map-card__inactive-note {
  margin-top: 0.65rem;
  color: rgba(213, 222, 221, 0.45);
  font-size: 0.68rem;
  line-height: 1.5;
}

.map-card__steps {
  padding-top: 0.3rem;
}

.map-card__steps summary {
  display: flex;
  min-height: 44px;
  align-items: center;
  gap: 0.7rem;
  color: rgba(227, 233, 231, 0.68);
  cursor: pointer;
  list-style: none;
}

.map-card__steps summary::-webkit-details-marker {
  display: none;
}

.map-card__steps summary strong {
  flex: 1;
  font-size: 0.78rem;
  font-weight: 620;
}

.map-card__steps summary > span {
  display: grid;
  width: 1.55rem;
  height: 1.55rem;
  place-items: center;
  border: 1px solid rgba(255, 118, 87, 0.32);
  border-radius: 999px;
  color: var(--map-signal-soft);
  font-size: 0.66rem;
  font-weight: 700;
}

.map-card__steps summary svg {
  width: 1rem;
  height: 1rem;
  transition: transform 180ms ease;
}

.map-card__steps summary path {
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-width: 1.9;
}

.map-card__steps:not([open]) summary svg {
  transform: rotate(-90deg);
}

.map-card__step-list {
  padding: 0.3rem 0 0.05rem;
}

.map-card__step-list li {
  position: relative;
  display: grid;
  grid-template-columns: 1.7rem minmax(0, 1fr);
  gap: 0.65rem;
  padding-bottom: 0.75rem;
}

.map-card__step-list li:not(:last-child)::after {
  position: absolute;
  top: 1.65rem;
  bottom: 0;
  left: 0.82rem;
  width: 1px;
  background: rgba(255, 118, 87, 0.24);
  content: "";
}

.map-card__step-list li > span {
  display: grid;
  width: 1.7rem;
  height: 1.7rem;
  place-items: center;
  border: 1px solid rgba(255, 118, 87, 0.32);
  border-radius: 999px;
  color: var(--map-signal-soft);
  font-size: 0.62rem;
  font-weight: 700;
}

.map-card__step-list p {
  padding-top: 0.14rem;
  color: rgba(225, 231, 229, 0.72);
  font-size: 0.78rem;
  line-height: 1.62;
}

.map-card--inactive .map-card__canvas,
.map-card--inactive .map-card__instruction {
  opacity: 0.65;
}

.map-viewer {
  position: absolute;
  inset: 0;
  z-index: 60;
  display: flex;
  min-width: 0;
  flex-direction: column;
  overflow: hidden;
  overscroll-behavior: contain;
  padding-top: env(safe-area-inset-top);
  padding-bottom: env(safe-area-inset-bottom);
  background: #080d0f;
  color: #edf1ef;
  font-family: "Space Grotesk", "Noto Sans JP", "Hiragino Sans", "Yu Gothic UI", sans-serif;
}

.map-viewer__header {
  position: relative;
  z-index: 2;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto 44px;
  align-items: center;
  gap: 0.7rem;
  min-height: 68px;
  border-bottom: 1px solid rgba(222, 231, 232, 0.12);
  background: rgba(9, 14, 16, 0.94);
  padding: 0.62rem 0.75rem 0.62rem 1rem;
}

.map-viewer__header h3 {
  overflow: hidden;
  color: rgba(242, 245, 243, 0.96);
  font-size: 0.94rem;
  font-weight: 650;
  letter-spacing: -0.025em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.map-viewer__header p {
  margin-top: 0.08rem;
  color: rgba(218, 226, 225, 0.45);
  font-size: 0.65rem;
}

.map-viewer__source-switch {
  display: flex;
  align-items: center;
  gap: 0.15rem;
  border-radius: 999px;
  background: rgba(222, 231, 232, 0.07);
  padding: 0.18rem;
}

.map-viewer__source-switch button {
  min-height: 40px;
  border-radius: 999px;
  padding: 0.4rem 0.72rem;
  color: rgba(222, 231, 230, 0.56);
  font-size: 0.68rem;
  font-weight: 600;
}

.map-viewer__source-switch button[aria-pressed="true"] {
  background: rgba(222, 231, 232, 0.12);
  color: #f2f5f3;
}

.map-viewer__close {
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  border-radius: 999px;
  color: rgba(235, 240, 238, 0.72);
}

.map-viewer__close:hover,
.map-viewer__close:focus-visible {
  background: rgba(222, 231, 232, 0.09);
  color: white;
}

.map-viewer__close svg {
  width: 1.25rem;
  height: 1.25rem;
}

.map-viewer__close path,
.map-viewer__zoom-controls path {
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
}

.map-viewer__viewport {
  position: relative;
  min-height: 0;
  flex: 1;
  overflow: hidden;
  overscroll-behavior: contain;
  background: #0b1113;
  cursor: grab;
  touch-action: none;
  user-select: none;
}

.map-viewer__viewport:active {
  cursor: grabbing;
}

.map-viewer__transform {
  position: absolute;
  inset: 0;
  transform-origin: 50% 50%;
  will-change: transform;
}

.map-viewer__transform--animated {
  transition: transform 220ms cubic-bezier(0.2, 0.8, 0.2, 1);
}

.map-viewer__official-map {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #f7f7f4;
  pointer-events: none;
}

.map-viewer__zoom-controls {
  position: absolute;
  right: max(0.75rem, env(safe-area-inset-right));
  bottom: 0.85rem;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 0.15rem;
  border: 1px solid rgba(222, 231, 232, 0.2);
  border-radius: 999px;
  background: rgba(9, 14, 16, 0.86);
  padding: 0.18rem;
  box-shadow: 0 12px 34px -22px rgba(0, 0, 0, 0.94);
  backdrop-filter: blur(10px);
}

.map-viewer__zoom-controls button {
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  border-radius: 999px;
  color: rgba(237, 241, 239, 0.84);
  font-size: 1.2rem;
}

.map-viewer__zoom-controls button:hover:not(:disabled),
.map-viewer__zoom-controls button:focus-visible:not(:disabled) {
  background: rgba(222, 231, 232, 0.1);
  color: white;
}

.map-viewer__zoom-controls button:disabled {
  color: rgba(222, 231, 232, 0.24);
}

.map-viewer__zoom-controls button svg {
  width: 1.05rem;
  height: 1.05rem;
}

.map-viewer__zoom-controls > span {
  min-width: 3rem;
  color: rgba(226, 232, 230, 0.58);
  font-size: 0.65rem;
  text-align: center;
}

.map-viewer__gesture-hint {
  position: absolute;
  bottom: 1.15rem;
  left: max(0.85rem, env(safe-area-inset-left));
  color: rgba(222, 231, 230, 0.5);
  font-size: 0.66rem;
  pointer-events: none;
}

.map-viewer__origin-panel {
  max-height: 34%;
  overflow-y: auto;
  overscroll-behavior: contain;
  border-top: 1px solid rgba(222, 231, 232, 0.12);
  background: #0e1517;
  padding: 0.75rem max(0.9rem, env(safe-area-inset-right)) 0.8rem max(0.9rem, env(safe-area-inset-left));
}

.map-viewer__origin-panel > p {
  margin-bottom: 0.55rem;
  color: rgba(235, 239, 237, 0.76);
  font-size: 0.75rem;
  font-weight: 600;
}

.map-viewer__origin-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.42rem;
}

.map-viewer__origin-chips button {
  min-height: 44px;
  max-width: 100%;
  border: 1px solid rgba(222, 231, 232, 0.15);
  border-radius: 999px;
  padding: 0.42rem 0.75rem;
  color: rgba(229, 235, 233, 0.74);
  font-size: 0.7rem;
}

.map-viewer__origin-chips button:hover:not(:disabled),
.map-viewer__origin-chips button:focus-visible:not(:disabled),
.map-viewer__origin-chips button[aria-pressed="true"] {
  border-color: rgba(255, 118, 87, 0.58);
  background: rgba(255, 118, 87, 0.1);
  color: #fff4ef;
}

.map-viewer__origin-chips button:disabled {
  opacity: 0.42;
}

.map-viewer-fade-enter-active,
.map-viewer-fade-leave-active {
  transition: opacity 180ms ease;
}

.map-viewer-fade-enter-from,
.map-viewer-fade-leave-to {
  opacity: 0;
}

@media (max-width: 640px) {
  .map-viewer__header {
    grid-template-columns: minmax(0, 1fr) 44px;
    align-items: start;
  }

  .map-viewer__source-switch {
    grid-column: 1 / -1;
    grid-row: 2;
    width: 100%;
  }

  .map-viewer__source-switch button {
    min-height: 44px;
    flex: 1;
  }

  .map-viewer__close {
    grid-column: 2;
    grid-row: 1;
  }

  .map-viewer__zoom-controls > span {
    display: none;
  }

  .map-viewer__gesture-hint {
    bottom: 4.4rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .map-card__expand,
  .map-card__chip,
  .map-card__cancel,
  .map-card__steps summary svg,
  .map-viewer__transform,
  .map-viewer-fade-enter-active,
  .map-viewer-fade-leave-active {
    animation: none !important;
    transition: none !important;
  }
}
</style>
