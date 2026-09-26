import { useCallback, useEffect, useState } from 'react'
import { io } from 'socket.io-client'

import styles from './InstructorWorkspace.module.css'
import LiveMonitor from './LiveMonitor.jsx'
import AssessmentWorkspace from './AssessmentWorkspace.jsx'
import ScenarioLibrary from './ScenarioLibrary.jsx'
import InstructorGroups from './InstructorGroups.jsx'
import PreparedGroupCards from './PreparedGroupCards.jsx'
import AdvancedScenarioLibrary from './AdvancedScenarioLibrary.jsx'
import WorkspaceClock from './WorkspaceClock.jsx'
import { sessionStateLabels, trainingModeLabels } from './uiLabels.js'

const emptySettings = {
  title: `Практическое занятие · ${new Intl.DateTimeFormat('ru-RU', { timeZone: 'Europe/Moscow' }).format(new Date())}`, topic: '', mode: 'FLOW', duration_minutes: 30,
  delivery_interval_seconds: 120, delivery_order: 'SEQUENTIAL', workstation_count: 30,
}
const steps = ['Параметры занятия', 'Группы', 'Карточки происшествий', 'Подключение и запуск']
const emptyScenario = { title: '', target: '', address: '', description: '', incident_type: '' }
const stateLabels = sessionStateLabels
const modeLabels = trainingModeLabels

function InstructorWorkspace({ user, users, selectUser, requestJson, onLogout }) {
  const [sessions, setSessions] = useState([])
  const [templates, setTemplates] = useState([])
  const [session, setSession] = useState(null)
  const [step, setStep] = useState(0)
  const [settings, setSettings] = useState(emptySettings)
  const [templateName, setTemplateName] = useState('')
  const [queue, setQueue] = useState([])
  const [scenarioInstances, setScenarioInstances] = useState([])
  const [instanceTargets, setInstanceTargets] = useState({})
  const [scenarioDraft, setScenarioDraft] = useState(emptyScenario)
  const [editingScenarioId, setEditingScenarioId] = useState(null)
  const [generateCount, setGenerateCount] = useState(3)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [libraryKey, setLibraryKey] = useState(0)
  const [libraryDetailOpen, setLibraryDetailOpen] = useState(false)
  const [groupsOpen, setGroupsOpen] = useState(false)
  const [userGroups, setUserGroups] = useState([])
  const [pickerGroupId, setPickerGroupId] = useState(null)
  const [pickerTemplate, setPickerTemplate] = useState(null)
  const [libraryUse, setLibraryUse] = useState(null)
  const [useSessionId, setUseSessionId] = useState('')
  const [useGroupId, setUseGroupId] = useState('')
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
      const [queueItems, instances] = await Promise.all([
        api(`/api/training/sessions/${sessionId}/queue`),
        api(`/api/training/sessions/${sessionId}/scenario-instances`),
      ])
      setQueue(queueItems)
      setScenarioInstances(instances)
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
    if (!libraryUse && !pickerGroupId) return undefined

    const handleKeyDown = (event) => {
      if (event.key !== 'Escape') return
      setLibraryUse(null)
      setPickerGroupId(null)
      setPickerTemplate(null)
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [libraryUse, pickerGroupId])

  useEffect(() => {
    api('/api/training/user-groups').then(setUserGroups).catch((cause) => setError(cause.message))
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
    setGenerateCount(item.mode === 'FLOW' ? Math.min(100, Math.ceil(item.duration_minutes * 60 / item.delivery_interval_seconds) + 2) : 3)
    setQueue([])
    setScenarioInstances([])
    api(`/api/training/sessions/${item.id}/queue`).then(setQueue).catch((cause) => setError(cause.message))
    api(`/api/training/sessions/${item.id}/scenario-instances`).then(setScenarioInstances).catch((cause) => setError(cause.message))
    setStep(0)
  }

  const createSession = () => runAction(async () => {
    const item = await api('/api/training/sessions', jsonOptions('POST', settings))
    await reload(item.id)
    openSession(item)
    setStep(1)
    setNotice('Черновик занятия создан')
  })

  const saveSettings = () => runAction(async () => {
    const item = await api(`/api/training/sessions/${session.id}`, jsonOptions('PUT', settings))
    setSession(item)
    setStep(1)
    setNotice('Параметры сохранены')
  })

  const archiveSession = (item) => runAction(async () => {
    await api(`/api/training/sessions/${item.id}/archive`, { method: 'POST' })
    setSessions((current) => current.filter((candidate) => candidate.id !== item.id))
    setNotice(`Занятие «${item.title}» архивировано`)
  })

  const addUserGroup = (source) => runAction(async () => {
    if (!session?.id || session.groups.some((group) => group.source_user_group_id === source.id)) return
    const item = await api(`/api/training/sessions/${session.id}/groups`, jsonOptions('POST', {
      name: source.name, source_user_group_id: source.id, difficulty: 'Средняя', queue_mode: 'SHARED_QUEUE',
    }))
    setSession(item)
    setNotice(`Группа ${source.code || source.name} добавлена`)
  })

  const updateSessionGroup = (group, changes) => runAction(async () => {
    const item = await api(`/api/training/sessions/${session.id}/groups/${group.id}`, jsonOptions('PUT', {
      name: group.name, source_user_group_id: group.source_user_group_id,
      dds_profile: group.dds_profile, difficulty: group.difficulty,
      queue_mode: group.queue_mode, ...changes,
    }))
    setSession(item)
  })

  const changeGroup = (group, method) => runAction(async () => {
    const item = await api(`/api/training/sessions/${session.id}/groups/${group.id}`,
      method === 'DELETE' ? { method } : jsonOptions(method, group))
    setSession(item)
  })

  const start = () => runAction(async () => {
    if (session.state === 'DRAFT') {
      await api(`/api/training/sessions/${session.id}/prepare`, { method: 'POST' })
    }
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
  const prepareInstance = (instance) => runAction(async () => {
    const target = instanceTargets[instance.id]
    if (!target) return
    const [kind, id] = target.split(':')
    await api(`/api/scenario-instances/${instance.id}/materialize`, jsonOptions('POST', {
      [kind === 'group' ? 'training_group_id' : 'training_run_id']: Number(id),
    }))
    await reload(session.id)
    setNotice(`Экземпляр #${instance.id} добавлен в очередь`)
  })
  const editScenario = (item) => {
    setEditingScenarioId(item.id)
    setScenarioDraft({ title: item.title, target: item.training_group_id ? `group:${item.training_group_id}` : `run:${item.training_run_id}`, address: item.snapshot.address, description: item.snapshot.description, incident_type: item.snapshot.incident_type })
  }

  const updateSettings = (event) => {
    const { name, value, type } = event.target
    setSettings((current) => ({ ...current, [name]: type === 'number' ? Number(value) : value }))
  }
  const editable = session && ['DRAFT', 'READY'].includes(session.state)
  const closeSession = () => {
    window.sessionStorage.removeItem('ut112-instructor-session-id')
    setSession(null)
    reload()
  }

  const openSessions = () => {
    setLibraryOpen(false)
    setGroupsOpen(false)
    closeSession()
  }

  const openPicker = (groupId, template = null) => {
    setPickerGroupId(groupId)
    setPickerTemplate(template)
  }
  const closePicker = () => {
    setPickerGroupId(null)
    setPickerTemplate(null)
    if (session?.id) reload(session.id).catch((cause) => setError(cause.message))
  }
  const startUsingTemplate = () => {
    const item = sessions.find((entry) => entry.id === Number(useSessionId))
    const group = item?.groups.find((entry) => entry.id === Number(useGroupId))
    if (!item || !group) return
    openSession(item)
    setStep(2)
    setLibraryOpen(false)
    openPicker(group.id, libraryUse)
    setLibraryUse(null)
  }

  const renderNavigation = () => <aside className={styles.navigation}>
    <header><span>112</span><div><small>Учебный тренажёр</small><strong>Преподаватель</strong></div></header>
    <nav aria-label="Разделы кабинета преподавателя">
      <button type="button" className={!libraryOpen && !groupsOpen ? styles.navigationActive : ''} onClick={openSessions}>Занятия</button>
      <button type="button" className={groupsOpen ? styles.navigationActive : ''} onClick={() => { setGroupsOpen(true); setLibraryOpen(false) }}>Группы обучающихся</button>
      <button type="button" className={libraryOpen ? styles.navigationActive : ''} onClick={() => { setLibraryOpen(true); setGroupsOpen(false); setLibraryDetailOpen(false); setLibraryKey((value) => value + 1) }}>Библиотека сценариев</button>
      {libraryOpen && libraryDetailOpen && <>
        <span className={styles.navigationDivider} aria-hidden="true" />
        <button type="button" onClick={() => { setLibraryDetailOpen(false); setLibraryKey((value) => value + 1) }}>← Библиотека</button>
      </>}
      {session && <>
        <span className={styles.navigationDivider} aria-hidden="true" />
        {session.state === 'ACTIVE' && <button type="button" className={!libraryOpen ? styles.navigationActive : ''} onClick={() => setLibraryOpen(false)}>Live-монитор</button>}
        {session.state === 'COMPLETED' && <button type="button" className={!libraryOpen ? styles.navigationActive : ''} onClick={() => setLibraryOpen(false)}>Результаты и оценивание</button>}
        <button type="button" onClick={openSessions}>← Все занятия</button>
      </>}
    </nav>
    <footer><select value={user.username} onChange={selectUser}>{users.map((item) => <option key={item.id} value={item.username}>{item.full_name}</option>)}</select><small>Преподаватель</small><button type="button" onClick={onLogout}>Выйти</button></footer>
  </aside>

  const renderWorkspace = (title, content) => <main className={`${styles.shell} ${styles.instructorLayout}`}>
    {renderNavigation()}
    <section className={styles.workspace}>
      <header className={styles.header}>
        <div><h1>{title}</h1></div>
        <WorkspaceClock user={user} users={users} selectUser={selectUser} onLogout={onLogout} />
      </header>
      {content}
    </section>
  </main>

  if (groupsOpen) return renderWorkspace('Группы обучающихся', <div className={styles.content}><InstructorGroups api={api} onChanged={setUserGroups} /></div>)

  if (libraryOpen) return renderWorkspace('Библиотека сценариев', <div className={styles.embeddedContent}>
    <AdvancedScenarioLibrary key={libraryKey} embedded user={user} requestJson={requestJson} onViewChange={setLibraryDetailOpen} onUse={(item) => { setLibraryUse(item); setUseSessionId(String(session?.id || '')); setUseGroupId('') }} />
    {libraryUse && <div className={styles.pickerOverlay} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setLibraryUse(null) }}><section className={styles.useDialog} role="dialog" aria-modal="true" aria-label="Использовать сценарий"><h2>Использовать сценарий</h2><p>{libraryUse.name}</p><label>Занятие<select value={useSessionId} onChange={(event) => { setUseSessionId(event.target.value); setUseGroupId('') }}><option value="">Выберите занятие</option>{sessions.filter((item) => ['DRAFT', 'READY'].includes(item.state)).map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label><label>Группа<select value={useGroupId} onChange={(event) => setUseGroupId(event.target.value)}><option value="">Выберите группу</option>{sessions.find((item) => item.id === Number(useSessionId))?.groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select></label><div className={styles.actions}><button type="button" disabled={!useGroupId} onClick={startUsingTemplate}>Продолжить</button><button type="button" onClick={() => setLibraryUse(null)}>Отмена</button></div></section></div>}
  </div>)

  if (session?.state === 'ACTIVE') return renderWorkspace('Live-монитор', <>
    <div className={styles.content}>
      <LiveMonitor sessionId={session.id} user={user} api={api} />
    </div>
  </>)

  if (session?.state === 'COMPLETED') return renderWorkspace('Результаты и оценивание', <AssessmentWorkspace embedded session={session} api={api} />)

  return renderWorkspace(session ? steps[step] : 'Занятия', <>
    {error && <p className={styles.error} role="alert">{error}</p>}
    {notice && <p className={styles.notice} role="status">{notice}</p>}
    {!session ? <div className={styles.content}>
      <div className={styles.topline}><div><h2>Занятия</h2><p>Выберите группы и подготовьте материал до подключения класса.</p></div><button type="button" onClick={() => { setSettings({ ...emptySettings, title: `Практическое занятие · ${new Intl.DateTimeFormat('ru-RU', { timeZone: 'Europe/Moscow' }).format(new Date())}` }); setSession({ id: null, state: 'DRAFT', runs: [], groups: [] }); setStep(0) }}>+ Новое занятие</button></div>
      {['DRAFT', 'ACTIVE', 'COMPLETED'].map((state) => <section key={state} className={styles.section}>
        <h3>{state === 'DRAFT' || state === 'READY' ? 'Черновики' : state === 'ACTIVE' ? 'Активные' : 'Завершённые'}</h3>
        <div className={styles.itemList}>{sessions.filter((item) => state === 'DRAFT' ? ['DRAFT', 'READY'].includes(item.state) : item.state === state).map((item) => <article key={item.id} className={`${styles.itemRow} ${styles.sessionRow}`}>
          <strong>{item.title}</strong><span>{item.topic || 'Без темы'}</span><small>{stateLabels[item.state]} · {modeLabels[item.mode]} · {item.runs.length} участников</small>
          <div className={styles.actions}><button type="button" onClick={() => openSession(item)}>Изменить</button><button type="button" disabled={busy || item.state === 'ACTIVE'} title={item.state === 'ACTIVE' ? 'Сначала завершите активное занятие' : ''} onClick={() => archiveSession(item)}>Архивировать</button></div>
        </article>)}</div>
      </section>)}
      <section className={styles.section}><h3>Шаблоны занятий</h3><div className={styles.itemList}>{templates.map((item) => <button key={item.id} className={styles.itemRow} type="button" disabled={busy} onClick={() => applyTemplate(item.id)}><strong>{item.name}</strong><small>Создать новый черновик</small></button>)}</div></section>
    </div> : <div className={styles.content}>
      <div className={styles.topline}><div><h2>{session.id ? session.title : 'Новое занятие'}</h2><p>{session.id ? stateLabels[session.state] : 'Шаг 1 · основные параметры'}</p></div>{session.id && <span className={styles.badge}>№ {session.id}</span>}</div>
      <nav className={styles.steps} aria-label="Шаги подготовки">{steps.map((label, index) => <button key={label} type="button" className={step === index ? styles.activeStep : ''} disabled={!session.id && index > 0} onClick={() => setStep(index)}><b>{index + 1}</b>{label}</button>)}</nav>
      {step === 0 && <section className={styles.section}><h3>Параметры занятия</h3><div className={styles.formGrid}>
        <label>Название занятия<input name="title" value={settings.title} onChange={updateSettings} disabled={!editable} required /></label>
        <label>Режим<select name="mode" value={settings.mode} onChange={updateSettings} disabled={!editable}><option value="FLOW">Потоковая тренировка</option><option value="FIXED_SET">Набор карточек</option></select></label>
        {settings.mode === 'FLOW' && <label>Продолжительность, мин<input name="duration_minutes" type="number" min="1" max="480" value={settings.duration_minutes} onChange={updateSettings} disabled={!editable} /></label>}
        {settings.mode === 'FLOW' && <label>Интервал выдачи, сек<input name="delivery_interval_seconds" type="number" min="10" max="3600" value={settings.delivery_interval_seconds} onChange={updateSettings} disabled={!editable} /></label>}
        <label>Порядок карточек<select name="delivery_order" value={settings.delivery_order} onChange={updateSettings} disabled={!editable}><option value="SEQUENTIAL">По порядку</option><option value="RANDOM">Случайным образом</option></select></label>
      </div><div className={styles.actions}>{editable && <button type="button" disabled={busy || !settings.title.trim()} onClick={session.id ? saveSettings : createSession}>{session.id ? 'Сохранить и продолжить' : 'Создать занятие'}</button>}{session.id && <button type="button" onClick={() => setStep(1)}>Далее →</button>}</div></section>}
      {step === 1 && <>
        <section className={styles.section}><h3>Выберите группы для занятия</h3>
          <p>Постоянные группы можно добавить до подключения обучаемых.</p>
          <div className={styles.itemList}>{userGroups.filter((group) => !group.is_archived).map((source) => {
            const selectedGroup = session.groups.find((group) => group.source_user_group_id === source.id)
            return <article key={source.id} className={styles.itemRow}>
              <strong>{source.code || source.name}</strong><span>{source.name}</span><small>{source.member_count} человек</small>
              <button type="button" disabled={!editable || busy} onClick={() => selectedGroup ? changeGroup(selectedGroup, 'DELETE') : addUserGroup(source)}>
                {selectedGroup ? '✓ В занятии · убрать' : 'Добавить в занятие'}
              </button>
            </article>
          })}</div>
          {!userGroups.some((group) => !group.is_archived) && <p>Создайте первую группу.</p>}
        </section>
        {editable && <InstructorGroups api={api} compact onChanged={setUserGroups} onCreated={addUserGroup} />}
        {session.groups.length > 0 && <section className={styles.section}><h3>Группы этого занятия</h3>
          <div className={styles.itemList}>{session.groups.map((group) => <article key={group.id} className={styles.itemRow}>
            <strong>{group.name}</strong>
            <label>Сложность<select value={group.difficulty || 'Средняя'} disabled={!editable || busy} onChange={(event) => updateSessionGroup(group, { difficulty: event.target.value })}>
              <option>Начальная</option><option>Средняя</option><option>Высокая</option>
            </select></label>
            <label>Карточки<select value={group.queue_mode} disabled={!editable || busy} onChange={(event) => updateSessionGroup(group, { queue_mode: event.target.value })}>
              <option value="SHARED_QUEUE">Общий пул</option><option value="INDIVIDUAL_QUEUE">Личный пул</option>
            </select></label>
            <small>{userGroups.find((source) => source.id === group.source_user_group_id)?.member_count ?? group.run_ids.length} человек</small>
          </article>)}</div>
        </section>}
        <div className={styles.actions}><button type="button" disabled={!session.groups.length} onClick={() => setStep(2)}>К карточкам →</button></div>
      </>}
      {step === 3 && <section className={styles.section}>
        <h3>Подключение и запуск</h3>
        <p>Подключённые обучаемые автоматически получают группу по постоянному составу. Здесь можно изменить группу только для этого занятия.</p>
        <div className={styles.stationGrid}>{session.runs.map((run) => <div className={`${styles.station} ${run.online ? styles.online : ''}`} key={run.id}>
          <b>АРМ {String(run.workstation_number).padStart(2, '0')}</b><span>{run.trainee_name}</span>
          <small>{run.online ? '● Подключён' : '○ Не в сети'}</small>
          <label>Группа на этом занятии<select aria-label={`Группа для АРМ ${run.workstation_number}`} value={run.group_id || ''} disabled={!editable || busy} onChange={(event) => {
            const groupId = event.target.value ? Number(event.target.value) : null
            runAction(async () => {
              const item = await api(`/api/training/sessions/${session.id}/assign`, jsonOptions('POST', { run_ids: [run.id], group_id: groupId }))
              setSession(item)
            })
          }}><option value="">Не распределён</option>{session.groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select></label>
        </div>)}</div>
        {!session.runs.length && <p>Ожидаем подключения обучаемых.</p>}
        <h4>Готовность групп</h4>
        <div className={styles.itemList}>{session.groups.map((group) => {
          const cards = scenarioInstances.filter((item) => item.training_group_id === group.id)
          const connected = session.runs.filter((run) => run.group_id === group.id).length
          const ready = cards.length > 0 && cards.every((item) => item.status === 'CONFIRMED')
          return <article className={styles.itemRow} key={group.id}>
            <strong>{group.name}</strong>
            <span>{connected} подключено · {group.queue_mode === 'SHARED_QUEUE' ? 'Общий пул' : 'Личный пул'}</span>
            <small>{cards.length} {group.queue_mode === 'INDIVIDUAL_QUEUE' ? 'карточек каждому' : 'карточек'} · {ready ? '✓ Набор готов' : 'Набор не готов'}</small>
          </article>
        })}</div>
        <p>Не распределены: {session.runs.filter((run) => !run.group_id).length}. Они не получат карточки при запуске.</p>
        {session.readiness.warnings.map((warning) => <p key={warning} className={styles.warning}>⚠ {warning}</p>)}
        {['DRAFT', 'READY'].includes(session.state) && <div className={styles.actions}><button type="button" disabled={busy || !session.readiness.can_start} onClick={start}>Начать занятие</button></div>}
        <div className={styles.templateForm}><h4>Сохранить как шаблон</h4><p>Сохраняются параметры занятия и групп без участников.</p><input aria-label="Название шаблона" placeholder="Название шаблона" value={templateName} onChange={(event) => setTemplateName(event.target.value)} /><button type="button" disabled={!templateName.trim() || busy} onClick={saveTemplate}>Сохранить шаблон</button></div>
      </section>}
      {step === 2 && user.role !== 'ADMIN' && <section className={styles.section}>
        <h3>Карточки происшествий</h3>
        <p>Подготовьте для каждой группы карточки из одного или нескольких сценариев и утвердите проверенный набор.</p>
        <div className={styles.groupCardSets}>{session.groups.map((group) => <PreparedGroupCards key={group.id} group={group} sessionId={session.id} instances={scenarioInstances.filter((item) => item.training_group_id === group.id)} editable={editable} api={api} refresh={() => reload(session.id)} onAdd={openPicker} />)}</div>
        {!session.groups.length && <p>Сначала выберите группы занятия.</p>}
        <div className={styles.actions}><button type="button" onClick={() => setStep(3)}>К подключению →</button></div>
        {pickerGroupId && <div className={styles.pickerOverlay} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closePicker() }}><section className={styles.pickerDialog} role="dialog" aria-modal="true" aria-label="Выберите сценарий"><button type="button" className={styles.back} onClick={closePicker}>Закрыть</button><ScenarioLibrary key={`${session.id}:${pickerGroupId}:${pickerTemplate?.id || ''}`} embedded picker user={user} requestJson={requestJson} sessionId={session.id} groupId={pickerGroupId} groupDifficulty={session.groups.find((group) => group.id === pickerGroupId)?.difficulty} initialTemplate={pickerTemplate} onCompleted={closePicker} /></section></div>}
      </section>}
      {step === 2 && user.role === 'ADMIN' && <section className={styles.section}>
        <h3>Подготовленные задания</h3>
        <h4>Экземпляры из библиотеки</h4>
        <p>Выберите очередь для подтверждённого экземпляра. Исходная карточка будет выдана обычным механизмом занятия, а события появятся по учебному времени.</p>
        <div className={styles.itemList}>{scenarioInstances.map((item) => {
          const prepared = queue.find((entry) => entry.scenario_instance_id === item.id)
          return <article className={styles.itemRow} key={item.id}><strong>{item.name}</strong><span>{item.object_snapshot.name} · {item.object_snapshot.address}</span><small>Экземпляр #{item.id} · сложность {item.difficulty}/5 · {item.events.length} событий · {prepared ? prepared.delivery_state === 'DELIVERED' ? `Incident #${prepared.incident_id}` : 'В очереди' : 'Не подготовлен'}</small>{editable && !prepared && item.status === 'CONFIRMED' && <><select aria-label={`Очередь для экземпляра ${item.id}`} value={instanceTargets[item.id] || ''} onChange={(event) => setInstanceTargets((current) => ({ ...current, [item.id]: event.target.value }))}><option value="">Выберите АРМ или группу</option>{session.runs.filter((run) => run.queue_mode === 'INDIVIDUAL_QUEUE').map((run) => <option key={run.id} value={`run:${run.id}`}>АРМ {run.workstation_number} · {run.trainee_name}</option>)}{session.groups.filter((group) => group.queue_mode === 'SHARED_QUEUE' && group.run_ids.length).map((group) => <option key={group.id} value={`group:${group.id}`}>Группа {group.name}</option>)}</select><button type="button" disabled={busy || !instanceTargets[item.id]} onClick={() => prepareInstance(item)}>Добавить в очередь</button></>}</article>
        })}</div>
        {!scenarioInstances.length && <p>Экземпляры библиотеки пока не привязаны к занятию.</p>}
        {editable && <button type="button" onClick={() => setLibraryOpen(true)}>Открыть библиотеку сценариев</button>}
        <p>Карточки подготовлены до старта. Для FLOW требуется примерно {session.mode === 'FLOW' ? Math.ceil(session.duration_minutes * 60 / session.delivery_interval_seconds) : '—'} позиций на АРМ. Случайный порядок фиксируется при запуске.</p>
        {editable && <div className={styles.actions}>
          <label>На каждое АРМ или группу <input type="number" min="1" max="100" value={generateCount} onChange={(event) => setGenerateCount(event.target.value)} /></label>
          <button type="button" disabled={busy || !session.runs.length || queue.some((item) => item.scenario_instance_id)} onClick={generateQueue}>{queue.length ? 'Перегенерировать набор' : 'Сформировать набор'}</button>
          <button type="button" disabled={busy || !queue.length || queue.every((item) => item.approved)} onClick={approveQueue}>Утвердить набор</button>
        </div>}
        <div className={styles.scenarioList}>{queue.map((item) => <article className={styles.scenario} key={item.id}>
          <div><strong>{item.position}. {item.title}</strong><small>{item.training_group_id ? `Группа ${session.groups.find((group) => group.id === item.training_group_id)?.name || '—'}` : `АРМ ${session.runs.find((run) => run.id === item.training_run_id)?.workstation_number || '—'}`} · {item.approved ? 'Утверждена' : 'Ожидает утверждения'} · {item.delivery_state === 'DELIVERED' ? 'Выдана' : 'Не выдана'}{item.delivery_position ? ` · порядок ${item.delivery_position}` : ''}</small></div>
          <p>{item.snapshot.incident_type} · {item.snapshot.address}</p><p>{item.snapshot.description}</p>
          {editable && <div className={styles.actions}>{!item.scenario_instance_id && <><button type="button" onClick={() => editScenario(item)}>Изменить</button><button type="button" onClick={() => replaceScenario(item.id)}>Заменить</button></>}<button type="button" onClick={() => removeScenario(item.id)}>Удалить</button></div>}
        </article>)}</div>
        {!queue.length && <p>Пул пока пуст.</p>}
        {editable && <div className={styles.scenarioForm}><h4>{editingScenarioId ? 'Изменить карточку' : 'Добавить карточку'}</h4>
          {!editingScenarioId && <label>Очередь <select value={scenarioDraft.target} onChange={(event) => setScenarioDraft((current) => ({ ...current, target: event.target.value }))}><option value="">Выберите АРМ или группу</option>{session.runs.filter((run) => run.queue_mode === 'INDIVIDUAL_QUEUE').map((run) => <option key={run.id} value={`run:${run.id}`}>АРМ {run.workstation_number} · {run.trainee_name}</option>)}{session.groups.filter((group) => group.queue_mode === 'SHARED_QUEUE' && group.run_ids.length).map((group) => <option key={group.id} value={`group:${group.id}`}>Группа {group.name}</option>)}</select></label>}
          {['title', 'incident_type', 'address', 'description'].map((field) => <label key={field}>{({ title: 'Название', incident_type: 'Тип происшествия', address: 'Адрес', description: 'Описание' })[field]}<input value={scenarioDraft[field]} onChange={(event) => setScenarioDraft((current) => ({ ...current, [field]: event.target.value }))} /></label>)}
          <div className={styles.actions}><button type="button" disabled={busy || !scenarioDraft.title || !scenarioDraft.incident_type || !scenarioDraft.address || !scenarioDraft.description || (!editingScenarioId && !scenarioDraft.target)} onClick={saveScenario}>{editingScenarioId ? 'Сохранить изменение' : 'Добавить'}</button>{editingScenarioId && <button type="button" onClick={() => { setEditingScenarioId(null); setScenarioDraft(emptyScenario) }}>Отмена</button>}</div>
        </div>}
        <div className={styles.actions}><button type="button" onClick={() => setStep(3)}>К подключению →</button></div>
      </section>}
    </div>}
  </>)
}

export default InstructorWorkspace
