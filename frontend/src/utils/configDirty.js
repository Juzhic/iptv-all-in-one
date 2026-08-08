export function hasConfigurationChanges({
  fileContent = '',
  savedFileContent = '',
  configLoaded = false,
  currentConfigFingerprint = '',
  savedConfigFingerprint = '',
} = {}) {
  return fileContent !== savedFileContent || Boolean(
    configLoaded && currentConfigFingerprint !== savedConfigFingerprint,
  )
}
