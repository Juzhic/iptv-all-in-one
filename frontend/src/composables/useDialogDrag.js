import { onMounted, onBeforeUnmount } from 'vue'

export function useDialogDrag() {
  let dragging = false
  let dragTarget = null
  let startX = 0
  let startY = 0
  let startTranslateX = 0
  let startTranslateY = 0

  function getTranslate(el) {
    const m = (el.style.transform || '').match(/translate\(([-\d.]+)px,\s*([-\d.]+)px\)/)
    return m ? { x: +m[1], y: +m[2] } : { x: 0, y: 0 }
  }

  function onDocMouseDown(e) {
    if (e.button !== 0) return
    const header = e.target.closest('.t-dialog__header')
    if (!header) return
    if (e.target.closest('.t-dialog__close-btn, .t-dialog__close, [class*="dialog__close"]')) return

    const dialog = header.closest('.t-dialog')
    if (!dialog) return
    const ctx = dialog.closest('.t-dialog__ctx') || dialog.parentElement
    if (!ctx) return
    const position = ctx.querySelector('.t-dialog__position') || dialog.parentElement
    if (!position) return

    dragging = true
    dragTarget = position
    startX = e.clientX
    startY = e.clientY
    const { x, y } = getTranslate(position)
    startTranslateX = x
    startTranslateY = y

    e.preventDefault()
    document.body.style.userSelect = 'none'

    document.addEventListener('mousemove', onDocMouseMove, true)
    document.addEventListener('mouseup', onDocMouseUp, true)
  }

  function onDocMouseMove(e) {
    if (!dragging || !dragTarget) return
    const dx = e.clientX - startX
    const dy = e.clientY - startY
    dragTarget.style.transform = `translate(${startTranslateX + dx}px, ${startTranslateY + dy}px)`
  }

  function onDocMouseUp() {
    dragging = false
    dragTarget = null
    document.body.style.userSelect = ''
    document.removeEventListener('mousemove', onDocMouseMove, true)
    document.removeEventListener('mouseup', onDocMouseUp, true)
  }

  onMounted(() => {
    document.addEventListener('mousedown', onDocMouseDown, true)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('mousedown', onDocMouseDown, true)
    document.removeEventListener('mousemove', onDocMouseMove, true)
    document.removeEventListener('mouseup', onDocMouseUp, true)
  })
}
