const DIALOG_PRESENTATION = Object.freeze({
  rename: Object.freeze({
    ariaLabel: 'スレッド名を変更',
    initialFocus: 'input',
  }),
  delete: Object.freeze({
    ariaLabel: '会話を削除',
    initialFocus: 'close',
  }),
  about: Object.freeze({
    ariaLabel: 'このアプリについて',
    initialFocus: 'close',
  }),
})

export function getDialogAriaLabel(kind) {
  return DIALOG_PRESENTATION[kind]?.ariaLabel || ''
}

export function getDialogInitialFocus(kind) {
  return DIALOG_PRESENTATION[kind]?.initialFocus || 'close'
}
