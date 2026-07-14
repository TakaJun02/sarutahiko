import { onBeforeUnmount, onMounted } from 'vue'

export function useAppViewport() {
  let visualViewport = null

  function resetWindowScroll() {
    if (window.scrollY > 0) {
      window.scrollTo(0, 0)
    }
  }

  function syncAppHeight() {
    if (visualViewport.scale <= 1) {
      document.documentElement.style.setProperty('--app-height', `${visualViewport.height}px`)
    }
    resetWindowScroll()
  }

  onMounted(() => {
    visualViewport = window.visualViewport
    if (!visualViewport) {
      return
    }

    syncAppHeight()
    visualViewport.addEventListener('resize', syncAppHeight)
    window.addEventListener('scroll', resetWindowScroll)
  })

  onBeforeUnmount(() => {
    if (!visualViewport) {
      return
    }

    visualViewport.removeEventListener('resize', syncAppHeight)
    window.removeEventListener('scroll', resetWindowScroll)
  })
}
