import { describe, expect, it } from 'vitest'

import { advanceRevealCount } from './revealPacing'

describe('advanceRevealCount', () => {
  it('advances a small backlog by at least one character without passing total', () => {
    const next = advanceRevealCount({ revealed: 0, total: 3, dtSeconds: 0.016 })

    expect(next).toBeGreaterThan(0)
    expect(next).toBeLessThanOrEqual(3)
  })

  it('uses the drain rate for a large backlog', () => {
    expect(advanceRevealCount({ revealed: 0, total: 900, dtSeconds: 0.1 })).toBe(100)
  })

  it('clamps large frame deltas', () => {
    expect(advanceRevealCount({ revealed: 0, total: 900, dtSeconds: 5 })).toBe(100)
  })

  it('does not advance when there is no backlog', () => {
    expect(advanceRevealCount({ revealed: 120, total: 120, dtSeconds: 0.1 })).toBe(120)
  })
})
