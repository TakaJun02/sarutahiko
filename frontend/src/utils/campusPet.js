export const CAMPUS_PET_STORAGE_KEY = 'campus-guide-pet'
export const CAMPUS_PET_PASSPHRASE = 'ペットを呼び出す'

export const CAMPUS_PET_FORMS = Object.freeze([
  { id: 'robo', name: 'ぴこ' },
  { id: 'sarutahiko', name: 'みちかぜ' },
  { id: 'akita', name: 'こまち' },
  { id: 'gotenmari', name: 'てまりん' },
  { id: 'namahage', name: 'ガオウ', rare: true },
  { id: 'yatagarasu', name: '八咫烏' },
])

const FORM_IDS = new Set(CAMPUS_PET_FORMS.map((form) => form.id))
const DEFAULT_STORAGE = Symbol('default-campus-pet-storage')

const REACTION_WEIGHTS = Object.freeze({
  robo: [['spark', 0.5], ['nod', 0.3], ['peek', 0.2]],
  sarutahiko: [['nod', 0.45], ['spark', 0.35], ['peek', 0.2]],
  akita: [['peek', 0.45], ['spark', 0.35], ['nod', 0.2]],
  gotenmari: [['spark', 0.45], ['peek', 0.4], ['nod', 0.15]],
  namahage: [['spark', 0.55], ['peek', 0.3], ['nod', 0.15]],
  yatagarasu: [['spark', 0.55], ['peek', 0.25], ['nod', 0.2]],
})

export function createDefaultCampusPetState() {
  return {
    unlocked: false,
    visible: true,
    currentForm: null,
    pos: null,
  }
}

export function isCampusPetPassphrase(text) {
  if (typeof text !== 'string') {
    return false
  }
  const normalized = text.trim().normalize('NFKC').replace(/[!！。]+$/u, '')
  return normalized === CAMPUS_PET_PASSPHRASE
}

function isValidPosition(pos) {
  return (
    pos
    && Number.isFinite(pos.xr)
    && Number.isFinite(pos.yr)
    && pos.xr >= 0
    && pos.xr <= 1
    && pos.yr >= 0
    && pos.yr <= 1
  )
}

export function sanitizeCampusPetState(value) {
  const defaults = createDefaultCampusPetState()
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return defaults
  }
  return {
    unlocked: typeof value.unlocked === 'boolean' ? value.unlocked : defaults.unlocked,
    visible: typeof value.visible === 'boolean' ? value.visible : defaults.visible,
    currentForm: FORM_IDS.has(value.currentForm) ? value.currentForm : defaults.currentForm,
    pos: isValidPosition(value.pos) ? { xr: value.pos.xr, yr: value.pos.yr } : defaults.pos,
  }
}

function resolveStorage(storage) {
  if (storage !== DEFAULT_STORAGE) {
    return storage
  }
  try {
    return globalThis.localStorage
  } catch {
    return null
  }
}

export function loadCampusPetState(storage = DEFAULT_STORAGE) {
  const resolvedStorage = resolveStorage(storage)
  if (!resolvedStorage) {
    return createDefaultCampusPetState()
  }
  try {
    const raw = resolvedStorage.getItem(CAMPUS_PET_STORAGE_KEY)
    return raw ? sanitizeCampusPetState(JSON.parse(raw)) : createDefaultCampusPetState()
  } catch {
    return createDefaultCampusPetState()
  }
}

export function saveCampusPetState(state, storage = DEFAULT_STORAGE) {
  const value = sanitizeCampusPetState(state)
  const resolvedStorage = resolveStorage(storage)
  if (!resolvedStorage) {
    return value
  }
  try {
    resolvedStorage.setItem(CAMPUS_PET_STORAGE_KEY, JSON.stringify(value))
  } catch {
    // The in-memory pet remains usable when storage is unavailable.
  }
  return value
}

export function chooseCampusPetReaction(form, randomValue = Math.random()) {
  const weights = REACTION_WEIGHTS[form] || REACTION_WEIGHTS.robo
  const normalizedRandom = Math.min(0.999999, Math.max(0, Number(randomValue) || 0))
  let boundary = 0
  for (const [reaction, weight] of weights) {
    boundary += weight
    if (normalizedRandom < boundary) {
      return reaction
    }
  }
  return weights[weights.length - 1][0]
}

export function pointerDragThreshold(pointerType) {
  return pointerType === 'touch' ? 6 : 4
}

export function resolveCampusPetState({ summoning, clarification, sending, done }) {
  if (summoning) {
    return 'summoning'
  }
  if (clarification) {
    return 'clarify'
  }
  if (sending) {
    return 'thinking'
  }
  if (done) {
    return 'done'
  }
  return 'idle'
}

export function clampCampusPetTranslation({
  baseRect,
  layerRect,
  tx,
  ty,
  topInset = 56,
  sideInset = 4,
  bottomClearance = 100,
}) {
  const minTx = layerRect.left + sideInset - baseRect.left
  const maxTx = layerRect.right - sideInset - baseRect.right
  const minTy = layerRect.top + topInset - baseRect.top
  const maxTy = layerRect.bottom - bottomClearance - baseRect.bottom
  return {
    tx: Math.min(Math.max(tx, Math.min(minTx, maxTx)), Math.max(minTx, maxTx)),
    ty: Math.min(Math.max(ty, Math.min(minTy, maxTy)), Math.max(minTy, maxTy)),
  }
}

export function positionRatioFromRects(buttonRect, layerRect) {
  return {
    xr: Math.min(1, Math.max(0, (buttonRect.left + buttonRect.width / 2 - layerRect.left) / layerRect.width)),
    yr: Math.min(1, Math.max(0, (buttonRect.top + buttonRect.height / 2 - layerRect.top) / layerRect.height)),
  }
}

export function translationFromPositionRatio({ pos, baseRect, layerRect }) {
  return {
    tx: layerRect.left + layerRect.width * pos.xr - (baseRect.left + baseRect.width / 2),
    ty: layerRect.top + layerRect.height * pos.yr - (baseRect.top + baseRect.height / 2),
  }
}
