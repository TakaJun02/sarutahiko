export const EMPTY_GREETING_VARIANTS = Object.freeze([
  Object.freeze({
    id: 'ask-anything',
    usesName: true,
    before: '',
    nameSuffix: 'さん、',
    after: 'なんでも聞いてください',
    fallback: 'なんでも聞いてください',
  }),
  Object.freeze({
    id: 'where-to-start',
    usesName: false,
    before: '',
    nameSuffix: '',
    after: '',
    fallback: '何から始めますか？',
  }),
  Object.freeze({
    id: 'get-started',
    usesName: true,
    before: '',
    nameSuffix: 'さん、',
    after: 'さっそく始めましょう',
    fallback: 'さっそく始めましょう',
  }),
  Object.freeze({
    id: 'what-to-know',
    usesName: false,
    before: '',
    nameSuffix: '',
    after: '',
    fallback: '今日はどんなことを知りたいですか？',
  }),
  Object.freeze({
    id: 'welcome',
    usesName: true,
    before: 'ようこそ、',
    nameSuffix: 'さん',
    after: '',
    fallback: 'ようこそ',
  }),
])

export function selectGreetingVariant(previousId, random = Math.random) {
  const candidates = EMPTY_GREETING_VARIANTS.filter((variant) => variant.id !== previousId)
  const pool = candidates.length ? candidates : EMPTY_GREETING_VARIANTS
  const sampledValue = Number(random())
  const normalizedValue = Number.isFinite(sampledValue)
    ? Math.min(Math.max(sampledValue, 0), 0.999999)
    : 0
  return pool[Math.floor(normalizedValue * pool.length)]
}

export function splitGreetingName(name, protectedLength = 2) {
  const characters = Array.from(name || '')
  const safeProtectedLength = Math.max(0, Math.min(protectedLength, characters.length))
  const tailStart = characters.length - safeProtectedLength
  return {
    head: characters.slice(0, tailStart).join(''),
    tail: characters.slice(tailStart).join(''),
  }
}

export function buildGreetingLines(variant, name) {
  if (!variant.usesName || !name) {
    return [{ type: 'phrase', text: variant.fallback }]
  }

  const nameLine = { type: 'name', text: `${name}${variant.nameSuffix}` }
  return [
    variant.before ? { type: 'phrase', text: variant.before } : null,
    nameLine,
    variant.after ? { type: 'phrase', text: variant.after } : null,
  ].filter(Boolean)
}
