import { describe, expect, it } from 'vitest'
import { isEditableShortcutTarget } from '../src/utils/keyboard.js'

describe('keyboard shortcut target guard', () => {
  it('does not intercept shortcuts from form controls or editable descendants', () => {
    expect(isEditableShortcutTarget(document.createElement('input'))).toBe(true)
    expect(isEditableShortcutTarget(document.createElement('textarea'))).toBe(true)

    const editor = document.createElement('div')
    editor.setAttribute('contenteditable', 'true')
    const child = document.createElement('span')
    editor.append(child)
    expect(isEditableShortcutTarget(child)).toBe(true)
  })

  it('allows shortcuts from ordinary controls and page chrome', () => {
    expect(isEditableShortcutTarget(document.createElement('button'))).toBe(false)
    expect(isEditableShortcutTarget(document.body)).toBe(false)
    expect(isEditableShortcutTarget(null)).toBe(false)
  })
})
