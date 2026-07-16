import { describe, expect, it } from 'vitest'

import {
  buildGreetingLines,
  EMPTY_GREETING_VARIANTS,
  selectGreetingVariant,
  splitGreetingName,
} from './emptyGreeting'

describe('selectGreetingVariant', () => {
  it('never selects the immediately previous greeting', () => {
    for (const previous of EMPTY_GREETING_VARIANTS) {
      expect(selectGreetingVariant(previous.id, () => 0.999999).id).not.toBe(previous.id)
    }
  })

  it('uses the full set when the previous id is unknown', () => {
    expect(selectGreetingVariant('unknown', () => 0).id).toBe(EMPTY_GREETING_VARIANTS[0].id)
  })
})

describe('splitGreetingName', () => {
  it.each([
    ['さくら', 'さ', 'くら'],
    ['あいうえおかきくけこさしすせそたちつてと', 'あいうえおかきくけこさしすせそたちつ', 'てと'],
    ['CampusGuideR1Mix2026', 'CampusGuideR1Mix20', '26'],
  ])('protects the end of %s with the honorific', (name, head, tail) => {
    expect(splitGreetingName(name)).toEqual({ head, tail })
  })
})

describe('buildGreetingLines', () => {
  const askAnything = EMPTY_GREETING_VARIANTS.find((variant) => variant.id === 'ask-anything')
  const welcome = EMPTY_GREETING_VARIANTS.find((variant) => variant.id === 'welcome')

  it.each([
    ['さくら', 3],
    ['Sol検収一号AB', 9],
    ['あいうえおかきくけこさしすせそたちつてと', 20],
  ])(
    'keeps the name and following phrase on separate lines for %s',
    (name, expectedLength) => {
      expect(Array.from(name)).toHaveLength(expectedLength)
      expect(buildGreetingLines(askAnything, name)).toEqual([
        { type: 'name', text: `${name}さん、` },
        { type: 'phrase', text: 'なんでも聞いてください' },
      ])
    },
  )

  it('keeps the welcome phrase above the name', () => {
    expect(buildGreetingLines(welcome, 'さくら')).toEqual([
      { type: 'phrase', text: 'ようこそ、' },
      { type: 'name', text: 'さくらさん' },
    ])
  })

  it('returns one wrappable phrase line when no name is used', () => {
    const variant = EMPTY_GREETING_VARIANTS.find((item) => item.id === 'what-to-know')
    expect(buildGreetingLines(variant, '')).toEqual([
      { type: 'phrase', text: '今日はどんなことを知りたいですか？' },
    ])
  })
})
