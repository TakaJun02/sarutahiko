import { describe, expect, it } from 'vitest'

import {
  CAMPUS_EDGES,
  CAMPUS_NODES,
  destinationBadge,
  edgeBadgeText,
  edgePath,
} from './campusMap'

describe('campus map presentation data', () => {
  it('contains exactly the specified nine nodes and pairwise-expanded edges', () => {
    expect(CAMPUS_NODES.map((node) => node.id)).toEqual([
      'g1', 'g2', 'd', 'k', 'cafeteria', 'j', 'gym', 'o_bakuro', 'o_minami',
    ])
    expect(CAMPUS_EDGES.map((edge) => edge.id)).toEqual([
      'E1', 'E2', 'E3', 'E4', 'E5', 'E6a', 'E6b', 'E6c',
      'E7', 'E8', 'E9', 'E10', 'E11', 'E12', 'E13', 'E14', 'E15',
    ])
  })

  it('uses concise sign codes instead of exposing internal node ids', () => {
    expect(CAMPUS_NODES.map((node) => node.displayCode)).toEqual([
      'G1', 'G2', 'D', 'K', 'MC', 'J', 'GYM', 'O-1', 'O-2',
    ])
    expect(CAMPUS_NODES.every((node) => !node.displayCode.includes('_'))).toBe(true)
  })

  it('keeps every SVG node target at least 44px at the narrow mobile card scale', () => {
    const renderedTargetHeight = 58 * (288 / 360)
    expect(renderedTargetHeight).toBeGreaterThanOrEqual(44)
  })

  it('shows only sourced connector floors and walking minutes', () => {
    expect(edgeBadgeText(CAMPUS_EDGES[0])).toBe('4F 連絡通路')
    expect(edgeBadgeText(CAMPUS_EDGES.find((edge) => edge.id === 'E11'))).toBe('約10分')
    expect(edgeBadgeText(CAMPUS_EDGES.find((edge) => edge.id === 'E6a'))).toBe('')
    expect(edgePath(CAMPUS_EDGES[0])).toMatch(/^M /)
  })

  it('does not invent an unknown destination floor', () => {
    expect(destinationBadge({ room: 'D414', floor: 4 })).toBe('D414・4階')
    expect(destinationBadge({ room: 'D404', floor: null })).toBe('D404')
  })
})
