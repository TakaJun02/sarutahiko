import { describe, expect, it } from 'vitest'

import {
  CAMPUS_EDGES,
  CAMPUS_MAP_FIT,
  CAMPUS_MAP_FULL_BOUNDS,
  CAMPUS_MAP_VIEWBOX,
  CAMPUS_NODES,
  destinationBadge,
  edgeBadgeText,
  edgePath,
  fitMapViewBox,
  fullMapViewBox,
} from './campusMap'

function parseViewBox(viewBox) {
  const [x, y, width, height] = viewBox.split(' ').map(Number)
  return { x, y, width, height }
}

describe('campus map presentation data', () => {
  it('contains exactly the eight real-map nodes and the remaining edges', () => {
    expect(CAMPUS_NODES.map((node) => node.id)).toEqual([
      'g1', 'g2', 'd', 'k', 'cafeteria', 'j', 'gym', 'o_minami',
    ])
    expect(CAMPUS_EDGES.map((edge) => edge.id)).toEqual([
      'E1', 'E2', 'E3', 'E4', 'E5', 'E6a', 'E6b', 'E6c',
      'E7', 'E8', 'E9', 'E10', 'E13', 'E14', 'E15',
    ])
  })

  it('uses the approved image anchors and keeps every pin inside the crop', () => {
    expect(Object.fromEntries(CAMPUS_NODES.map(({ id, x, y }) => [id, [x, y]]))).toEqual({
      g1: [222, 168],
      g2: [307, 168],
      d: [277, 88],
      k: [300, 400],
      cafeteria: [342, 320],
      j: [152, 160],
      gym: [383, 165],
      o_minami: [545, 160],
    })
    const [left, top, width, height] = CAMPUS_MAP_VIEWBOX.split(' ').map(Number)
    expect(CAMPUS_NODES.every(({ x, y }) => (
      x >= left && x <= left + width && y >= top && y <= top + height
    ))).toBe(true)
  })

  it('uses concise sign codes instead of exposing internal node ids', () => {
    expect(CAMPUS_NODES.map((node) => node.displayCode)).toEqual([
      'G1', 'G2', 'D', 'K', 'MC', 'J', 'GYM', 'O',
    ])
    expect(CAMPUS_NODES.every((node) => !node.displayCode.includes('_'))).toBe(true)
  })

  it('keeps every SVG node target at least 44px at the narrow mobile card scale', () => {
    const renderedTargetSize = 90 * (343 / CAMPUS_MAP_FULL_BOUNDS.width)
    expect(renderedTargetSize).toBeGreaterThanOrEqual(44)
  })

  it('fits a route to its relevant nodes and preserves the measured canvas aspect', () => {
    const mobileAspect = 343 / 352
    const route = {
      mode: 'route',
      destination: { node: 'd', room: 'D404', floor: null },
      path: { nodes: ['k', 'g1', 'd'], edges: ['E5', 'E1'] },
    }
    const fitted = parseViewBox(fitMapViewBox(route, mobileAspect))
    const full = parseViewBox(fullMapViewBox(mobileAspect))

    expect(fitted.width).toBeLessThan(full.width)
    expect(fitted.height).toBeLessThan(full.height)
    expect(fitted.width / fitted.height).toBeCloseTo(mobileAspect, 2)
    expect(fitted.x).toBeLessThan(222)
    expect(fitted.y).toBeLessThan(88)
    expect(fitted.x + fitted.width).toBeGreaterThan(300)
    expect(fitted.y + fitted.height).toBeGreaterThan(400)
  })

  it('enforces the minimum place crop and keeps ask-origin on the whole campus', () => {
    const mobileAspect = 343 / 352
    const place = parseViewBox(fitMapViewBox({
      mode: 'place',
      destination: { node: 'g1', room: 'GI512', floor: 5 },
    }, mobileAspect))
    const askOrigin = fitMapViewBox({ mode: 'ask_origin' }, mobileAspect)

    expect(place.width).toBeGreaterThanOrEqual(CAMPUS_MAP_FIT.minimumWidth)
    expect(place.height).toBeGreaterThanOrEqual(CAMPUS_MAP_FIT.minimumHeight)
    expect(askOrigin).toBe(fullMapViewBox(mobileAspect))
    expect(CAMPUS_MAP_VIEWBOX).toBe('82 24 581 500')
  })

  it('shows only sourced connector floors and walking minutes', () => {
    expect(edgeBadgeText(CAMPUS_EDGES[0])).toBe('4F 連絡通路')
    expect(edgeBadgeText(CAMPUS_EDGES.find((edge) => edge.id === 'E13'))).toBe('約15分')
    expect(edgeBadgeText(CAMPUS_EDGES.find((edge) => edge.id === 'E6a'))).toBe('')
    expect(edgePath(CAMPUS_EDGES[0])).toMatch(/^M /)
  })

  it('does not invent an unknown destination floor', () => {
    expect(destinationBadge({ room: 'D414', floor: 4 })).toBe('D414・4階')
    expect(destinationBadge({ room: 'D404', floor: null })).toBe('D404')
  })
})
