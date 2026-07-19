<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { useChatStore } from '../stores/chat'
import { useCampusPetStore } from '../stores/pet'
import {
  chooseCampusPetReaction,
  clampCampusPetTranslation,
  pointerDragThreshold,
  positionRatioFromRects,
  resolveCampusPetState,
  translationFromPositionRatio,
} from '../utils/campusPet'
import CampusPetSvg from './CampusPetSvg.vue'
import './campusPet.css'

const props = defineProps({
  composerClearance: {
    type: Number,
    default: 100,
  },
})

const chat = useChatStore()
const pet = useCampusPetStore()

const layerRef = ref(null)
const buttonRef = ref(null)
const rendered = ref(Boolean(pet.unlocked && pet.visible && pet.currentForm))
const smokeVisible = ref(false)
const summoningActive = ref(false)
const doneActive = ref(false)
const dragging = ref(false)
const settling = ref(false)
const reaction = ref('')

const protectControls = computed(() => (
  chat.isClarificationPending
  || chat.messages.some((message) => message.mapInteractive)
  || pet.phase !== 'idle'
))

const petState = computed(() => {
  return resolveCampusPetState({
    summoning: summoningActive.value,
    clarification: chat.isClarificationPending,
    sending: chat.isSending,
    done: doneActive.value,
  })
})

let smokeTimer = null
let visibilityTimer = null
let doneTimer = null
let reactionTimer = null
let settlingTimer = null
let tapTimer = null
let lastTapAt = 0
let layerResizeObserver = null
let translation = { tx: 0, ty: 0 }
let pointerSession = null

function clearTimer(timer) {
  if (timer) {
    window.clearTimeout(timer)
  }
}

function showSmoke({ materialize = true } = {}) {
  clearTimer(smokeTimer)
  smokeVisible.value = true
  summoningActive.value = materialize
  smokeTimer = window.setTimeout(() => {
    smokeVisible.value = false
    summoningActive.value = false
    smokeTimer = null
  }, 720)
}

function baseButtonRect() {
  const rect = buttonRef.value?.getBoundingClientRect()
  if (!rect) {
    return null
  }
  return {
    left: rect.left - translation.tx,
    right: rect.right - translation.tx,
    top: rect.top - translation.ty,
    bottom: rect.bottom - translation.ty,
    width: rect.width,
    height: rect.height,
  }
}

function updateTranslation(nextTranslation) {
  translation = nextTranslation
  if (buttonRef.value) {
    buttonRef.value.style.transform = `translate3d(${translation.tx}px, ${translation.ty}px, 0)`
  }
}

function clampedTranslation(nextTranslation, baseRect = baseButtonRect()) {
  const layerRect = layerRef.value?.getBoundingClientRect()
  if (!baseRect || !layerRect) {
    return nextTranslation
  }
  return clampCampusPetTranslation({
    baseRect,
    layerRect,
    tx: nextTranslation.tx,
    ty: nextTranslation.ty,
    topInset: 56,
    sideInset: 4,
    bottomClearance: props.composerClearance,
  })
}

function applyStoredPosition() {
  if (dragging.value || !buttonRef.value || !layerRef.value) {
    return
  }
  updateTranslation({ tx: 0, ty: 0 })
  if (!pet.pos) {
    return
  }
  const baseRect = baseButtonRect()
  const layerRect = layerRef.value.getBoundingClientRect()
  if (!baseRect || !layerRect.width || !layerRect.height) {
    return
  }
  const restored = translationFromPositionRatio({ pos: pet.pos, baseRect, layerRect })
  updateTranslation(clampedTranslation(restored, baseRect))
}

function saveCurrentPosition() {
  const buttonRect = buttonRef.value?.getBoundingClientRect()
  const layerRect = layerRef.value?.getBoundingClientRect()
  if (!buttonRect || !layerRect?.width || !layerRect?.height) {
    return
  }
  pet.setPosition(positionRatioFromRects(buttonRect, layerRect))
}

function playReaction() {
  clearTimer(reactionTimer)
  reaction.value = chooseCampusPetReaction(pet.currentForm)
  reactionTimer = window.setTimeout(() => {
    reaction.value = ''
    reactionTimer = null
  }, reaction.value === 'nod' ? 620 : 720)
}

function handleTap() {
  const now = Date.now()
  if (lastTapAt && now - lastTapAt <= 300) {
    clearTimer(tapTimer)
    tapTimer = null
    lastTapAt = 0
    return
  }
  lastTapAt = now
  clearTimer(tapTimer)
  tapTimer = window.setTimeout(() => {
    playReaction()
    lastTapAt = 0
    tapTimer = null
  }, 300)
}

function onPointerDown(event) {
  if (protectControls.value || pointerSession) {
    return
  }
  buttonRef.value?.setPointerCapture?.(event.pointerId)
  pointerSession = {
    pointerId: event.pointerId,
    pointerType: event.pointerType,
    startX: event.clientX,
    startY: event.clientY,
    startTx: translation.tx,
    startTy: translation.ty,
    baseRect: baseButtonRect(),
  }
}

function onPointerMove(event) {
  if (!pointerSession || pointerSession.pointerId !== event.pointerId) {
    return
  }
  const dx = event.clientX - pointerSession.startX
  const dy = event.clientY - pointerSession.startY
  if (!dragging.value && Math.hypot(dx, dy) >= pointerDragThreshold(pointerSession.pointerType)) {
    dragging.value = true
    clearTimer(tapTimer)
    tapTimer = null
    lastTapAt = 0
  }
  if (!dragging.value) {
    return
  }
  event.preventDefault()
  const nextTranslation = clampedTranslation({
    tx: pointerSession.startTx + dx,
    ty: pointerSession.startTy + dy,
  }, pointerSession.baseRect)
  updateTranslation(nextTranslation)
}

function finishPointer(event, cancelled = false) {
  if (!pointerSession || pointerSession.pointerId !== event.pointerId) {
    return
  }
  buttonRef.value?.releasePointerCapture?.(event.pointerId)
  const wasDragging = dragging.value
  pointerSession = null
  dragging.value = false
  if (wasDragging) {
    saveCurrentPosition()
    if (!cancelled) {
      clearTimer(settlingTimer)
      settling.value = true
      settlingTimer = window.setTimeout(() => {
        settling.value = false
        settlingTimer = null
      }, 260)
    }
    return
  }
  if (!cancelled) {
    handleTap()
  }
}

function onPointerUp(event) {
  finishPointer(event)
}

function onPointerCancel(event) {
  finishPointer(event, true)
}

watch(
  () => chat.isSending,
  (isSending, wasSending) => {
    clearTimer(doneTimer)
    doneTimer = null
    if (isSending) {
      doneActive.value = false
      return
    }
    if (wasSending) {
      doneActive.value = true
      doneTimer = window.setTimeout(() => {
        doneActive.value = false
        doneTimer = null
      }, 4000)
    }
  },
)

watch(
  () => pet.summonRevision,
  (revision, previousRevision) => {
    if (revision === previousRevision || !pet.currentForm) {
      return
    }
    clearTimer(visibilityTimer)
    rendered.value = true
    showSmoke()
    nextTick(applyStoredPosition)
  },
)

watch(
  () => pet.visible,
  (visible, wasVisible) => {
    if (visible === wasVisible || !pet.currentForm) {
      return
    }
    clearTimer(visibilityTimer)
    if (visible) {
      rendered.value = true
      showSmoke()
      nextTick(applyStoredPosition)
      return
    }
    showSmoke({ materialize: false })
    visibilityTimer = window.setTimeout(() => {
      rendered.value = false
      visibilityTimer = null
    }, 720)
  },
)

watch(
  () => pet.pos,
  () => nextTick(applyStoredPosition),
  { deep: true },
)

watch(
  () => props.composerClearance,
  () => nextTick(applyStoredPosition),
)

onMounted(() => {
  nextTick(applyStoredPosition)
  window.addEventListener('resize', applyStoredPosition)
  if (typeof ResizeObserver !== 'undefined' && layerRef.value) {
    layerResizeObserver = new ResizeObserver(applyStoredPosition)
    layerResizeObserver.observe(layerRef.value)
  }
})

onBeforeUnmount(() => {
  clearTimer(smokeTimer)
  clearTimer(visibilityTimer)
  clearTimer(doneTimer)
  clearTimer(reactionTimer)
  clearTimer(settlingTimer)
  clearTimer(tapTimer)
  layerResizeObserver?.disconnect()
  window.removeEventListener('resize', applyStoredPosition)
})
</script>

<template>
  <div
    v-if="rendered && pet.currentForm"
    ref="layerRef"
    class="campus-pet-host campus-pet-layer"
    :class="{ 'campus-pet-layer--protect-controls': protectControls }"
    :style="{ '--pet-composer-clearance': `${composerClearance}px` }"
    aria-hidden="true"
  >
    <button
      ref="buttonRef"
      type="button"
      tabindex="-1"
      class="campus-pet-button"
      :class="{ 'campus-pet-button--placed': pet.pos }"
      :data-dragging="dragging ? 'true' : undefined"
      :data-settling="settling ? 'true' : undefined"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerCancel"
      @dblclick.prevent
    >
      <CampusPetSvg
        :form="pet.currentForm"
        :state="petState"
        :reaction="reaction"
      />
      <svg v-if="smokeVisible" class="campus-pet-smoke" viewBox="0 0 72 72" aria-hidden="true">
        <g class="smoke-ring">
          <ellipse cx="36" cy="51" rx="18" ry="5.2" fill="var(--pet-paper)" opacity="0.1" />
        </g>
        <circle class="smoke-puff smoke-puff--a" cx="25" cy="42" r="8.5" fill="var(--pet-paper)" />
        <circle class="smoke-puff smoke-puff--b" cx="38" cy="37" r="10" fill="var(--pet-paper)" />
        <circle class="smoke-puff smoke-puff--c" cx="49" cy="44" r="7.5" fill="var(--pet-muted)" />
        <circle class="smoke-puff smoke-puff--d" cx="31" cy="51" r="6" fill="var(--pet-muted)" />
        <circle class="smoke-dot smoke-dot--a" cx="18" cy="36" r="2.2" fill="var(--pet-paper)" />
        <circle class="smoke-dot smoke-dot--b" cx="55" cy="35" r="2" fill="var(--pet-paper)" />
      </svg>
    </button>
  </div>
</template>
