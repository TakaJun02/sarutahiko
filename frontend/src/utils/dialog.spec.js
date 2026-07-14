import { describe, expect, it } from 'vitest'

import { getDialogAriaLabel, getDialogInitialFocus } from './dialog'

describe('dialog presentation', () => {
  it.each([
    ['rename', 'スレッド名を変更', 'input'],
    ['delete', '会話を削除', 'close'],
    ['about', 'このアプリについて', 'close'],
  ])('defines the accessible label and safe initial focus for %s', (kind, label, focus) => {
    expect(getDialogAriaLabel(kind)).toBe(label)
    expect(getDialogInitialFocus(kind)).toBe(focus)
  })

  it('falls back to a close control for an unknown dialog kind', () => {
    expect(getDialogAriaLabel('unknown')).toBe('')
    expect(getDialogInitialFocus('unknown')).toBe('close')
  })
})
