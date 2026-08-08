export function isEditableShortcutTarget(target) {
  return Boolean(target?.closest?.(
    'input, textarea, select, [contenteditable]:not([contenteditable="false"])',
  ))
}
