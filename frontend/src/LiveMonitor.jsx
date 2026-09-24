/* eslint-disable react/prop-types */
import { useCallback, useEffect, useState } from 'react'
import { io } from 'socket.io-client'

import styles from './LiveMonitor.module.css'

const statusLabels = {
  AWAITING_DECISION: 'Ожидает решения', ACCEPTED: 'Принята', REJECTED: 'Отказ',
  RESPONSE_STARTED: 'Начало реагирования', ARRIVED: 'Прибытие',
  WORKING: 'Проведение работ', COMPLETED: 'Работы завершены',
  WORK_REFUSED: 'Отказ от работ',
}

function duration(seconds) {
  const value = Math.max(0, Math.floor(seconds || 0))
  return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`
}

function time(value) {
  return value ? new Intl.DateTimeFormat('ru-RU', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Europe/Moscow',
  }).format(new Date(value)) : '—'
}

function incidentList(incidents) {
  return incidents.map((incident) => <article className={styles.incident} key={incident.id}>
    <div><strong>{incident.incident_number}</strong><span>{duration(incident.elapsed_seconds)}</span></div>
    <b>{incident.incident_type}</b>
    <small>{statusLabels[incident.dds_status] || incident.dds_status}</small>
  </article>)
}

function LiveMonitor({ sessionId, user, api }) {
  const [snapshot, setSnapshot] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [workstation, setWorkstation] = useState(null)
  const workstationId = workstation?.id
  const [error, setError] = useState('')
  const [, setTick] = useState(0)

  const refresh = useCallback(async () => {
    try {
      const result = await api(`/api/training/sessions/${sessionId}/monitor`)
      setSnapshot({ ...result, receivedAt: Date.now() })
      setError('')
    } catch (cause) { setError(cause.message) }
  }, [api, sessionId])

  useEffect(() => {
    refresh()
    const socket = io(import.meta.env.VITE_API_URL || 'http://localhost:8000', {
      auth: { username: user.username },
    })
    socket.on('connect', () => { socket.emit('subscribe', { session_id: sessionId }); refresh() })
    for (const event of ['incident.delivered', 'incident.claimed', 'incident.updated', 'response.message_created']) {
      socket.on(event, refresh)
    }
    const poll = window.setInterval(refresh, 10000)
    const timer = window.setInterval(() => setTick((value) => value + 1), 1000)
    return () => { socket.disconnect(); window.clearInterval(poll); window.clearInterval(timer) }
  }, [refresh, sessionId, user.username])

  useEffect(() => {
    if (!workstationId) return undefined
    let active = true
    const load = () => api(`/api/training/sessions/${sessionId}/runs/${workstationId}/workstation`)
      .then((value) => { if (active) setWorkstation(value) })
      .catch((cause) => { if (active) setError(cause.message) })
    load()
    const poll = window.setInterval(load, 10000)
    return () => { active = false; window.clearInterval(poll) }
  }, [api, sessionId, workstationId])

  if (!snapshot) return <section className={styles.monitor}><p>{error || 'Загрузка монитора…'}</p></section>
  const selected = snapshot.runs.find((run) => run.id === selectedId)
  const { counts, session } = snapshot
  const elapsed = session.started_at
    ? (new Date(snapshot.server_time).getTime() - new Date(session.started_at).getTime()) / 1000
      + (Date.now() - snapshot.receivedAt) / 1000
    : 0

  return <div className={styles.monitor}>
    {error && <p className={styles.error} role="alert">{error}</p>}
    <section className={styles.hero}>
      <div><small>LIVE · УЧЕБНАЯ СМЕНА</small><h2>{session.title}</h2><p>{session.topic || 'Без темы'}</p></div>
      <div className={styles.clock}><strong>{duration(elapsed)} <span>/ {duration((session.duration_minutes || 0) * 60)}</span></strong><small>Время занятия</small></div>
      <div className={styles.controls}>{['Пауза', '+ Карточка', '+ Событие', 'Завершить'].map((label) => <button key={label} type="button" disabled title="Управление занятием появится в UT112-21">{label}</button>)}</div>
    </section>
    <section className={styles.metrics} aria-label="Сводка класса">
      <div><span>На связи</span><strong>{counts.online}</strong><small>{counts.offline} offline</small></div>
      <div><span>Новые</span><strong>{counts.new}</strong></div>
      <div><span>В работе</span><strong>{counts.working}</strong></div>
      <div><span>Завершено</span><strong>{counts.completed}</strong></div>
      <div><span>Отклонения</span><strong>{counts.deviations}</strong></div>
    </section>
    <div className={styles.body}>
      <section className={styles.classroom}>
        <div className={styles.sectionTitle}><h3>Рабочие места</h3><span>{snapshot.runs.length} участников</span></div>
        <div className={styles.grid}>{snapshot.runs.map((run) => <button
          key={run.id} type="button" onClick={() => { setSelectedId(run.id); setWorkstation(null) }}
          className={`${styles.tile} ${run.counts.deviations ? styles.warn : ''}`}
        >
          <div className={styles.tileTop}><b>АРМ {String(run.workstation_number || 0).padStart(2, '0')}</b><i className={run.online ? styles.online : styles.offline} title={run.online ? 'Online' : 'Offline'} /></div>
          <strong>{run.trainee_name}</strong><small>{run.dds_profile}</small>
          <dl><div><dt>Новые</dt><dd>{run.counts.new}</dd></div><div><dt>В работе</dt><dd>{run.counts.working}</dd></div><div><dt>Завершено</dt><dd>{run.counts.completed}</dd></div><div><dt>Отказы</dt><dd>{run.counts.refusals}</dd></div></dl>
          <p className={styles.deviations}>⚠ Отклонения <b>{run.counts.deviations}</b></p>
          <p className={styles.current}>{run.current ? <>Сейчас: <b>{run.current.incident_number}</b><small>{statusLabels[run.current.dds_status]} · {duration(run.current.elapsed_seconds)}</small></> : 'Нет активной карточки'}</p>
        </button>)}</div>
      </section>
      <aside className={styles.attention}><div className={styles.sectionTitle}><h3>Требует внимания</h3><b>{snapshot.attention.length}</b></div>
        {snapshot.attention.length ? snapshot.attention.map((signal, index) => <button key={`${signal.run_id}-${signal.kind}-${index}`} type="button" onClick={() => { setSelectedId(signal.run_id); setWorkstation(null) }}>
          <i className={styles[signal.severity]} /><span><strong>АРМ {String(signal.workstation_number || 0).padStart(2, '0')}</strong><small>{signal.text}</small></span>
        </button>) : <p>Сейчас нет сигналов.</p>}
      </aside>
    </div>
    {selected && <div className={styles.overlay} onMouseDown={() => { setSelectedId(null); setWorkstation(null) }}><aside className={styles.drawer} onMouseDown={(event) => event.stopPropagation()}>
      <header><div><small>АРМ {String(selected.workstation_number || 0).padStart(2, '0')} · {selected.online ? 'Online' : 'Offline'}</small><h2>{selected.trainee_name}</h2><p>{selected.dds_profile}</p></div><button type="button" onClick={() => { setSelectedId(null); setWorkstation(null) }} aria-label="Закрыть">×</button></header>
      <button className={styles.workstationButton} type="button" onClick={() => setWorkstation(workstation ? null : { id: selected.id })}>{workstation ? '← К деталям участника' : 'Открыть рабочее место'}</button>
      {workstation?.incidents ? <><h3>Карточки рабочего места</h3>{incidentList(workstation.incidents)}{workstation.incidents.map((incident) => <section key={incident.id} className={styles.readonly}><h4>{incident.incident_number} · {incident.incident_type}</h4><p>{incident.address}</p><p>{incident.description}</p><h5>Статусы и комментарии</h5>{incident.actions.map((action) => <p key={action.id}>{time(action.created_at)} · {action.status}{action.comment ? ` — ${action.comment}` : ''}</p>)}<h5>Группы и сообщения</h5>{incident.response_assignments.map((assignment) => <div key={assignment.id}><b>{assignment.unit_name} · {assignment.state}</b>{assignment.messages.map((message) => <p key={message.id}>{time(message.created_at)} · {message.sender_type}: {message.body}</p>)}</div>)}</section>)}</> : <>
        <h3>Активные карточки</h3>{selected.active_incidents.length ? incidentList(selected.active_incidents) : <p>Активных карточек нет.</p>}
        <h3>Последние действия</h3>{selected.timeline.length ? selected.timeline.map((entry, index) => <p className={styles.event} key={`${entry.incident_id}-${index}`}><time>{time(entry.at)}</time>{entry.text}</p>) : <p>Действий пока нет.</p>}
        <h3>Сигналы</h3>{selected.signals.length ? selected.signals.map((signal, index) => <p className={styles.signal} key={`${signal.kind}-${index}`}>⚠ {signal.text}</p>) : <p>Сигналов нет.</p>}
      </>}
    </aside></div>}
  </div>
}

export default LiveMonitor
