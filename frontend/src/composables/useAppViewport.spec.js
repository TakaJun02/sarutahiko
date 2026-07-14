import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const lifecycle = vi.hoisted(() => ({
  mounted: null,
  beforeUnmount: null,
}))

vi.mock('vue', () => ({
  ref: (value) => ({ value }),
  onMounted: (callback) => {
    lifecycle.mounted = callback
  },
  onBeforeUnmount: (callback) => {
    lifecycle.beforeUnmount = callback
  },
}))

import { useAppViewport, useViewportState } from './useAppViewport'

function createEventTarget() {
  const listeners = new Map()
  return {
    addEventListener: vi.fn((type, callback) => listeners.set(type, callback)),
    removeEventListener: vi.fn((type, callback) => {
      if (listeners.get(type) === callback) {
        listeners.delete(type)
      }
    }),
    dispatch(type) {
      listeners.get(type)?.()
    },
    listener(type) {
      return listeners.get(type)
    },
  }
}

function installDomMocks({ withVisualViewport = true, coarsePointer = true } = {}) {
  const visualViewport = Object.assign(createEventTarget(), {
    height: 844,
    width: 390,
    scale: 1,
  })
  const windowTarget = createEventTarget()
  const windowMock = Object.assign(windowTarget, {
    matchMedia: vi.fn(() => ({ matches: coarsePointer })),
    scrollY: 0,
    scrollTo: vi.fn(),
  })
  if (withVisualViewport) {
    windowMock.visualViewport = visualViewport
  }

  const setProperty = vi.fn()
  const attributes = new Map()
  const documentElement = {
    style: { setProperty },
    getAttribute: vi.fn((name) => attributes.get(name) ?? null),
    hasAttribute: vi.fn((name) => attributes.has(name)),
    removeAttribute: vi.fn((name) => attributes.delete(name)),
    setAttribute: vi.fn((name, value) => attributes.set(name, value)),
  }
  vi.stubGlobal('window', windowMock)
  vi.stubGlobal('document', {
    documentElement,
  })

  return { documentElement, setProperty, visualViewport, windowMock }
}

function mountComposable() {
  useAppViewport()
  lifecycle.mounted()
  return useViewportState()
}

describe('useAppViewport', () => {
  beforeEach(() => {
    lifecycle.mounted = null
    lifecycle.beforeUnmount = null
  })

  afterEach(() => {
    lifecycle.beforeUnmount?.()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('sets --app-height from visualViewport when mounted', () => {
    const { setProperty } = installDomMocks()

    const viewportState = mountComposable()

    expect(setProperty).toHaveBeenCalledWith('--app-height', '844px')
    expect(viewportState.appHeight.value).toBe(844)
  })

  it('updates the app height and resets window panning on resize', () => {
    const { setProperty, visualViewport, windowMock } = installDomMocks()
    mountComposable()
    visualViewport.height = 620
    windowMock.scrollY = 48

    visualViewport.dispatch('resize')

    expect(setProperty).toHaveBeenLastCalledWith('--app-height', '620px')
    expect(windowMock.scrollTo).toHaveBeenCalledWith(0, 0)
  })

  it('does not update the app height while pinch zoomed', () => {
    const { documentElement, setProperty, visualViewport } = installDomMocks()
    const viewportState = mountComposable()
    visualViewport.height = 620
    visualViewport.dispatch('resize')

    expect(viewportState.keyboardOpen.value).toBe(true)
    expect(documentElement.getAttribute('data-keyboard')).toBe('open')

    visualViewport.height = 844
    visualViewport.scale = 2

    visualViewport.dispatch('resize')

    expect(setProperty).toHaveBeenCalledTimes(2)
    expect(setProperty).toHaveBeenLastCalledWith('--app-height', '620px')
    expect(viewportState.appHeight.value).toBe(620)
    expect(viewportState.keyboardOpen.value).toBe(true)
    expect(documentElement.getAttribute('data-keyboard')).toBe('open')
  })

  it('marks the keyboard open at a 150px height loss and closes it on recovery', () => {
    const { documentElement, visualViewport } = installDomMocks()
    const viewportState = mountComposable()

    visualViewport.height = 694
    visualViewport.dispatch('resize')

    expect(documentElement.getAttribute('data-keyboard')).toBe('open')
    expect(viewportState.keyboardOpen.value).toBe(true)

    visualViewport.height = 844
    visualViewport.dispatch('resize')

    expect(documentElement.hasAttribute('data-keyboard')).toBe(false)
    expect(viewportState.keyboardOpen.value).toBe(false)
  })

  it('does not detect a keyboard for fine pointers', () => {
    const { documentElement, visualViewport } = installDomMocks({ coarsePointer: false })
    const viewportState = mountComposable()

    visualViewport.height = 500
    visualViewport.dispatch('resize')

    expect(documentElement.hasAttribute('data-keyboard')).toBe(false)
    expect(viewportState.keyboardOpen.value).toBe(false)
  })

  it('resets the height baseline when the viewport width changes', () => {
    const { documentElement, visualViewport } = installDomMocks()
    const viewportState = mountComposable()

    visualViewport.width = 844
    visualViewport.height = 390
    visualViewport.dispatch('resize')

    expect(viewportState.appHeight.value).toBe(390)
    expect(viewportState.keyboardOpen.value).toBe(false)
    expect(documentElement.hasAttribute('data-keyboard')).toBe(false)
  })

  it('removes visualViewport and window listeners when unmounted', () => {
    const { documentElement, visualViewport, windowMock } = installDomMocks()
    const viewportState = mountComposable()
    const resizeListener = visualViewport.listener('resize')
    const scrollListener = windowMock.listener('scroll')

    visualViewport.height = 600
    visualViewport.dispatch('resize')
    expect(viewportState.keyboardOpen.value).toBe(true)

    lifecycle.beforeUnmount()

    expect(visualViewport.removeEventListener).toHaveBeenCalledWith('resize', resizeListener)
    expect(windowMock.removeEventListener).toHaveBeenCalledWith('scroll', scrollListener)
    expect(visualViewport.listener('resize')).toBeUndefined()
    expect(windowMock.listener('scroll')).toBeUndefined()
    expect(documentElement.hasAttribute('data-keyboard')).toBe(false)
    expect(viewportState.appHeight.value).toBeNull()
    expect(viewportState.keyboardOpen.value).toBe(false)
  })

  it('does nothing when visualViewport is unavailable', () => {
    const { setProperty, windowMock } = installDomMocks({ withVisualViewport: false })

    mountComposable()

    expect(setProperty).not.toHaveBeenCalled()
    expect(windowMock.addEventListener).not.toHaveBeenCalled()
  })
})
