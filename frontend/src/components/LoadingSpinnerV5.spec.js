import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('./LoadingSpinnerV5.vue', import.meta.url), 'utf8')

describe('LoadingSpinnerV5 live status runs', () => {
  it('keys the status transition by statusRunId instead of display text', () => {
    expect(source).toContain('statusRunId: {')
    expect(source).toContain(':key="props.statusRunId"')
    expect(source).not.toContain(':key="displayText"')
  })

  it('falls back to the generate theme for additive backend status steps', () => {
    expect(source).toContain('STEP_THEMES[props.statusStep] || STEP_THEMES.generate')
  })

  it('accepts elicit mode and renders the body slot outside pending mode', () => {
    expect(source).toContain("['pending', 'settled', 'elicit'].includes(value)")
    expect(source).toContain("const isPending = computed(() => props.mode === 'pending')")
    expect(source).toContain('<p v-if="isPending"')
    expect(source).toContain('<div v-if="!isPending" class="aurora-ring-v5__settled">')
  })

  it('keeps elicit geometry settled-sized without applying the settled ring fade', () => {
    expect(source).toContain('.aurora-ring-v5--settled,\n.aurora-ring-v5--elicit')
    expect(source).toContain('.aurora-ring-v5--settled .aurora-ring-v5__ring')
    expect(source).toContain('.aurora-ring-v5--settled .aurora-ring-v5__icon')
    expect(source).not.toContain('.aurora-ring-v5--elicit .aurora-ring-v5__ring')
    expect(source).not.toContain('.aurora-ring-v5--elicit .aurora-ring-v5__icon')
  })
})
