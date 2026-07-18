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
    pickerOpen: false,
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
    openPicker() {
      this.pickerOpen = true
    },
    closePicker() {
      this.pickerOpen = false
    },
    summon(form) {
      if (!FORM_IDS.has(form)) {
        return false
      }
      this.unlocked = true
      this.visible = true
      this.currentForm = form
      this.pickerOpen = false
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
