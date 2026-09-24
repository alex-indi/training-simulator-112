import { useEffect, useRef, useState } from 'react'
import { io } from 'socket.io-client'
import PropTypes from 'prop-types'

import styles from './App.module.css'

const senderLabels = {
  DISPATCHER: 'Диспетчер ДДС',
  RESPONSE_UNIT: 'Старший группы',
  SYSTEM: 'Система',
}

function ResponseChat({ assignment, incidentNumber, username, apiUrl, requestJson, formatDateTime }) {
  const [messages, setMessages] = useState([])
  const [body, setBody] = useState('')
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef(null)
  const path = `/api/response/assignments/${assignment.id}`

  useEffect(() => {
    let active = true
    const refresh = () => requestJson(`${path}/messages`, username)
      .then((items) => { if (active) setMessages(items) })
      .catch((requestError) => { if (active) setError(requestError.message) })
    refresh()
    const socket = io(apiUrl, { auth: { username } })
    socket.on('response.message_created', (event) => {
      if (event.assignment_id === assignment.id) refresh()
    })
    socket.on('connect', refresh)
    return () => {
      active = false
      socket.disconnect()
    }
  }, [apiUrl, assignment.id, path, requestJson, username])

  useEffect(() => {
    if (!open) return
    endRef.current?.scrollIntoView({ block: 'end' })
    for (const message of messages) {
      if (message.sender_type === 'RESPONSE_UNIT' && !message.read_at) {
        requestJson(`/api/response/messages/${message.id}/read`, username, { method: 'POST' })
          .then((updated) => setMessages((items) => items.map(
            (item) => item.id === updated.id ? updated : item,
          )))
          .catch((requestError) => setError(requestError.message))
      }
    }
  }, [messages, open, requestJson, username])

  const submit = async (event) => {
    event.preventDefault()
    if (!body.trim()) return
    setBusy(true)
    setError('')
    try {
      await requestJson(`${path}/messages`, username, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body }),
      })
      setBody('')
      setMessages(await requestJson(`${path}/messages`, username))
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  const requestState = async () => {
    setBusy(true)
    setError('')
    try {
      await requestJson(`${path}/request-state`, username, { method: 'POST' })
      setMessages(await requestJson(`${path}/messages`, username))
      setOpen(true)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  const unreadCount = messages.filter(
    (message) => message.sender_type === 'RESPONSE_UNIT' && !message.read_at,
  ).length

  return (
    <div className={styles.responseChat}>
      <button type="button" className={styles.chatToggle} onClick={() => setOpen((value) => !value)}>
        Оперативная связь · {incidentNumber} · {assignment.response_unit.name}
        {unreadCount > 0 && <b className={styles.unreadBadge}>{unreadCount} новых</b>}
        <span>{open ? '⌃' : '⌄'}</span>
      </button>
      {open && (
        <div className={styles.chatContent}>
          <small>Учебный канал оперативной связи со старшим группы</small>
          <div className={styles.chatHistory} role="log" aria-live="polite">
            {messages.length === 0 && <p>Сообщений пока нет.</p>}
            {messages.map((message) => (
              <article key={message.id} className={`${styles.chatMessage} ${styles[`chat${message.sender_type}`]}`}>
                <header>
                  <strong>{senderLabels[message.sender_type]}</strong>
                  <time>{formatDateTime(message.created_at)}</time>
                </header>
                <p>{message.body}</p>
              </article>
            ))}
            <div ref={endRef} />
          </div>
          {error && <p className={styles.chatError} role="alert">{error}</p>}
          <button type="button" onClick={requestState} disabled={busy}>Запросить состояние</button>
          <form className={styles.chatComposer} onSubmit={submit}>
            <input
              aria-label="Сообщение старшему группы"
              value={body}
              onChange={(event) => setBody(event.target.value)}
              maxLength={4000}
              placeholder="Сообщение старшему группы"
            />
            <button type="submit" disabled={busy || !body.trim()}>Отправить</button>
          </form>
        </div>
      )}
    </div>
  )
}

export default ResponseChat

ResponseChat.propTypes = {
  assignment: PropTypes.shape({
    id: PropTypes.number.isRequired,
    response_unit: PropTypes.shape({ name: PropTypes.string.isRequired }).isRequired,
  }).isRequired,
  incidentNumber: PropTypes.string.isRequired,
  username: PropTypes.string.isRequired,
  apiUrl: PropTypes.string.isRequired,
  requestJson: PropTypes.func.isRequired,
  formatDateTime: PropTypes.func.isRequired,
}
