/* eslint-disable react/prop-types */
import { useCallback, useEffect, useState } from 'react'
import { io } from 'socket.io-client'

import styles from './LiveMonitor.module.css'
import { ddsStatusLabels, incidentHistoryLabels, responseStateLabels, responseSenderLabels } from './uiLabels.js'

const statusLabels = ddsStatusLabels

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
  const [dialog, setDialog] = useState('')
  const [busy, setBusy] = useState(false)
  const [scenarios, setScenarios] = useState([])
  const [notes, setNotes] = useState([])
  const [scenarioDetails, setScenarioDetails] = useState({})
  const [draft, setDraft] = useState({ scenario_id: '', target: 'CLASS', target_id: '', incident_id: '', kind: 'NEW_INFORMATION', body: '', mode: 'GRACEFUL', reason: '' })
  const selectedScenario = scenarios.find((item) => item.id === Number(draft.scenario_id))
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
    for (const event of ['incident.delivered', 'incident.claimed', 'incident.updated', 'response.message_created', 'training.control_changed']) {
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

  useEffect(() => {
    if (!selectedId) return undefined
    let active = true
    api(`/api/training/sessions/${sessionId}/runs/${selectedId}/notes`)
      .then((items) => { if (active) setNotes(items) })
      .catch((cause) => { if (active) setError(cause.message) })
    return () => { active = false }
  }, [api, sessionId, selectedId])

  const post = async (path, body) => {
    setBusy(true); setError('')
    try {
      const result = await api(`/api/training/sessions/${sessionId}${path}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
      await refresh()
      setDialog('')
      return result
    } catch (cause) { setError(cause.message); return null } finally { setBusy(false) }
  }

  const openCards = async () => {
    try { setScenarios(await api(`/api/training/sessions/${sessionId}/scenarios`)); setDialog('card') }
    catch (cause) { setError(cause.message) }
  }
  const showScenario = async (instanceId) => {
    try {
      const [instance, materialization] = await Promise.all([
        api(`/api/scenario-instances/${instanceId}`),
        api(`/api/scenario-instances/${instanceId}/materialization`),
      ])
      setScenarioDetails((current) => ({ ...current, [instanceId]: { instance, materialization } }))
    } catch (cause) { setError(cause.message) }
  }

  const submitDialog = async (event) => {
    event.preventDefault()
    if (dialog === 'card') await post('/manual-cards', { scenario_id: Number(draft.scenario_id), target: draft.target, target_id: draft.target_id ? Number(draft.target_id) : null })
    if (dialog === 'event') await post('/scenario-events', { incident_id: Number(draft.incident_id), kind: draft.kind, body: draft.body })
    if (dialog === 'finish') await post('/finish', { mode: draft.mode })
    if (dialog === 'runPause') await post(`/runs/${selectedId}/pause`, { reason: draft.reason })
    if (dialog === 'note') {
      const result = await post(`/runs/${selectedId}/notes`, { body: draft.body })
      if (result) setNotes((items) => [...items, result])
    }
    setDraft((value) => ({ ...value, body: '', reason: '' }))
  }

  if (!snapshot) return <section className={styles.monitor}><p>{error || 'Загрузка монитора…'}</p></section>
  const selected = snapshot.runs.find((run) => run.id === selectedId)
  const { counts, session } = snapshot
  const elapsed = (session.delivery_elapsed_seconds || 0)
    + (session.delivery_checked_at && !session.paused_at && !session.finish_mode
      ? (Date.now() - new Date(session.delivery_checked_at).getTime()) / 1000 : 0)
  const activeIncidents = snapshot.runs.flatMap((run) => run.active_incidents)
    .filter((item, index, items) => items.findIndex((other) => other.id === item.id) === index)

  return <div className={styles.monitor}>
    {error && <p className={styles.error} role="alert">{error}</p>}
    <section className={styles.hero}>
      <div><small>LIVE · УЧЕБНАЯ СМЕНА</small><h2>{session.title}</h2><p>{session.topic || 'Без темы'}</p></div>
      <div className={styles.clock}><strong>{duration(elapsed)} <span>/ {duration((session.duration_minutes || 0) * 60)}</span></strong><small>Время занятия</small></div>
      <div className={styles.controls}>
        <button type="button" disabled={busy || session.state !== 'ACTIVE'} onClick={() => post(session.paused_at ? '/resume' : '/pause', {})}>{session.paused_at ? 'Продолжить' : 'Пауза'}</button>
        <button type="button" disabled={busy || !!session.paused_at || !!session.finish_mode} onClick={openCards}>+ Карточка</button>
        <button type="button" disabled={busy || !!session.paused_at || !activeIncidents.length} onClick={() => setDialog('event')}>+ Событие</button>
        <button type="button" disabled={busy || session.state !== 'ACTIVE'} onClick={() => { setDraft((value) => ({ ...value, mode: session.finish_mode === 'GRACEFUL' ? 'IMMEDIATE' : 'GRACEFUL' })); setDialog('finish') }}>{session.finish_mode === 'GRACEFUL' ? 'Завершить немедленно' : 'Завершить'}</button>
      </div>
    </section>
    {session.paused_at && <p className={styles.pauseBanner} role="status">ЗАНЯТИЕ ПРИОСТАНОВЛЕНО ПРЕПОДАВАТЕЛЕМ</p>}
    {session.finish_mode === 'GRACEFUL' && session.state === 'ACTIVE' && <p className={styles.pauseBanner} role="status">Выдача остановлена. Обучаемые завершают текущие карточки.</p>}
    {session.state === 'COMPLETED' && <p className={styles.pauseBanner} role="status">Занятие завершено. История карточек сохранена.</p>}
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
          <p className={styles.current}>{run.paused_at ? 'АРМ приостановлен' : run.current ? <>Сейчас: <b>{run.current.incident_number}</b><small>{statusLabels[run.current.dds_status]} · {duration(run.current.elapsed_seconds)}</small></> : 'Нет активной карточки'}</p>
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
      <div className={styles.runControls}><button type="button" disabled={busy} onClick={() => selected.paused_at ? post(`/runs/${selected.id}/resume`, {}) : setDialog('runPause')}>{selected.paused_at ? 'Продолжить АРМ' : 'Приостановить АРМ'}</button><button type="button" onClick={() => setDialog('note')}>+ Заметка</button></div>
      {notes.length > 0 && <section><h3>Заметки преподавателя</h3>{notes.map((note) => <p className={styles.event} key={note.id}>{time(note.created_at)} · {note.body}</p>)}</section>}
      {workstation?.incidents ? <><h3>Карточки рабочего места</h3>{incidentList(workstation.incidents)}{workstation.incidents.map((incident) => <section key={incident.id} className={styles.readonly}><h4>{incident.incident_number} · {incident.incident_type}</h4><p>{incident.address}</p><p>{incident.description}</p>{incident.scenario_instance_id && <><button type="button" onClick={() => showScenario(incident.scenario_instance_id)}>Показать план сценария</button>{scenarioDetails[incident.scenario_instance_id] && <div><p>Шаблон: {scenarioDetails[incident.scenario_instance_id].instance.template_snapshot.name} · объект: {scenarioDetails[incident.scenario_instance_id].instance.object_snapshot.name}</p><ol>{scenarioDetails[incident.scenario_instance_id].instance.events.map((event) => { const fact = scenarioDetails[incident.scenario_instance_id].materialization.runtime_events.find((item) => item.scenario_instance_event_id === event.id); return <li key={event.sequence_number}>T+{duration(event.offset_seconds)} · {event.title} — {event.description} · {event.event_type === 'INITIAL_REPORT' ? 'Исходное сообщение' : fact?.released_at ? `Выдано ${time(fact.released_at)}` : 'Ожидает'}</li> })}</ol></div>}</>}{incident.scenario_events?.map((item) => <p key={item.id}><b>{item.origin === 'SCENARIO' ? 'Сценарий' : 'Вводная преподавателя'} · {time(item.created_at)}</b> {item.body}</p>)}<h5>Статусы и комментарии</h5>{incident.actions.map((action) => <p key={action.id}>{time(action.created_at)} · {incidentHistoryLabels[action.status] || action.status}{action.comment ? ` — ${action.comment}` : ''}</p>)}<h5>Группы и сообщения</h5>{incident.response_assignments.map((assignment) => <div key={assignment.id}><b>{assignment.unit_name} · {responseStateLabels[assignment.state] || assignment.state}</b>{assignment.messages.map((message) => <p key={message.id}>{time(message.created_at)} · {responseSenderLabels[message.sender_type] || message.sender_type}: {message.body}</p>)}</div>)}</section>)}</> : <>
        <h3>Активные карточки</h3>{selected.active_incidents.length ? incidentList(selected.active_incidents) : <p>Активных карточек нет.</p>}
        <h3>Последние действия</h3>{selected.timeline.length ? selected.timeline.map((entry, index) => <p className={styles.event} key={`${entry.incident_id}-${index}`}><time>{time(entry.at)}</time>{entry.text}</p>) : <p>Действий пока нет.</p>}
        <h3>Сигналы</h3>{selected.signals.length ? selected.signals.map((signal, index) => <p className={styles.signal} key={`${signal.kind}-${index}`}>⚠ {signal.text}</p>) : <p>Сигналов нет.</p>}
      </>}
    </aside></div>}
    {dialog && <div className={styles.dialogBackdrop}><form className={styles.dialog} onSubmit={submitDialog}>
      <header><h3>{({ card: 'Отправить карточку', event: 'Добавить событие', finish: 'Завершить занятие', runPause: 'Приостановить АРМ', note: 'Заметка преподавателя' })[dialog]}</h3><button type="button" onClick={() => setDialog('')}>×</button></header>
      {dialog === 'card' && <><label>Подготовленный сценарий<select required value={draft.scenario_id} onChange={(e) => { const item = scenarios.find((entry) => entry.id === Number(e.target.value)); setDraft({ ...draft, scenario_id: e.target.value, target: item?.scenario_instance_id ? item.training_group_id ? 'GROUP' : 'RUN' : 'CLASS', target_id: item?.scenario_instance_id ? String(item.training_group_id || item.training_run_id) : '' }) }}><option value="">Выберите сценарий</option>{scenarios.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>{selectedScenario?.scenario_instance_id ? <p>Подготовлен для {selectedScenario.training_group_id ? `группы #${selectedScenario.training_group_id}` : `АРМ #${selectedScenario.training_run_id}`}</p> : <><label>Получатели<select value={draft.target} onChange={(e) => setDraft({ ...draft, target: e.target.value, target_id: '' })}><option value="CLASS">Весь класс</option><option value="GROUP">Группа</option><option value="RUN">АРМ</option></select></label>{draft.target === 'GROUP' && <label>Группа<select required value={draft.target_id} onChange={(e) => setDraft({ ...draft, target_id: e.target.value })}><option value="">Выберите группу</option>{[...new Set(snapshot.runs.map((run) => run.group_id).filter(Boolean))].map((id) => <option key={id} value={id}>Группа {id}</option>)}</select></label>}{draft.target === 'RUN' && <label>АРМ<select required value={draft.target_id} onChange={(e) => setDraft({ ...draft, target_id: e.target.value })}><option value="">Выберите АРМ</option>{snapshot.runs.map((run) => <option key={run.id} value={run.id}>АРМ {run.workstation_number} · {run.trainee_name}</option>)}</select></label>}</>}</>}
      {dialog === 'event' && <><label>Карточка<select required value={draft.incident_id} onChange={(e) => setDraft({ ...draft, incident_id: e.target.value })}><option value="">Выберите карточку</option>{activeIncidents.map((item) => <option key={item.id} value={item.id}>{item.incident_number} · {item.incident_type}</option>)}</select></label><label>Тип события<select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}><option value="NEW_INFORMATION">Дополнительная информация</option><option value="SITUATION_CHANGED">Изменилась ситуация</option><option value="REPEAT_CALL">Повторное обращение</option><option value="CASUALTY">Появился пострадавший</option><option value="OBJECT_CLARIFIED">Уточнён объект</option><option value="UNIT_UNAVAILABLE">Группа не отвечает</option><option value="PARTICIPANT_MESSAGE">Сообщение участника</option></select></label><label>Текст<textarea required value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} /></label></>}
      {dialog === 'finish' && <fieldset><legend>Режим завершения</legend>{!session.finish_mode && <label><input type="radio" name="finish" checked={draft.mode === 'GRACEFUL'} onChange={() => setDraft({ ...draft, mode: 'GRACEFUL' })} /> Прекратить поступление новых карточек и дать завершить текущие</label>}<label><input type="radio" name="finish" checked={draft.mode === 'IMMEDIATE'} onChange={() => setDraft({ ...draft, mode: 'IMMEDIATE' })} /> Завершить немедленно</label></fieldset>}
      {dialog === 'runPause' && <label>Причина<textarea required value={draft.reason} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} /></label>}
      {dialog === 'note' && <label>Заметка<textarea required value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} /></label>}
      <footer><button type="button" onClick={() => setDialog('')}>Отмена</button><button type="submit" disabled={busy}>Сохранить</button></footer>
    </form></div>}
  </div>
}

export default LiveMonitor
