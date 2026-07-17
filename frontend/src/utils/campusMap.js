export const CAMPUS_NODES = Object.freeze([
  { id: 'g1', displayCode: 'G1', label: '学部棟Ⅰ', selectionLabel: '学部棟Ⅰ', x: 222, y: 168, groundFloor: 2 },
  { id: 'g2', displayCode: 'G2', label: '学部棟Ⅱ', selectionLabel: '学部棟Ⅱ', x: 307, y: 168, groundFloor: 2 },
  { id: 'd', displayCode: 'D', label: '大学院棟', selectionLabel: '大学院棟', x: 277, y: 88, groundFloor: 2 },
  { id: 'k', displayCode: 'K', label: '共通施設棟', selectionLabel: '共通施設棟（総合受付）', x: 300, y: 400, groundFloor: 1 },
  {
    id: 'cafeteria',
    displayCode: 'MC',
    label: 'メディア交流棟',
    selectionLabel: 'カフェテリア（食堂）',
    x: 342,
    y: 320,
    groundFloor: 1,
  },
  { id: 'j', displayCode: 'J', label: '特別実験棟', selectionLabel: '特別実験棟', x: 152, y: 160, groundFloor: 1 },
  { id: 'gym', displayCode: 'GYM', label: '体育館', selectionLabel: '体育館', x: 383, y: 165, groundFloor: 1 },
  {
    id: 'o_minami',
    displayCode: 'O',
    label: '屋外O 南側多目的広場',
    selectionLabel: '屋外O 南側多目的広場',
    x: 545,
    y: 160,
    groundFloor: null,
  },
])

export const CAMPUS_MAP_IMAGE_SIZE = Object.freeze({ width: 671, height: 720 })
export const CAMPUS_MAP_VIEWBOX = '90 40 581 460'

export const CAMPUS_EDGES = Object.freeze([
  { id: 'E1', from: 'g1', to: 'd', floor: 4, kind: 'connector', curve: -12, badge: [235, 117] },
  { id: 'E2', from: 'g1', to: 'd', floor: 2, kind: 'connector', curve: 12, badge: [258, 136] },
  { id: 'E3', from: 'g2', to: 'd', floor: 3, kind: 'connector', curve: 12, badge: [310, 120] },
  { id: 'E4', from: 'g2', to: 'd', floor: 2, kind: 'connector', curve: -12, badge: [282, 137] },
  { id: 'E5', from: 'k', to: 'g1', floor: 2, kind: 'indoor' },
  { id: 'E6a', from: 'g1', to: 'cafeteria', kind: 'front' },
  { id: 'E6b', from: 'g2', to: 'cafeteria', kind: 'front' },
  { id: 'E6c', from: 'g1', to: 'g2', kind: 'front' },
  { id: 'E7', from: 'cafeteria', to: 'gym', kind: 'path' },
  { id: 'E8', from: 'k', to: 'cafeteria', minutes: 10, kind: 'walk', curve: 14, badge: [348, 365] },
  { id: 'E9', from: 'k', to: 'j', minutes: 15, kind: 'walk', badge: [222, 289] },
  { id: 'E10', from: 'j', to: 'g1', minutes: 10, kind: 'walk', badge: [183, 207] },
  { id: 'E13', from: 'o_minami', to: 'k', minutes: 15, kind: 'walk', curve: 24, badge: [448, 304] },
  { id: 'E14', from: 'o_minami', to: 'cafeteria', minutes: 10, kind: 'walk', badge: [462, 260] },
  { id: 'E15', from: 'g1', to: 'o_minami', minutes: 15, kind: 'walk', curve: -24, badge: [389, 126] },
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
