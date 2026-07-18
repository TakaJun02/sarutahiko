import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('./LoadingSpinnerV5.vue', import.meta.url), 'utf8')

describe('LoadingSpinnerV5 live status runs', () => {
  it('keys the status transition by statusRunId instead of display text', () => {
    expect(source).toContain('statusRunId: {')
    expect(source).toContain(':key="props.statusRunId"')
    expect(source).not.toContain(':key="displayText"')
  })
})
