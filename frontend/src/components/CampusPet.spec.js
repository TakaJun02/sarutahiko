import { readFileSync } from 'node:fs'

import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useChatStore } from '../stores/chat'
import { useCampusPetStore } from '../stores/pet'
import {
  CAMPUS_PET_FORMS,
  CAMPUS_PET_SUMMON_WAIT_MS,
  CAMPUS_PET_STORAGE_KEY,
  canOpenCampusPetPickerFromTap,
  chooseCampusPetReaction,
  clampCampusPetTranslation,
  createDefaultCampusPetState,
  isCampusPetPassphrase,
  loadCampusPetState,
  pointerDragThreshold,
  positionRatioFromRects,
  resolveCampusPetState,
  saveCampusPetState,
  translationFromPositionRatio,
} from '../utils/campusPet'
import { CAMPUS_PET_SVGS } from './campusPetSvgs'

const chatViewSource = readFileSync(new URL('../views/ChatView.vue', import.meta.url), 'utf8')
const campusPetSource = readFileSync(new URL('./CampusPet.vue', import.meta.url), 'utf8')
const pickerSource = readFileSync(new URL('./CampusPetPicker.vue', import.meta.url), 'utf8')
const petCssSource = readFileSync(new URL('./campusPet.css', import.meta.url), 'utf8')
const previewSource = readFileSync(new URL('../../../docs/pet-preview.html', import.meta.url), 'utf8')
const normalizedChatSource = chatViewSource.replace(/\s+/g, ' ')
const normalizedPetSource = campusPetSource.replace(/\s+/g, ' ')

function createMemoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem: vi.fn((key) => values.get(key) ?? null),
    setItem: vi.fn((key, value) => values.set(key, String(value))),
    removeItem: vi.fn((key) => values.delete(key)),
    value(key) {
      return values.get(key) ?? null
    },
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('FR-41 §11-1 passphrase interception', () => {
  it('accepts only the specified normalized exact phrase and leaves the normal send path intact', () => {
    for (const text of [
      'ペットを呼び出す',
      ' ペットを呼び出す！ ',
      '　ペットを呼び出す!　',
      'ペットを呼び出す。',
    ]) {
      expect(isCampusPetPassphrase(text)).toBe(true)
    }
    for (const text of [
      'ペットを呼び出すよ',
      'ペットを呼び出す方法は？',
      'ペットをよびだす',
      'ドロン',
    ]) {
      expect(isCampusPetPassphrase(text)).toBe(false)
    }

    const sendSource = chatViewSource.match(/async function send\(\) \{[\s\S]*?\n\}/)?.[0]
    expect(sendSource).toContain('if (isCampusPetPassphrase(text))')
    expect(sendSource).toContain('beginCampusPetSummon()')
    expect(sendSource).toContain('await chat.sendMessage(text)')
    expect(sendSource.indexOf('beginCampusPetSummon()')).toBeLessThan(sendSource.indexOf('await chat.sendMessage(text)'))
    expect(chatViewSource).toContain('{{ CAMPUS_PET_PASSPHRASE }}')
  })

  it('keeps the summon local and advances waiting to picking after 1900ms', () => {
    vi.useFakeTimers()
    const chat = useChatStore()
    const pet = useCampusPetStore()
    const sendMessage = vi.spyOn(chat, 'sendMessage')
    const messagesBefore = [...chat.messages]
    const chatStateBefore = JSON.stringify(chat.$state)

    expect(pet.beginSummon()).toBe(true)
    const runId = pet.summonRunId
    globalThis.setTimeout(() => pet.showPicker(), CAMPUS_PET_SUMMON_WAIT_MS)

    expect(pet.phase).toBe('waiting')
    expect(pet.summonOrigin).toBe('passphrase')
    expect(runId).toBeGreaterThan(0)
    vi.advanceTimersByTime(1899)
    expect(pet.phase).toBe('waiting')
    vi.advanceTimersByTime(1)
    expect(pet.phase).toBe('picking')
    expect(pet.summonOrigin).toBe('passphrase')
    expect(chat.messages).toEqual(messagesBefore)
    expect(JSON.stringify(chat.$state)).toBe(chatStateBefore)
    expect(sendMessage).not.toHaveBeenCalled()

    expect(chatViewSource).toContain('}, CAMPUS_PET_SUMMON_WAIT_MS)')
    expect(chatViewSource).toContain(':key="pet.summonRunId"')
    expect(chatViewSource).toContain('campus-pet-spinner-fade-leave-active')
    expect(chatViewSource).toContain('transition: opacity 160ms ease-out;')
    expect(chatViewSource).toContain('campus-pet-summon-block-leave-active')
    expect(chatViewSource).toContain('transition: opacity 260ms ease-out;')
  })
})

describe('FR-41 §11-2 picker behavior', () => {
  it('keeps the six-form order, focus/cancel/current semantics, and composer lock', () => {
    expect(CAMPUS_PET_FORMS.map((form) => form.id)).toEqual([
      'robo',
      'sarutahiko',
      'akita',
      'gotenmari',
      'namahage',
      'yatagarasu',
    ])
    expect(pickerSource).toContain('firstOptionRef.value?.focus({ preventScroll: true })')
    expect(pickerSource).toContain("event.key === 'Escape'")
    expect(pickerSource).toContain("emit('cancel')")
    expect(pickerSource).toContain("'campus-pet-picker__option--current': form.id === currentForm")
    expect(pickerSource).toContain(":aria-current=\"form.id === currentForm ? 'true' : undefined\"")
    expect(pickerSource).toContain('class="campus-pet-picker__stage"')
    expect(pickerSource).toContain('class="campus-pet-picker__figure"')
    expect(pickerSource).toContain(':style="`--i: ${index}`"')
    expect(pickerSource).toContain('class="campus-pet-picker__kicker"')
    expect(pickerSource).toContain('class="campus-pet-picker__apparition"')
    expect(pickerSource).toContain('class="campus-pet-picker__halo"')
    expect(pickerSource).toContain('class="campus-pet-picker__ground"')
    expect(pickerSource).toContain('animation-delay: calc(180ms + var(--i, 0) * 70ms);')
    expect(pickerSource).toContain('@keyframes campus_pet_halo_bloom')
    expect(pickerSource).toContain('@keyframes campus_pet_ground_sweep')
    expect(pickerSource).toContain('@keyframes campus_pet_picker_pop')
    expect(pickerSource).toContain('@keyframes campus_pet_picker_puff')
    expect(pickerSource).toContain('animation: campus_pet_picker_fade 260ms var(--ease-standard) 700ms both;')
    expect(pickerSource).not.toContain('campus-pet-picker__head')
    expect(pickerSource).not.toContain('campus-pet-picker__smoke-mark')
    expect(pickerSource).not.toContain('campus-pet-picker__grid')
    expect(pickerSource).not.toContain('campus-pet-picker__thumb')
    expect(normalizedChatSource).toContain("'composer-shell--pet-locked': pet.phase !== 'idle'")
    expect(normalizedChatSource).toContain('<fieldset :disabled="pet.phase !== \'idle\'" class="contents">')
    expect(normalizedChatSource).toContain('pet.cancelSummon() router.push(`/chat/${threadId}`)')
  })

  it('cancels from waiting on Escape and removes on cancel or selection', () => {
    const store = useCampusPetStore()
    store.beginSummon()
    expect(store.phase).toBe('waiting')
    expect(store.cancelSummon()).toBe(true)
    expect(store.phase).toBe('idle')
    expect(store.summonOrigin).toBeNull()

    store.beginSummon()
    store.showPicker()
    expect(store.cancelSummon()).toBe(true)
    expect(store.phase).toBe('idle')

    store.beginSummon()
    store.showPicker()
    expect(store.summon('akita')).toBe(true)
    expect(store.phase).toBe('idle')
    expect(store.summonOrigin).toBeNull()
    expect(store.currentForm).toBe('akita')
    expect(normalizedChatSource).toContain("if (pet.phase !== 'idle') { cancelCampusPetPicker()")
    expect(normalizedChatSource).toContain('function selectCampusPet(form) { clearPetSummonTimer() pet.summon(form)')
    expect(normalizedChatSource).toContain('function cancelCampusPetPicker() { clearPetSummonTimer() pet.cancelSummon()')
  })

  it('uses the six §12-4 SVGs without changing their markup', () => {
    for (const form of CAMPUS_PET_FORMS) {
      const marker = `<svg class="campus-pet campus-pet--${form.id}"`
      const start = previewSource.indexOf(marker)
      const end = previewSource.indexOf('</svg>', start)
      const expectedSvg = previewSource.slice(start, end + 6).replace(/^ {4}/gm, '')
      expect(CAMPUS_PET_SVGS[form.id]).toBe(expectedSvg)
    }
  })
})

describe('FR-41 §11-3 form changes', () => {
  it('unlocks on selection and replays summoning for different and current forms', () => {
    const storage = createMemoryStorage()
    vi.stubGlobal('localStorage', storage)
    const store = useCampusPetStore()
    store.beginSummon()
    store.showPicker()

    expect(store.summon('robo')).toBe(true)
    expect(store.unlocked).toBe(true)
    expect(store.visible).toBe(true)
    expect(store.currentForm).toBe('robo')
    expect(store.phase).toBe('idle')
    expect(store.summonRevision).toBe(1)

    store.beginSummon()
    store.showPicker()
    store.summon('robo')
    expect(store.currentForm).toBe('robo')
    expect(store.summonRevision).toBe(2)

    store.beginSummon()
    store.showPicker()
    store.summon('namahage')
    expect(store.currentForm).toBe('namahage')
    expect(store.summonRevision).toBe(3)
    expect(normalizedPetSource).toContain('() => pet.summonRevision')
    expect(campusPetSource).toContain('showSmoke()')
  })
})

describe('FR-41 §11-4 agent-linked state transitions', () => {
  it('prioritizes summoning/clarify/thinking/done and returns to idle after four seconds', () => {
    expect(resolveCampusPetState({ summoning: false, clarification: false, sending: false, done: false })).toBe('idle')
    expect(resolveCampusPetState({ summoning: false, clarification: false, sending: true, done: false })).toBe('thinking')
    expect(resolveCampusPetState({ summoning: false, clarification: true, sending: true, done: true })).toBe('clarify')
    expect(resolveCampusPetState({ summoning: false, clarification: false, sending: false, done: true })).toBe('done')
    expect(resolveCampusPetState({ summoning: true, clarification: true, sending: true, done: true })).toBe('summoning')
    expect(normalizedPetSource).toContain('() => chat.isSending')
    expect(normalizedPetSource).toContain('doneActive.value = true doneTimer = window.setTimeout(() => { doneActive.value = false doneTimer = null }, 4000)')
  })
})

describe('FR-41 §11-5 pointer drag and tap handling', () => {
  it('applies pointer thresholds, clamps all boundaries, and round-trips stored ratios', () => {
    expect(pointerDragThreshold('touch')).toBe(6)
    expect(pointerDragThreshold('mouse')).toBe(4)

    const layerRect = { left: 0, top: 0, right: 300, bottom: 500, width: 300, height: 500 }
    const baseRect = { left: 240, top: 350, right: 296, bottom: 406, width: 56, height: 56 }
    expect(clampCampusPetTranslation({
      baseRect,
      layerRect,
      tx: 100,
      ty: 100,
      topInset: 56,
      sideInset: 4,
      bottomClearance: 100,
    })).toEqual({ tx: 0, ty: -6 })
    expect(clampCampusPetTranslation({
      baseRect,
      layerRect,
      tx: -500,
      ty: -500,
      topInset: 56,
      sideInset: 4,
      bottomClearance: 100,
    })).toEqual({ tx: -236, ty: -294 })

    const pos = { xr: 0.5, yr: 0.5 }
    const restored = translationFromPositionRatio({ pos, baseRect, layerRect })
    const movedRect = {
      ...baseRect,
      left: baseRect.left + restored.tx,
      right: baseRect.right + restored.tx,
      top: baseRect.top + restored.ty,
      bottom: baseRect.bottom + restored.ty,
    }
    expect(positionRatioFromRects(movedRect, layerRect)).toEqual(pos)
    expect(normalizedPetSource).toContain('buttonRef.value?.setPointerCapture?.(event.pointerId)')
    expect(campusPetSource).toContain('buttonRef.value.style.transform = `translate3d(${translation.tx}px, ${translation.ty}px, 0)`')
    expect(normalizedPetSource).toContain("|| pet.phase !== 'idle'" )
  })

  it('uses every form-specific tap ratio without allowing a double-click action', () => {
    expect(chooseCampusPetReaction('robo', 0.49)).toBe('spark')
    expect(chooseCampusPetReaction('robo', 0.5)).toBe('nod')
    expect(chooseCampusPetReaction('akita', 0.44)).toBe('peek')
    expect(chooseCampusPetReaction('gotenmari', 0.84)).toBe('peek')
    expect(chooseCampusPetReaction('namahage', 0.54)).toBe('spark')
    expect(chooseCampusPetReaction('yatagarasu', 0.8)).toBe('nod')
    expect(campusPetSource).toContain('@dblclick.prevent')
    expect(normalizedPetSource).toContain('now - lastTapAt <= 300')
  })
})

describe('FR-41 §11-6 v1.1 persistence', () => {
  it('fills defaults, ignores seenForms, restores position, toggles visibility, and survives logout', () => {
    const legacyValue = {
      unlocked: true,
      visible: false,
      currentForm: 'akita',
      pos: { xr: 0.2, yr: 0.8 },
      seenForms: ['robo', 'akita'],
      unknown: 'ignored',
    }
    const storage = createMemoryStorage({
      [CAMPUS_PET_STORAGE_KEY]: JSON.stringify(legacyValue),
    })
    vi.stubGlobal('localStorage', storage)

    expect(loadCampusPetState()).toEqual({
      unlocked: true,
      visible: false,
      currentForm: 'akita',
      pos: { xr: 0.2, yr: 0.8 },
    })
    expect(loadCampusPetState(createMemoryStorage())).toEqual(createDefaultCampusPetState())

    const store = useCampusPetStore()
    store.toggleVisible()
    expect(store.visible).toBe(true)
    store.setPosition({ xr: 0.25, yr: 0.75 })
    const saved = JSON.parse(storage.value(CAMPUS_PET_STORAGE_KEY))
    expect(saved).toEqual({
      unlocked: true,
      visible: true,
      currentForm: 'akita',
      pos: { xr: 0.25, yr: 0.75 },
    })
    expect(Object.keys(saved)).toEqual(['unlocked', 'visible', 'currentForm', 'pos'])
    expect(normalizedChatSource).toContain('function logout() { clearPetSummonTimer() pet.cancelSummon() auth.clearSession() chat.reset()')
    expect(chatViewSource).not.toContain(`removeItem('${CAMPUS_PET_STORAGE_KEY}')`)
  })

  it('restores a saved ratio from a clean translation after visible off/on remount', () => {
    const applySource = campusPetSource.match(
      /function applyStoredPosition\(\) \{[\s\S]*?\n\}/,
    )?.[0]
    expect(applySource).toContain('if (dragging.value || !buttonRef.value || !layerRef.value)')
    expect(applySource.indexOf('updateTranslation({ tx: 0, ty: 0 })')).toBeLessThan(
      applySource.indexOf('const baseRect = baseButtonRect()'),
    )

    const pos = { xr: 0.581, yr: 0.149 }
    const layerRect = { left: 0, top: 0, right: 390, bottom: 800, width: 390, height: 800 }
    const remountedRect = { left: 310, top: 670, right: 366, bottom: 726, width: 56, height: 56 }
    let staleTranslation = { tx: -123, ty: -618 }
    const measureBaseRect = () => ({
      left: remountedRect.left - staleTranslation.tx,
      right: remountedRect.right - staleTranslation.tx,
      top: remountedRect.top - staleTranslation.ty,
      bottom: remountedRect.bottom - staleTranslation.ty,
      width: remountedRect.width,
      height: remountedRect.height,
    })

    staleTranslation = { tx: 0, ty: 0 }
    const cleanBaseRect = measureBaseRect()
    const restored = translationFromPositionRatio({ pos, baseRect: cleanBaseRect, layerRect })
    const restoredRect = {
      ...cleanBaseRect,
      left: cleanBaseRect.left + restored.tx,
      right: cleanBaseRect.right + restored.tx,
      top: cleanBaseRect.top + restored.ty,
      bottom: cleanBaseRect.bottom + restored.ty,
    }
    const restoredPos = positionRatioFromRects(restoredRect, layerRect)
    expect(restoredPos.xr).toBeCloseTo(pos.xr)
    expect(restoredPos.yr).toBeCloseTo(pos.yr)
  })

  it('does not throw when storage is unavailable or malformed', () => {
    const brokenStorage = {
      getItem: () => '{broken',
      setItem: () => { throw new Error('blocked') },
    }
    expect(loadCampusPetState(brokenStorage)).toEqual(createDefaultCampusPetState())
    expect(() => saveCampusPetState(createDefaultCampusPetState(), brokenStorage)).not.toThrow()
  })
})

describe('FR-41 §11-7 reduced motion', () => {
  it('contains the specified replacements for pet, smoke, picker, about, and settling motion', () => {
    expect(petCssSource.match(/@media \(prefers-reduced-motion: reduce\)/g)?.length).toBeGreaterThanOrEqual(4)
    expect(petCssSource).toContain('.campus-pet[data-state="summoning"] .pet-rig')
    expect(petCssSource).toContain('animation: campus_pet_smoke_reduce 220ms ease-out both !important;')
    expect(pickerSource).toContain('.campus-pet-picker__option:active')
    expect(pickerSource).toContain('.campus-pet-picker__figure::after')
    expect(pickerSource).toContain('animation: campus_pet_picker_fade 220ms ease-out both !important;')
    expect(petCssSource).toContain('.about-pet-toggle__knob')
    expect(petCssSource).toContain('.campus-pet-button[data-settling="true"] .campus-pet')
    expect(petCssSource).toContain('animation: none;')
  })
})

describe('FR-41 §11-8 v1.3 names and About guide', () => {
  it('uses the finalized names and exact descriptions as one shared source', () => {
    expect(CAMPUS_PET_FORMS).toEqual([
      {
        id: 'robo',
        name: 'ぴこ',
        description: 'APU-Navi の AI エージェントから生まれた分身。質問がとどくと、耳のフィンを光らせて一緒に考えてくれる。',
      },
      {
        id: 'sarutahiko',
        name: '猿田彦',
        description: '日本神話で道をひらく“導きの神”。キャンパスを案内するこのアプリの、たのもしい道案内役。',
      },
      {
        id: 'akita',
        name: 'こまち',
        description: '秋田生まれの秋田犬の子犬。人なつっこくて、こたえを待つ間もしっぽをふって寄りそってくれる。',
      },
      {
        id: 'gotenmari',
        name: 'てまりん',
        description: '由利本荘のつるし飾り「本荘ごてんまり」から生まれた手まりの妖精。じまんの刺繍でみんなを和ませる。',
      },
      {
        id: 'namahage',
        name: 'なまはげ',
        description: '秋田の来訪神・なまはげ。こわい顔はやる気の証。なまけ心にカツを入れて、探しものを応援してくれる。',
        rare: true,
      },
      {
        id: 'yatagarasu',
        name: '八咫烏',
        description: '三本足の導きの神使。開発メンバー・小川春翔さんのシステム「八咫烏」から名をうけついだ、稲妻をまとう守り神。',
      },
    ])
    expect(pickerSource).toContain('{{ form.name }}')
    expect(normalizedChatSource).toContain('<li v-for="form in CAMPUS_PET_FORMS" :key="form.id" class="about-pet-guide__row">')
    expect(normalizedChatSource).toContain('<span class="about-pet-guide__name">{{ form.name }}</span>')
    expect(normalizedChatSource).toContain('<span class="about-pet-guide__desc">{{ form.description }}</span>')
  })

  it('branches the About disclosure between the hint and six-entry guide', () => {
    expect(normalizedChatSource).toContain('const hasCampusPetCompanion = computed(() => Boolean(pet.unlocked && pet.currentForm))')
    expect(normalizedChatSource).toContain('<div v-if="hasCampusPetCompanion && aboutPetHintOpen" class="about-pet-guide campus-pet-host">')
    expect(normalizedChatSource).toContain('<p v-if="!hasCampusPetCompanion" class="about-pet-hint" :hidden="!aboutPetHintOpen">')
    expect(normalizedChatSource).toContain(':aria-expanded="aboutPetHintOpen"')
    expect(normalizedChatSource).toContain('if (dialog.value?.kind === \'about\') { aboutPetHintOpen.value = false')
    expect(chatViewSource).toContain('このコたちに特別な機能はありません。となりで一緒に待ってくれる、癒し担当です。ペットをタップすると、仲間をえらび直せます。')
    expect(petCssSource).toContain('.about-pet-guide__figure')
    expect(petCssSource).toContain('width: 2.25rem;')
  })
})

describe('FR-41 §11-9 v1.4 pet tap picker route', () => {
  it('opens picking directly with a pet origin and resets it on every exit', () => {
    const chat = useChatStore()
    const store = useCampusPetStore()
    const sendMessage = vi.spyOn(chat, 'sendMessage')
    const chatStateBefore = JSON.stringify(chat.$state)

    expect(store.openPickerDirect()).toBe(true)
    expect(store.phase).toBe('picking')
    expect(store.summonOrigin).toBe('pet')
    expect(store.summonRunId).toBe(1)
    expect(store.showPicker()).toBe(false)
    expect(store.phase).not.toBe('waiting')
    expect(JSON.stringify(chat.$state)).toBe(chatStateBefore)
    expect(sendMessage).not.toHaveBeenCalled()

    expect(store.cancelSummon()).toBe(true)
    expect(store.phase).toBe('idle')
    expect(store.summonOrigin).toBeNull()

    store.openPickerDirect()
    expect(store.summon('robo')).toBe(true)
    expect(store.phase).toBe('idle')
    expect(store.summonOrigin).toBeNull()
  })

  it('keeps the reaction but blocks direct picking while normal sending is unavailable', () => {
    const available = {
      isSending: false,
      isOriginSelectionPending: false,
      isClarificationPending: false,
    }
    expect(canOpenCampusPetPickerFromTap(available)).toBe(true)
    expect(canOpenCampusPetPickerFromTap({ ...available, isSending: true })).toBe(false)
    expect(canOpenCampusPetPickerFromTap({ ...available, isOriginSelectionPending: true })).toBe(false)
    expect(canOpenCampusPetPickerFromTap({ ...available, isClarificationPending: true })).toBe(false)

    expect(normalizedPetSource).toContain('tapTimer = window.setTimeout(() => { playReaction() if (canOpenCampusPetPickerFromTap(chat)) { pet.openPickerDirect() }')
    expect(normalizedPetSource).toContain('if (protectControls.value || pointerSession) { return }')
  })

  it('hides the passphrase bubble and scrolls the direct apparition with the shared exits', () => {
    expect(normalizedChatSource).toContain("v-if=\"pet.summonOrigin === 'passphrase'\"")
    expect(normalizedChatSource).toContain("if (pet.phase === 'picking' && pet.summonOrigin === 'pet') { pendingScrollBehavior = 'smooth' scrollToBottom('smooth')")
    expect(normalizedChatSource).toContain("'composer-shell--pet-locked': pet.phase !== 'idle'")
    expect(normalizedChatSource).toContain('function cancelCampusPetPicker() { clearPetSummonTimer() pet.cancelSummon()')
    expect(normalizedChatSource).toContain('function logout() { clearPetSummonTimer() pet.cancelSummon()')
    expect(normalizedChatSource).toContain('pet.cancelSummon() router.push(`/chat/${threadId}`)')
  })
})

describe('FR-41 §11-10 existing frontend regression surface', () => {
  it('keeps the existing composer, clarification, map, loading, and About content paths present', () => {
    expect(normalizedChatSource).toContain("'composer-shell--origin-locked': chat.isOriginSelectionPending || chat.isClarificationPending")
    expect(normalizedChatSource).toContain('<ClarificationCard v-if="message.clarificationActive"')
    expect(normalizedChatSource).toContain('<MapCard v-if="message.map"')
    expect(normalizedChatSource).toContain('<LoadingSpinnerV5')
    expect(normalizedChatSource).toContain('APU-Navi は、秋田県立大学 サイバーフィジカルシステム研究室【CPS Lab】によって開発されました！')
  })
})
