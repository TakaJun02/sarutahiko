export const CAMPUS_NODES = Object.freeze([
  { id: 'g1', label: '学部棟Ⅰ', selectionLabel: '学部棟Ⅰ', x: 120, y: 104, groundFloor: 2 },
  { id: 'g2', label: '学部棟Ⅱ', selectionLabel: '学部棟Ⅱ', x: 240, y: 104, groundFloor: 2 },
  { id: 'd', label: '大学院棟', selectionLabel: '大学院棟', x: 180, y: 42, groundFloor: 2 },
  { id: 'k', label: '共通施設棟', selectionLabel: '共通施設棟（総合受付）', x: 52, y: 172, groundFloor: 1 },
  {
    id: 'cafeteria',
    label: 'メディア交流棟',
    lines: ['メディア', '交流棟'],
    selectionLabel: 'カフェテリア（食堂）',
    x: 180,
    y: 184,
    groundFloor: 1,
  },
  { id: 'j', label: '特別実験棟', selectionLabel: '特別実験棟', x: 38, y: 78, groundFloor: 1 },
  { id: 'gym', label: '体育館', selectionLabel: '体育館', x: 308, y: 184, groundFloor: 1 },
  {
    id: 'o_bakuro',
    label: '屋外O 暴露試験場',
    lines: ['O 暴露', '試験場'],
    selectionLabel: '屋外O 暴露試験場',
    x: 92,
    y: 278,
    groundFloor: null,
  },
  {
    id: 'o_minami',
    label: '屋外O 南側多目的広場',
    lines: ['O 南側', '多目的広場'],
    selectionLabel: '屋外O 南側多目的広場',
    x: 252,
    y: 278,
    groundFloor: null,
  },
])

export const CAMPUS_EDGES = Object.freeze([
  { id: 'E1', from: 'g1', to: 'd', floor: 4, kind: 'connector', curve: -8, badge: [139, 64] },
  { id: 'E2', from: 'g1', to: 'd', floor: 2, kind: 'connector', curve: 8, badge: [156, 83] },
  { id: 'E3', from: 'g2', to: 'd', floor: 3, kind: 'connector', curve: 8, badge: [221, 64] },
  { id: 'E4', from: 'g2', to: 'd', floor: 2, kind: 'connector', curve: -8, badge: [204, 83] },
  { id: 'E5', from: 'k', to: 'g1', floor: 2, kind: 'indoor' },
  { id: 'E6a', from: 'g1', to: 'cafeteria', kind: 'front' },
  { id: 'E6b', from: 'g2', to: 'cafeteria', kind: 'front' },
  { id: 'E6c', from: 'g1', to: 'g2', kind: 'front' },
  { id: 'E7', from: 'cafeteria', to: 'gym', kind: 'path' },
  { id: 'E8', from: 'k', to: 'cafeteria', minutes: 10, kind: 'walk', curve: 10, badge: [116, 190] },
  { id: 'E9', from: 'k', to: 'j', minutes: 15, kind: 'walk', badge: [25, 125] },
  { id: 'E10', from: 'j', to: 'g1', minutes: 10, kind: 'walk', badge: [79, 70] },
  { id: 'E11', from: 'g1', to: 'o_bakuro', minutes: 10, kind: 'walk', badge: [91, 218] },
  { id: 'E12', from: 'o_bakuro', to: 'o_minami', minutes: 15, kind: 'walk', badge: [172, 291] },
  { id: 'E13', from: 'o_minami', to: 'k', minutes: 15, kind: 'walk', curve: 18, badge: [147, 253] },
  { id: 'E14', from: 'o_minami', to: 'cafeteria', minutes: 10, kind: 'walk', badge: [233, 229] },
  { id: 'E15', from: 'g1', to: 'o_minami', minutes: 15, kind: 'walk', curve: -18, badge: [186, 205] },
])

const NODE_BY_ID = new Map(CAMPUS_NODES.map((node) => [node.id, node]))

export function edgePath(edge) {
  const start = NODE_BY_ID.get(edge.from)
  const end = NODE_BY_ID.get(edge.to)
  if (!start || !end) {
    return ''
  }
  if (!edge.curve) {
    return `M ${start.x} ${start.y} L ${end.x} ${end.y}`
  }
  const midX = (start.x + end.x) / 2
  const midY = (start.y + end.y) / 2
  const dx = end.x - start.x
  const dy = end.y - start.y
  const length = Math.hypot(dx, dy) || 1
  const controlX = midX + (-dy / length) * edge.curve
  const controlY = midY + (dx / length) * edge.curve
  return `M ${start.x} ${start.y} Q ${controlX} ${controlY} ${end.x} ${end.y}`
}

export function edgeBadgeText(edge) {
  if (edge.kind === 'connector' && edge.floor) {
    return `${edge.floor}F 連絡通路`
  }
  if (edge.minutes) {
    return `約${edge.minutes}分`
  }
  return ''
}

export function destinationBadge(destination) {
  if (!destination) {
    return ''
  }
  return [destination.room, destination.floor ? `${destination.floor}階` : '']
    .filter(Boolean)
    .join('・')
}
