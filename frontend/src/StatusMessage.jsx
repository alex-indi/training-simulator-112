import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import PropTypes from 'prop-types'

import styles from './StatusMessage.module.css'

const messageOwners = new Map()
const dismissedMessages = new Set()

function statusViewport() {
  let viewport = document.getElementById('application-status-viewport')
  if (!viewport) {
    viewport = document.createElement('div')
    viewport.id = 'application-status-viewport'
    viewport.className = styles.viewport
    document.body.appendChild(viewport)
  }
  return viewport
}

function StatusMessage({ message, tone = 'info', duration = 5000, onDismiss }) {
  const owner = useRef(Symbol('status-message'))
  const previousKey = useRef('')
  const [visible, setVisible] = useState(false)
  const dismissRef = useRef(onDismiss)
  dismissRef.current = onDismiss

  useEffect(() => {
    const key = message ? `${tone}:${message}` : ''
    const previous = previousKey.current
    if (previous && previous !== key) {
      messageOwners.delete(previous)
      dismissedMessages.delete(previous)
    }
    previousKey.current = key

    if (!message) {
      setVisible(false)
      return undefined
    }

    const currentOwner = messageOwners.get(key)
    if (dismissedMessages.has(key) || (currentOwner && currentOwner !== owner.current)) {
      setVisible(false)
      return undefined
    }

    messageOwners.set(key, owner.current)
    setVisible(true)
    const timer = window.setTimeout(() => {
      dismissedMessages.add(key)
      setVisible(false)
      dismissRef.current?.()
    }, duration)
    return () => window.clearTimeout(timer)
  }, [duration, message, tone])

  if (!message || !visible) return null

  const dismiss = () => {
    dismissedMessages.add(`${tone}:${message}`)
    setVisible(false)
    dismissRef.current?.()
  }

  return createPortal(
    <div className={`${styles.message} ${styles[tone]}`} role={tone === 'error' ? 'alert' : 'status'}>
      <span>{message}</span>
      <button type="button" onClick={dismiss} aria-label="Закрыть уведомление">×</button>
    </div>,
    statusViewport(),
  )
}

StatusMessage.propTypes = {
  message: PropTypes.string,
  tone: PropTypes.oneOf(['info', 'success', 'warning', 'error']),
  duration: PropTypes.number,
  onDismiss: PropTypes.func,
}

export default StatusMessage
