import { describe, expect, it } from 'vitest'
import { hasConfigurationChanges } from '../src/utils/configDirty.js'

describe('configuration dirty guard', () => {
  it('detects unsaved text and loaded form changes', () => {
    expect(hasConfigurationChanges({ fileContent: 'new', savedFileContent: 'old' })).toBe(true)
    expect(hasConfigurationChanges({
      fileContent: 'same',
      savedFileContent: 'same',
      configLoaded: true,
      currentConfigFingerprint: '{"workers":20}',
      savedConfigFingerprint: '{"workers":10}',
    })).toBe(true)
  })

  it('does not block before the form is loaded or after both snapshots match', () => {
    expect(hasConfigurationChanges({
      configLoaded: false,
      currentConfigFingerprint: 'new',
      savedConfigFingerprint: 'old',
    })).toBe(false)
    expect(hasConfigurationChanges({
      fileContent: 'same',
      savedFileContent: 'same',
      configLoaded: true,
      currentConfigFingerprint: 'same',
      savedConfigFingerprint: 'same',
    })).toBe(false)
  })
})
