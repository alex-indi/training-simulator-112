/* eslint-disable react/prop-types */
import { useCallback, useEffect, useState } from 'react'
import { io } from 'socket.io-client'

import styles from './InstructorWorkspace.module.css'
import LiveMonitor from './LiveMonitor.jsx'
import AssessmentWorkspace from './AssessmentWorkspace.jsx'
import ScenarioLibrary from './ScenarioLibrary.jsx'

const emptySettings = {
  title: '', topic: '', mode: 'FLOW', duration_minutes: 30,
  delivery_interval_seconds: 120, delivery_order: 'SEQUENTIAL', workstation_count: 30,
}
const emptyGroup = { name: '', dds_profile: '', difficulty: 'Средняя', queue_mode: 'INDIVIDUAL_QUEUE' }
const steps = ['Параметры', 'Учебный класс', 'Распределение', 'Задания', 'Готовность']
const emptyScenario = { title: '', target: '', address: '', description: '', incident_type: '' }
const stateLabels = { DRAFT: 'Черновик', READY: 'Готово к запуску', ACTIVE: 'Активное', COMPLETED: 'Завершённое', CANCELLED: 'Отменённое' }
const modeLabels = { FLOW: 'Потоковая тренировка', FIXED_SET: 'Набор заданий', MANUAL: 'Управляемая тренировка' }

function InstructorWorkspace({ user, users, selectUser, requestJson }) {
  const [sessions, setSessions] = useState([])
  const [templates, setTemplates] = useState([])
  const [session, setSession] = useState(null)
  const [step, setStep] = useState(0)
  const [settings, setSettings] = useState(emptySettings)
  const [selected, setSelected] = useState([])
  const [assignment, setAssignment] = useState({ dds_profile: '', difficulty: 'Средняя', queue_mode: 'INDIVIDUAL_QUEUE', group_id: '' })
  const [groupDraft, setGroupDraft] = useState(emptyGroup)
  const [editingGroupId, setEditingGroupId] = useState(null)
  const [templateName, setTemplateName] = useState('')
  const [queue, setQueue] = useState([])
  const [scenarioDraft, setScenarioDraft] = useState(emptyScenario)
  const [editingScenarioId, setEditingScenarioId] = useState(null)
  const [generateCount, setGenerateCount] = useState(3)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [libraryOpen, setLibraryOpen] = useState(false)
  const openSessionId = session?.id

  const api = useCallback((path, options) => requestJson(path, user.username, options), [requestJson, user.username])
  const jsonOptions = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

  const reload = useCallback(async (sessionId) => {
    const [items, savedTemplates] = await Promise.all([
      api('/api/training/sessions'), api('/api/training/templates'),
    ])
    setSessions(items)
    setTemplates(savedTemplates)
    if (sessionId) {
      const fresh = items.find((item) => item.id === sessionId)
      if (fresh) setSession(fresh)
      setQueue(await api(`/api/training/sessions/${sessionId}/queue`))
    }
  }, [api])

  useEffect(() => {
    let active = true
    Promise.all([api('/api/training/sessions'), api('/api/training/templates')])
      .then(([items, saved]) => {
        if (!active) return
        setSessions(items)
        setTemplates(saved)
        const savedId = Number(window.sessionStorage.getItem('ut112-instructor-session-id'))
        const current = items.find((item) => item.id === savedId && item.state === 'ACTIVE')
        if (current) setSession(current)
      })
      .catch((cause) => { if (active) setError(cause.message) })
    return () => { active = false }
  }, [api])

  useEffect(() => {
    if (!openSessionId) return undefined
    const timer = window.setInterval(() => {
      api(`/api/training/sessions/${openSessionId}`)
        .then((fresh) => setSession((current) => current?.id === fresh.id ? fresh : current))
        .catch(() => {})
    }, 5000)
    return () => window.clearInterval(timer)
  }, [api, openSessionId, session?.state])

  useEffect(() => {
    if (!openSessionId || session?.state === 'ACTIVE') return undefined
    const socket = io(import.meta.env.VITE_API_URL || 'http://localhost:8000', { auth: { username: user.username } })
    const refresh = () => reload(openSessionId).catch(() => {})
    socket.on('connect', () => { socket.emit('subscribe', { session_id: openSessionId }); refresh() })
    socket.on('incident.delivered', refresh)
    socket.on('incident.opened', refresh)
    socket.on('incident.claimed', refresh)
    socket.on('incident.updated', refresh)
    socket.on('response.assignment_created', refresh)
    socket.on('response.state_changed', refresh)
    return () => socket.disconnect()
  }, [openSessionId, reload, session?.state, user.username])

  const runAction = async (action) => {
    setBusy(true)
    setError('')
    setNotice('')
    try { await action() } catch (cause) { setError(cause.message) } finally { setBusy(false) }
  }

  const openSession = (item) => {
    window.sessionStorage.setItem('ut112-instructor-session-id', String(item.id))
    setSession(item)
    setSettings({
      title: item.title, topic: item.topic, mode: item.mode,
      duration_minutes: item.duration_minutes ?? 30,
      delivery_interval_seconds: item.delivery_interval_seconds ?? 120,
      delivery_order: item.delivery_order, workstation_count: item.workstation_count,
    })
    setSelected([])
    setGenerateCount(item.mode === 'FLOW' ? Math.min(100, Math.ceil(item.duration_minutes * 60 / item.delivery_interval_seconds) + 2) : 3)
    setQueue([])
    api(`/api/training/sessions/${item.id}/queue`).then(setQueue).catch((cause) => setError(cause.message))
    setStep(0)
  }

  const createSession = () => runAction(async () => {
    const item = await api('/api/training/sessions', jsonOptions('POST', settings))
    await reload(item.id)
    openSession(item)
    setNotice('Черновик занятия создан')
  })

  const saveSettings = () => runAction(async () => {
    const item = await api(`/api/training/sessions/${session.id}`, jsonOptions('PUT', settings))
    setSession(item)
    setStep(1)
    setNotice('Параметры сохранены')
  })

  const saveGroup = () => runAction(async () => {
    const path = `/api/training/sessions/${session.id}/groups${editingGroupId ? `/${editingGroupId}` : ''}`
    const item = await api(path, jsonOptions(editingGroupId ? 'PUT' : 'POST', {
      ...groupDraft, name: groupDraft.name.trim(), dds_profile: groupDraft.dds_profile.trim() || null,
    }))
    setSession(item)
    setGroupDraft(emptyGroup)
    setEditingGroupId(null)
    setNotice(editingGroupId ? 'Группа обновлена' : 'Группа создана')
  })

  const changeGroup = (group, method) => runAction(async () => {
    const item = await api(`/api/training/sessions/${session.id}/groups/${group.id}`,
      method === 'DELETE' ? { method } : jsonOptions(method, group))
    setSession(item)
  })

  const assignRuns = () => runAction(async () => {
    const payload = assignment.group_id
      ? { run_ids: selected, group_id: Number(assignment.group_id) }
      : { run_ids: selected, group_id: null, dds_profile: assignment.dds_profile.trim(), difficulty: assignment.difficulty, queue_mode: assignment.queue_mode }
    const item = await api(`/api/training/sessions/${session.id}/assign`, jsonOptions('POST', payload))
    setSession(item)
    setSelected([])
    setNotice(`Параметры назначены: ${selected.length} АРМ`)
  })

  const prepare = () => runAction(async () => {
    const item = await api(`/api/training/sessions/${session.id}/prepare`, { method: 'POST' })
    setSession(item)
    setNotice('Занятие готово к запуску')
  })
  const start = () => runAction(async () => {
    const item = await api(`/api/training/sessions/${session.id}/start`, { method: 'POST' })
    setSession(item)
    setNotice('Занятие запущено')
  })
  const saveTemplate = () => runAction(async () => {
    await api('/api/training/templates', jsonOptions('POST', { name: templateName, training_session_id: session.id }))
    setTemplateName('')
    await reload(session.id)
    setNotice('Шаблон сохранён')
  })
  const applyTemplate = (id) => runAction(async () => {
    const item = await api(`/api/training/templates/${id}/sessions`, { method: 'POST' })
    await reload(item.id)
    openSession(item)
    setNotice('Создан черновик из шаблона')
  })

  const generateQueue = () => runAction(async () => {
    const items = await api(`/api/training/sessions/${session.id}/queue/generate`, jsonOptions('POST', { count_per_run: Number(generateCount) }))
    setQueue(items)
    await reload(session.id)
    setNotice('Подготовлен новый набор. Проверьте и утвердите карточки.')
  })
  const saveScenario = () => runAction(async () => {
    const snapshot = {
      incident_number: editingScenarioId ? queue.find((item) => item.id === editingScenarioId).snapshot.incident_number : `КП-${session.id}-${Date.now()}`,
      reported_at: new Date().toISOString(), source: 'Система-112',
      address: scenarioDraft.address, description: scenarioDraft.description,
      incident_type: scenarioDraft.incident_type,
    }
    const path = `/api/training/sessions/${session.id}/queue${editingScenarioId ? `/${editingScenarioId}` : ''}`
    const payload = { title: scenarioDraft.title, snapshot }
    if (!editingScenarioId) {
      const [kind, id] = scenarioDraft.target.split(':')
      payload[kind === 'group' ? 'training_group_id' : 'training_run_id'] = Number(id)
    }
    setQueue(await api(path, jsonOptions(editingScenarioId ? 'PUT' : 'POST', payload)))
    setScenarioDraft(emptyScenario)
    setEditingScenarioId(null)
    await reload(session.id)
  })
  const removeScenario = (id) => runAction(async () => {
    setQueue(await api(`/api/training/sessions/${session.id}/queue/${id}`, { method: 'DELETE' }))
    await reload(session.id)
  })
  const replaceScenario = (id) => runAction(async () => {
    setQueue(await api(`/api/training/sessions/${session.id}/queue/${id}/replace`, { method: 'POST' }))
    await reload(session.id)
  })
  const approveQueue = () => runAction(async () => {
    setQueue(await api(`/api/training/sessions/${session.id}/queue/approve`, { method: 'POST' }))
    await reload(session.id)
    setNotice('Набор утверждён')
  })
  const editScenario = (item) => {
    setEditingScenarioId(item.id)
    setScenarioDraft({ title: item.title, target: item.training_group_id ? `group:${item.training_group_id}` : `run:${item.training_run_id}`, address: item.snapshot.address, description: item.snapshot.description, incident_type: item.snapshot.incident_type })
  }

  const updateSettings = (event) => {
    const { name, value, type } = event.target
    setSettings((current) => ({ ...current, [name]: type === 'number' ? Number(value) : value }))
  }
  const toggleRun = (id) => setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])
  const editable = session && ['DRAFT', 'READY'].includes(session.state)
  const stationByNumber = new Map(session?.runs?.map((run) => [run.workstation_number, run]) || [])
  const closeSession = () => {
    window.sessionStorage.removeItem('ut112-instructor-session-id')
    setSession(null)
    reload()
  }

  if (libraryOpen) return <ScenarioLibrary user={user} requestJson={requestJson} onBack={() => setLibraryOpen(false)} />

  if (session?.state === 'ACTIVE') return <main className={styles.shell}>
    <header className={styles.header}>
      <div><small>Учебный тренажёр 112 · кабинет преподавателя</small><h1>Live-монитор</h1></div>
      <label>Пользователь <select value={user.username} onChange={selectUser}>{users.map((item) => <option key={item.id} value={item.username}>{item.full_name}</option>)}</select></label>
    </header>
    <div className={styles.content}>
      <button className={styles.back} type="button" onClick={closeSession}>← Все занятия</button>
      <LiveMonitor sessionId={session.id} user={user} api={api} />
    </div>
  </main>

  if (session?.state === 'COMPLETED') return <AssessmentWorkspace session={session} api={api} onBack={closeSession} />

  return <main className={styles.shell}>
    <header className={styles.header}>
      <div><small>Учебный тренажёр 112 · кабинет преподавателя</small><h1>Занятия</h1><button type="button" onClick={() => setLibraryOpen(true)}>Библиотека сценариев</button></div>
      <label>Пользователь <select value={user.username} onChange={selectUser}>{users.map((item) => <option key={item.id} value={item.username}>{item.full_name}</option>)}</select></label>
    </header>
    {error && <p className={styles.error} role="alert">{error}</p>}
    {notice && <p className={styles.notice} role="status">{notice}</p>}
    {!session ? <div className={styles.content}>
      <div className={styles.topline}><div><h2>Учебные смены</h2><p>Подготовьте класс, затем запустите занятие.</p></div><button type="button" onClick={() => { setSettings(emptySettings); setSession({ id: null, state: 'DRAFT', runs: [], groups: [] }); setStep(0) }}>+ Новое занятие</button></div>
      {['DRAFT', 'READY', 'ACTIVE', 'COMPLETED'].map((state) => <section key={state} className={styles.section}>
        <h3>{state === 'DRAFT' || state === 'READY' ? 'Черновики' : state === 'ACTIVE' ? 'Активные' : 'Завершённые'}</h3>
        <div className={styles.cards}>{sessions.filter((item) => state === 'DRAFT' ? ['DRAFT', 'READY'].includes(item.state) : item.state === state).map((item) => <button key={item.id} type="button" onClick={() => openSession(item)} className={styles.card}>
          <strong>{item.title}</strong><span>{item.topic || 'Без темы'}</span><small>{stateLabels[item.state]} · {modeLabels[item.mode]} · {item.runs.length} участников</small>
        </button>)}</div>
      </section>)}
      <section className={styles.section}><h3>Шаблоны занятий</h3><div className={styles.cards}>{templates.map((item) => <button key={item.id} className={styles.card} type="button" disabled={busy} onClick={() => applyTemplate(item.id)}><strong>{item.name}</strong><small>Создать новый черновик</small></button>)}</div></section>
    </div> : <div className={styles.content}>
      <div className={styles.topline}><div><button className={styles.back} type="button" onClick={closeSession}>← Все занятия</button><h2>{session.id ? session.title : 'Новое занятие'}</h2><p>{session.id ? stateLabels[session.state] : 'Шаг 1 · основные параметры'}</p></div>{session.id && <span className={styles.badge}>№ {session.id}</span>}</div>
      <nav className={styles.steps} aria-label="Шаги подготовки">{steps.map((label, index) => <button key={label} type="button" className={step === index ? styles.activeStep : ''} disabled={!session.id && index > 0} onClick={() => setStep(index)}><b>{index + 1}</b>{label}</button>)}</nav>
      {step === 0 && <section className={styles.section}><h3>Основные параметры</h3><div className={styles.formGrid}>
        <label>Название занятия<input name="title" value={settings.title} onChange={updateSettings} disabled={!editable} required /></label>
        <label>Тема<input name="topic" value={settings.topic} onChange={updateSettings} disabled={!editable} /></label>
        <label>Режим<select name="mode" value={settings.mode} onChange={updateSettings} disabled={!editable}>{Object.entries(modeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label>Продолжительность, мин<input name="duration_minutes" type="number" min="1" max="480" value={settings.duration_minutes} onChange={updateSettings} disabled={!editable} /></label>
        {settings.mode === 'FLOW' && <label>Интервал выдачи, сек<input name="delivery_interval_seconds" type="number" min="10" max="3600" value={settings.delivery_interval_seconds} onChange={updateSettings} disabled={!editable} /></label>}
        <label>Порядок карточек<select name="delivery_order" value={settings.delivery_order} onChange={updateSettings} disabled={!editable}><option value="SEQUENTIAL">По порядку</option><option value="RANDOM">Случайным образом</option></select></label>
        <label>Рабочих мест<input name="workstation_count" type="number" min="1" max="100" value={settings.workstation_count} onChange={updateSettings} disabled={!editable} /></label>
      </div><div className={styles.actions}>{editable && <button type="button" disabled={busy || !settings.title.trim()} onClick={session.id ? saveSettings : createSession}>{session.id ? 'Сохранить и продолжить' : 'Создать и продолжить'}</button>}{session.id && <button type="button" onClick={() => setStep(1)}>Далее →</button>}</div></section>}
      {step === 1 && <section className={styles.section}><h3>Учебный класс</h3><p>Обучаемый выбирает свободное АРМ после входа. Состояние участия сохраняется при отключении браузера.</p><div className={styles.stationGrid}>{Array.from({ length: session.workstation_count }, (_, index) => {
        const run = stationByNumber.get(index + 1)
        return <div className={`${styles.station} ${run?.online ? styles.online : ''}`} key={index}><b>АРМ {String(index + 1).padStart(2, '0')}</b><span>{run?.trainee_name || 'Ожидание'}</span><small>{run ? run.online ? '● Online' : '○ Offline' : 'Свободно'}</small></div>
      })}</div><div className={styles.actions}><button type="button" onClick={() => setStep(2)}>К распределению →</button></div></section>}
      {step === 2 && <section className={styles.section}><h3>Распределение</h3><p>Выберите несколько АРМ и назначьте параметры одним действием.</p><div className={styles.layout}>
        <div><div className={styles.selectbar}><button type="button" onClick={() => setSelected(session.runs.map((run) => run.id))}>Выбрать всех</button><button type="button" onClick={() => setSelected([])}>Снять выбор</button><span>Выбрано: {selected.length}</span></div><div className={styles.runList}>{session.runs.map((run) => <label key={run.id} className={styles.run}><input type="checkbox" checked={selected.includes(run.id)} onChange={() => toggleRun(run.id)} disabled={!editable} /><b>АРМ {String(run.workstation_number).padStart(2, '0')}</b><span>{run.trainee_name}</span><small>{run.dds_profile === 'ДДС' ? 'Профиль не назначен' : run.dds_profile} · {run.difficulty || 'Сложность не задана'}</small></label>)}</div></div>
        <aside className={styles.sidebar}><h4>Массовое назначение</h4><label>Профиль ДДС<input value={assignment.dds_profile} onChange={(event) => setAssignment((current) => ({ ...current, dds_profile: event.target.value }))} placeholder="Например, ДДС района" disabled={!editable || !!assignment.group_id} /></label><label>Сложность<select value={assignment.difficulty} onChange={(event) => setAssignment((current) => ({ ...current, difficulty: event.target.value }))} disabled={!editable || !!assignment.group_id}><option>Начальная</option><option>Средняя</option><option>Высокая</option></select></label><label>Тип очереди<select value={assignment.queue_mode} onChange={(event) => setAssignment((current) => ({ ...current, queue_mode: event.target.value }))} disabled={!editable || !!assignment.group_id}><option value="INDIVIDUAL_QUEUE">Индивидуальная</option><option value="SHARED_QUEUE">Общая</option></select></label><label>Группа<select value={assignment.group_id} onChange={(event) => setAssignment((current) => ({ ...current, group_id: event.target.value }))} disabled={!editable}><option value="">Без группы</option>{session.groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select></label><button type="button" disabled={!editable || !selected.length || busy || (!assignment.group_id && !assignment.dds_profile.trim())} onClick={assignRuns}>Применить к выбранным</button></aside>
      </div><h4>Учебные группы</h4><div className={styles.cards}>{session.groups.map((group) => <div key={group.id} className={styles.card}><strong>{group.name}</strong><span>{group.dds_profile || 'Профиль не задан'} · {group.difficulty || 'Без сложности'}</span><small>{group.queue_mode === 'SHARED_QUEUE' ? 'Общая очередь' : 'Индивидуальная очередь'} · {group.run_ids.length} участников</small>{editable && <><button type="button" onClick={() => { setEditingGroupId(group.id); setGroupDraft({ name: group.name, dds_profile: group.dds_profile || '', difficulty: group.difficulty || 'Средняя', queue_mode: group.queue_mode }) }}>Изменить группу</button><button type="button" onClick={() => changeGroup(group, 'DELETE')}>Удалить группу</button></>}</div>)}</div>{editable && <div className={styles.groupForm}><input aria-label="Название группы" placeholder="Новая группа" value={groupDraft.name} onChange={(event) => setGroupDraft((current) => ({ ...current, name: event.target.value }))} /><input aria-label="Профиль ДДС группы" placeholder="Профиль ДДС" value={groupDraft.dds_profile} onChange={(event) => setGroupDraft((current) => ({ ...current, dds_profile: event.target.value }))} /><select aria-label="Сложность группы" value={groupDraft.difficulty} onChange={(event) => setGroupDraft((current) => ({ ...current, difficulty: event.target.value }))}><option>Начальная</option><option>Средняя</option><option>Высокая</option></select><select aria-label="Тип очереди группы" value={groupDraft.queue_mode} onChange={(event) => setGroupDraft((current) => ({ ...current, queue_mode: event.target.value }))}><option value="INDIVIDUAL_QUEUE">Индивидуальная</option><option value="SHARED_QUEUE">Общая</option></select><button type="button" disabled={!groupDraft.name.trim() || busy} onClick={saveGroup}>{editingGroupId ? 'Сохранить группу' : 'Создать группу'}</button>{editingGroupId && <button type="button" onClick={() => { setEditingGroupId(null); setGroupDraft(emptyGroup) }}>Отмена</button>}</div>}<div className={styles.actions}><button type="button" onClick={() => setStep(3)}>К заданиям →</button></div></section>}
      {step === 3 && <section className={styles.section}>
        <h3>Подготовленные задания</h3>
        <p>Карточки подготовлены до старта. Для FLOW требуется примерно {session.mode === 'FLOW' ? Math.ceil(session.duration_minutes * 60 / session.delivery_interval_seconds) : '—'} позиций на АРМ. Случайный порядок фиксируется при запуске.</p>
        {editable && <div className={styles.actions}>
          <label>На каждое АРМ или группу <input type="number" min="1" max="100" value={generateCount} onChange={(event) => setGenerateCount(event.target.value)} /></label>
          <button type="button" disabled={busy || !session.runs.length} onClick={generateQueue}>{queue.length ? 'Перегенерировать набор' : 'Сформировать набор'}</button>
          <button type="button" disabled={busy || !queue.length || queue.every((item) => item.approved)} onClick={approveQueue}>Утвердить набор</button>
        </div>}
        <div className={styles.scenarioList}>{queue.map((item) => <article className={styles.scenario} key={item.id}>
          <div><strong>{item.position}. {item.title}</strong><small>{item.training_group_id ? `Группа ${session.groups.find((group) => group.id === item.training_group_id)?.name || '—'}` : `АРМ ${session.runs.find((run) => run.id === item.training_run_id)?.workstation_number || '—'}`} · {item.approved ? 'Утверждена' : 'Ожидает утверждения'} · {item.delivery_state === 'DELIVERED' ? 'Выдана' : 'Не выдана'}{item.delivery_position ? ` · порядок ${item.delivery_position}` : ''}</small></div>
          <p>{item.snapshot.incident_type} · {item.snapshot.address}</p><p>{item.snapshot.description}</p>
          {editable && <div className={styles.actions}><button type="button" onClick={() => editScenario(item)}>Изменить</button><button type="button" onClick={() => replaceScenario(item.id)}>Заменить</button><button type="button" onClick={() => removeScenario(item.id)}>Удалить</button></div>}
        </article>)}</div>
        {!queue.length && <p>Пул пока пуст.</p>}
        {editable && <div className={styles.scenarioForm}><h4>{editingScenarioId ? 'Изменить карточку' : 'Добавить карточку'}</h4>
          {!editingScenarioId && <label>Очередь <select value={scenarioDraft.target} onChange={(event) => setScenarioDraft((current) => ({ ...current, target: event.target.value }))}><option value="">Выберите АРМ или группу</option>{session.runs.filter((run) => run.queue_mode === 'INDIVIDUAL_QUEUE').map((run) => <option key={run.id} value={`run:${run.id}`}>АРМ {run.workstation_number} · {run.trainee_name}</option>)}{session.groups.filter((group) => group.queue_mode === 'SHARED_QUEUE' && group.run_ids.length).map((group) => <option key={group.id} value={`group:${group.id}`}>Группа {group.name}</option>)}</select></label>}
          {['title', 'incident_type', 'address', 'description'].map((field) => <label key={field}>{({ title: 'Название', incident_type: 'Тип происшествия', address: 'Адрес', description: 'Описание' })[field]}<input value={scenarioDraft[field]} onChange={(event) => setScenarioDraft((current) => ({ ...current, [field]: event.target.value }))} /></label>)}
          <div className={styles.actions}><button type="button" disabled={busy || !scenarioDraft.title || !scenarioDraft.incident_type || !scenarioDraft.address || !scenarioDraft.description || (!editingScenarioId && !scenarioDraft.target)} onClick={saveScenario}>{editingScenarioId ? 'Сохранить изменение' : 'Добавить'}</button>{editingScenarioId && <button type="button" onClick={() => { setEditingScenarioId(null); setScenarioDraft(emptyScenario) }}>Отмена</button>}</div>
        </div>}
        <div className={styles.actions}><button type="button" onClick={() => setStep(4)}>К готовности →</button></div>
      </section>}
      {step === 4 && <section className={styles.section}><h3>Готовность занятия</h3><div className={styles.summary}><div><span>Участники</span><strong>{session.readiness.participant_count}</strong></div><div><span>Рабочие места</span><strong>{session.workstation_count}</strong></div><div><span>Группы</span><strong>{session.readiness.group_count}</strong></div><div><span>Карточки</span><strong>{session.readiness.approved_count}/{session.readiness.prepared_count}</strong></div><div><span>Профили назначены</span><strong>{session.readiness.profiles_assigned}/{session.readiness.participant_count}</strong></div><div><span>Online / offline</span><strong>{session.readiness.online_count} / {session.readiness.offline_count}</strong></div><div><span>Режим</span><strong>{modeLabels[session.mode]}</strong></div><div><span>Продолжительность</span><strong>{session.duration_minutes || '—'} мин</strong></div><div><span>Интервал</span><strong>{session.mode === 'FLOW' ? `${session.delivery_interval_seconds} сек` : '—'}</strong></div></div>{session.readiness.warnings.map((warning) => <p key={warning} className={styles.warning}>⚠ {warning}</p>)}<div className={styles.actions}>{session.state === 'DRAFT' && <button type="button" disabled={busy || !session.readiness.can_start} onClick={prepare}>Проверить готовность</button>}{session.state === 'READY' && <button type="button" disabled={busy || !session.readiness.can_start} onClick={start}>Запустить занятие</button>}</div><div className={styles.templateForm}><h4>Сохранить как шаблон</h4><p>Сохраняются параметры занятия и групп без участников.</p><input aria-label="Название шаблона" placeholder="Название шаблона" value={templateName} onChange={(event) => setTemplateName(event.target.value)} /><button type="button" disabled={!templateName.trim() || busy} onClick={saveTemplate}>Сохранить шаблон</button></div></section>}
    </div>}
  </main>
}

export default InstructorWorkspace
