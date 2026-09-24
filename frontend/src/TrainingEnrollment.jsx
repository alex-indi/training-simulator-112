/* eslint-disable react/prop-types */
import { useCallback, useEffect, useState } from 'react'
import { io } from 'socket.io-client'

import styles from './TrainingEnrollment.module.css'

function TrainingEnrollment({ user, requestJson, onJoined }) {
  const [sessions, setSessions] = useState([])
  const [sessionId, setSessionId] = useState('')
  const [station, setStation] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const api = useCallback((path, options) => requestJson(path, user.username, options), [requestJson, user.username])

  useEffect(() => {
    let active = true
    const refresh = () => api('/api/training/sessions')
      .then((items) => { if (active) setSessions(items) })
      .catch((cause) => { if (active) setError(cause.message) })
    refresh()
    const timer = window.setInterval(refresh, 15000)
    return () => { active = false; window.clearInterval(timer) }
  }, [api])

  const selected = sessions.find((item) => String(item.id) === sessionId) || sessions[0]
  const ownRun = selected?.own_run
  const selectedId = selected?.id
  const ownRunId = ownRun?.id

  useEffect(() => {
    if (!selectedId || !ownRunId) return undefined
    let active = true
    const socket = io(import.meta.env.VITE_API_URL || 'http://localhost:8000', {
      auth: { username: user.username },
    })
    const refresh = () => api('/api/training/sessions')
      .then((items) => { if (active) setSessions(items) })
      .catch((cause) => { if (active) setError(cause.message) })
    socket.on('connect', () => { socket.emit('subscribe', { session_id: selectedId }); refresh() })
    socket.on('training.control_changed', refresh)
    return () => { active = false; socket.disconnect() }
  }, [api, ownRunId, selectedId, user.username])

  useEffect(() => {
    if (!ownRunId || !selectedId) return undefined
    const beat = () => api(`/api/training/sessions/${selectedId}/heartbeat`, { method: 'POST' })
      .catch((cause) => setError(cause.message))
    beat()
    const timer = window.setInterval(beat, 20000)
    return () => window.clearInterval(timer)
  }, [api, ownRunId, selectedId])

  const join = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const item = await api(`/api/training/sessions/${selected.id}/join`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workstation_number: Number(station) }),
      })
      setSessions(await api('/api/training/sessions'))
      onJoined(item.id)
    } catch (cause) { setError(cause.message) } finally { setBusy(false) }
  }

  if (!sessions.length && !error) return null
  if (ownRun && !error && !selected?.paused_at && !ownRun.paused_at) return null
  return <section className={styles.panel} aria-label="Учебное занятие">
    <strong>Учебное занятие</strong>
    {error && <span className={styles.error} role="alert">{error}</span>}
    {sessions.length > 0 && <>
      <select aria-label="Занятие" value={selected?.id || ''} onChange={(event) => { setSessionId(event.target.value); setStation('') }}>
        {sessions.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
      </select>
      {ownRun ? <span>АРМ {String(ownRun.workstation_number).padStart(2, '0')} · {ownRun.dds_profile === 'ДДС' ? 'профиль ожидает назначения' : ownRun.dds_profile} · {ownRun.online ? 'online' : 'подключение'}</span>
        : <form onSubmit={join}><label>Рабочее место <input type="number" min="1" max={selected.workstation_count} value={station} onChange={(event) => setStation(event.target.value)} required /></label><button type="submit" disabled={busy || !station}>Занять АРМ</button></form>}
      {selected?.paused_at && <strong role="status">ЗАНЯТИЕ ПРИОСТАНОВЛЕНО ПРЕПОДАВАТЕЛЕМ</strong>}
      {!selected?.paused_at && ownRun?.paused_at && <strong role="status">ВАШЕ РАБОЧЕЕ МЕСТО ПРИОСТАНОВЛЕНО ПРЕПОДАВАТЕЛЕМ</strong>}
    </>}
  </section>
}

export default TrainingEnrollment
