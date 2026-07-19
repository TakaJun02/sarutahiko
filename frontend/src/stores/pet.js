import { defineStore } from 'pinia'

import {
  CAMPUS_PET_FORMS,
  loadCampusPetState,
  saveCampusPetState,
} from '../utils/campusPet'

const FORM_IDS = new Set(CAMPUS_PET_FORMS.map((form) => form.id))

export const useCampusPetStore = defineStore('campus-pet', {
  state: () => ({
    ...loadCampusPetState(),
    phase: 'idle',
    summonRunId: 0,
    summonRevision: 0,
  }),
  actions: {
    persist() {
      saveCampusPetState({
        unlocked: this.unlocked,
        visible: this.visible,
        currentForm: this.currentForm,
        pos: this.pos,
      })
    },
    beginSummon() {
      if (this.phase !== 'idle') {
        return false
      }
      this.phase = 'waiting'
      this.summonRunId += 1
      return true
    },
    showPicker() {
      if (this.phase !== 'waiting') {
        return false
      }
      this.phase = 'picking'
      return true
    },
    cancelSummon() {
      if (this.phase === 'idle') {
        return false
      }
      this.phase = 'idle'
      return true
    },
    summon(form) {
      if (!FORM_IDS.has(form)) {
        return false
      }
      this.unlocked = true
      this.visible = true
      this.currentForm = form
      this.phase = 'idle'
      this.summonRevision += 1
      this.persist()
      return true
    },
    toggleVisible() {
      if (!this.unlocked || !this.currentForm) {
        return
      }
      this.visible = !this.visible
      this.persist()
    },
    setPosition(pos) {
      this.pos = pos
      this.persist()
    },
  },
})
