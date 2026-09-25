import { useEffect, useMemo, useRef, useState } from 'react'
import { io } from 'socket.io-client'

import informationIcon from './assets/information.svg'
import styles from './App.module.css'
import AdminWorkspace from './AdminWorkspace.jsx'
import InstructorWorkspace from './InstructorWorkspace.jsx'
import TrainingEnrollment from './TrainingEnrollment.jsx'
import TrainingResults from './TrainingResults.jsx'
import ResponseChat from './ResponseChat'
import { ddsStatusLabels, incidentHistoryLabels, incidentSourceLabels, responseStateLabels } from './uiLabels.js'
import { previewActionStatuses, previewAvailableActions, previewCurrentStatus, previewServiceTiles, statusEditorActions } from './serviceStatusPreview.js'

const apiUrl = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

const roleLabels = {
  ADMIN: 'Администратор',
  INSTRUCTOR: 'Преподаватель',
  TRAINEE: 'Диспетчер ДДС',
}

const lifecycleLabels = {
  CREATED: 'Создана',
  DELIVERED: 'Добавлена',
  OPENED: 'Получена службой',
  FINISHED: 'Завершена',
}

const actionLabels = {
  ACCEPT: 'Принята',
  REJECT: 'Не принята',
  START_RESPONSE: 'Начало реагирования',
  MARK_ARRIVAL: 'Прибытие',
  START_WORK: 'Проведение работ',
  COMPLETE_WORK: 'Работы завершены',
  REFUSE_WORK: 'Отказ от выполнения работ',
}

function registryServiceStatus(incident) {
  const latestStatus = incident.actions?.[incident.actions.length - 1]?.status
  if (latestStatus === 'SERVICE_RECEIVED') return 'Добавлена'
  if (latestStatus) return incidentHistoryLabels[latestStatus] || lifecycleLabels[incident.lifecycle_state]
  return incident.lifecycle_state === 'OPENED' ? 'Добавлена' : lifecycleLabels[incident.lifecycle_state]
}

function registryIncidentType(incident) {
  const code = incident.source_snapshot?.classifier_code
  return code == null || String(code).trim() === '' ? incident.incident_type : String(code)
}

const commentRequiredActions = new Set(['REJECT', 'REFUSE_WORK'])

const emptyFilters = {
  number: '',
  type: '',
  address: '',
  applicant: '',
  description: '',
  source: '',
  state: '',
}

const clockWeekdayFormatter = new Intl.DateTimeFormat('ru-RU', {
  weekday: 'long',
  timeZone: 'Europe/Moscow',
})

const clockMonthFormatter = new Intl.DateTimeFormat('ru-RU', {
  month: 'long',
  timeZone: 'Europe/Moscow',
})

const clockDayYearFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  year: 'numeric',
  timeZone: 'Europe/Moscow',
})

const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: '2-digit',
  timeZone: 'Europe/Moscow',
})

const fullDateFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'Europe/Moscow',
})

const timeFormatter = new Intl.DateTimeFormat('ru-RU', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
  timeZone: 'Europe/Moscow',
})

function formatDate(value) {
  return value ? dateFormatter.format(new Date(value)) : '—'
}

function formatTime(value) {
  return value ? timeFormatter.format(new Date(value)) : '—'
}

function formatDateTime(value) {
  return value ? `${formatDate(value)} ${formatTime(value)}` : '—'
}

function formatSavedDateTime(value) {
  return value ? `${fullDateFormatter.format(new Date(value))} в ${formatTime(value)}` : '—'
}

function formatClockDate(value) {
  const weekday = clockWeekdayFormatter.format(value)
  const month = clockMonthFormatter.format(value)
  const parts = clockDayYearFormatter.formatToParts(value)
  const day = parts.find((part) => part.type === 'day')?.value
  const year = parts.find((part) => part.type === 'year')?.value
  return `${weekday[0].toUpperCase()}${weekday.slice(1)}, ${day} ${month[0].toUpperCase()}${month.slice(1)} ${year}`
}

function compactServiceName(service) {
  return service
    .replace(/^ДДС\s+/i, '')
    .replace(/пожарной охраны/i, 'Служба 101')
    .replace(/скорой медицинской помощи/i, 'Служба 103')
    .replace(/полиции/i, 'Служба 102')
}

function includesText(value, filter) {
  return !filter || (value || '').toLocaleLowerCase('ru-RU').includes(filter.toLocaleLowerCase('ru-RU'))
}

function operationalValue(value) {
  if (value === null || value === undefined || value === '') return 'Не указано'
  if (typeof value === 'boolean') return value ? 'Да' : 'Нет'
  return String(value)
}

async function requestJson(path, demoUsername, options = {}) {
  const headers = new Headers(options.headers)
  if (demoUsername) headers.set('X-Demo-User', demoUsername)

  const response = await fetch(`${apiUrl}${path}`, { ...options, headers })
  if (!response.ok) {
    let detail = 'Backend локального стенда недоступен'
    try {
      const payload = await response.json()
      detail = Array.isArray(payload.detail)
        ? payload.detail.map((item) => item.msg).join('; ')
        : payload.detail || detail
    } catch {
      // Ответ без JSON оставляет понятное общее сообщение.
    }
    throw new Error(detail)
  }

  if (response.status === 204) return null

  return response.json()
}

function App() {
  const [users, setUsers] = useState([])
  const [currentUser, setCurrentUser] = useState(null)
  const [loginUsername, setLoginUsername] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [passwordVisible, setPasswordVisible] = useState(false)
  const [incidents, setIncidents] = useState([])
  const [joinedSessionId, setJoinedSessionId] = useState(null)
  const [selectedIncident, setSelectedIncident] = useState(null)
  const selectedIncidentId = useRef(null)
  const [selectedService, setSelectedService] = useState('')
  const [serviceHistoryOpen, setServiceHistoryOpen] = useState(false)
  const [statusEditorOpen, setStatusEditorOpen] = useState(false)
  const [selectedAction, setSelectedAction] = useState('')
  const [actionOrderNumber, setActionOrderNumber] = useState('')
  const [actionComment, setActionComment] = useState('')
  const [previewStatuses, setPreviewStatuses] = useState({})
  const [responseUnits, setResponseUnits] = useState([])
  const [responseAssignments, setResponseAssignments] = useState([])
  const [selectedResponseUnitId, setSelectedResponseUnitId] = useState('')
  const [selectedDispatchServiceId, setSelectedDispatchServiceId] = useState('')
  const [expandedSearch, setExpandedSearch] = useState(false)
  const [filters, setFilters] = useState(emptyFilters)
  const [now, setNow] = useState(() => new Date())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!currentUser) return
    const target = currentUser.role === 'ADMIN' ? '/admin' : '/'
    if (window.location.pathname !== target) window.history.replaceState(null, '', target)
  }, [currentUser])

  useEffect(() => {
    const savedUsername = window.sessionStorage.getItem('ut112-demo-username')
    requestJson('/api/users/demo')
      .then(async (demoUsers) => {
        setUsers(demoUsers)
        const trainee = demoUsers.find((user) => user.role === 'TRAINEE')
        setLoginUsername(trainee?.username || demoUsers[0]?.username || '')
        const admin = demoUsers.find((user) => user.role === 'ADMIN')
        const preferredUsername = window.location.pathname === '/admin'
          ? admin?.username
          : savedUsername
        if (preferredUsername) {
          try {
            const selected = await requestJson('/api/users/me', preferredUsername)
            window.sessionStorage.setItem('ut112-demo-username', selected.username)
            setCurrentUser(selected)
          } catch {
            window.sessionStorage.removeItem('ut112-demo-username')
          }
        }
      })
      .catch((requestError) => setError(requestError.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (currentUser?.role !== 'TRAINEE') {
      setIncidents([])
      return
    }

    let isCurrent = true
    setLoading(true)
    setError('')
    requestJson('/api/incidents', currentUser.username)
      .then((items) => {
        if (isCurrent) setIncidents(items)
      })
      .catch((requestError) => {
        if (isCurrent) setError(requestError.message)
      })
      .finally(() => {
        if (isCurrent) setLoading(false)
      })

    return () => {
      isCurrent = false
    }
  }, [currentUser])

  useEffect(() => {
    if (currentUser?.role !== 'TRAINEE') return undefined
    let active = true
    const refresh = async () => {
      try {
        const items = await requestJson('/api/incidents', currentUser.username)
        if (!active) return
        setIncidents(items)
        if (selectedIncidentId.current) {
          const fresh = await requestJson(`/api/incidents/${selectedIncidentId.current}`, currentUser.username)
          if (active) setSelectedIncident(fresh)
        }
      } catch (cause) { if (active) setError(cause.message) }
    }
    const socket = io(apiUrl, { auth: { username: currentUser.username } })
    socket.on('connect', async () => {
      try {
        const sessions = await requestJson('/api/training/sessions', currentUser.username)
        if (!active) return
        sessions.filter((item) => item.own_run)
          .forEach((item) => socket.emit('subscribe', { session_id: item.id }))
        refresh()
      } catch (cause) { if (active) setError(cause.message) }
    })
    socket.on('incident.delivered', refresh)
    socket.on('incident.opened', refresh)
    socket.on('incident.claimed', refresh)
    socket.on('incident.updated', refresh)
    socket.on('training.control_changed', refresh)
    const refreshResponse = (notice) => {
      refresh()
      if (notice.incident_id !== selectedIncidentId.current) return
      requestJson(`/api/response/incidents/${notice.incident_id}/assignments`, currentUser.username)
        .then((items) => { if (active) setResponseAssignments(items) })
        .catch((cause) => { if (active) setError(cause.message) })
    }
    socket.on('response.assignment_created', refreshResponse)
    socket.on('response.state_changed', refreshResponse)
    const fallback = window.setInterval(refresh, 30000)
    return () => { active = false; window.clearInterval(fallback); socket.disconnect() }
  }, [currentUser, joinedSessionId])

  useEffect(() => {
    selectedIncidentId.current = selectedIncident?.id || null
  }, [selectedIncident?.id])

  useEffect(() => {
    if (!selectedIncident) return
    const current = incidents.find((incident) => incident.id === selectedIncident.id)
    if (current) setSelectedIncident(current)
  }, [incidents, selectedIncident])


  const visibleIncidents = useMemo(() => incidents.filter((incident) => {
    const stateMatches = !filters.state
      || (filters.state === 'new' && !incident.opened_at)
      || (filters.state === 'opened' && Boolean(incident.opened_at))
    return stateMatches
      && includesText(incident.incident_number, filters.number)
      && (includesText(incident.incident_type, filters.type)
        || includesText(registryIncidentType(incident), filters.type))
      && includesText(incident.address, filters.address)
      && includesText(incident.applicant_name, filters.applicant)
      && includesText(incident.description, filters.description)
      && includesText(incident.source, filters.source)
  }), [filters, incidents])

  const updateFilter = (event) => {
    setFilters((current) => ({ ...current, [event.target.name]: event.target.value }))
  }

  const submitLogin = async (event) => {
    event.preventDefault()
    setError('')

    const normalizedUsername = loginUsername.trim().toLocaleLowerCase('ru-RU')
    const demoUser = users.find(
      (user) => user.username.toLocaleLowerCase('ru-RU') === normalizedUsername,
    )

    if (!demoUser) {
      setError('Пользователь не найден на локальном учебном стенде')
      return
    }
    if (!loginPassword) {
      setError('Введите учебный пароль')
      return
    }

    setLoading(true)
    try {
      const user = await requestJson('/api/users/login', null, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: demoUser.username, password: loginPassword }),
      })
      window.sessionStorage.setItem('ut112-demo-username', user.username)
      setCurrentUser(user)
      setLoginPassword('')
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  const logout = () => {
    window.sessionStorage.removeItem('ut112-demo-username')
    setCurrentUser(null)
    setIncidents([])
    setSelectedIncident(null)
    setSelectedService('')
    setServiceHistoryOpen(false)
    setStatusEditorOpen(false)
    setPreviewStatuses({})
    setFilters(emptyFilters)
    setError('')
  }

  const updateCurrentUser = (updatedUser) => {
    window.sessionStorage.setItem('ut112-demo-username', updatedUser.username)
    setUsers((current) => current.map((item) => (
      item.id === updatedUser.id ? { ...item, ...updatedUser } : item
    )))
    setCurrentUser(updatedUser)
  }

  const selectUser = async (event) => {
    const demoUsername = event.target.value
    setError('')
    setSelectedIncident(null)
    setSelectedService('')
    setServiceHistoryOpen(false)
    setStatusEditorOpen(false)
    setSelectedAction('')
    setActionOrderNumber('')
    setActionComment('')
    setPreviewStatuses({})
    setResponseUnits([])
    setResponseAssignments([])
    setSelectedResponseUnitId('')
    setFilters(emptyFilters)
    setLoading(true)

    try {
      const selected = await requestJson('/api/users/me', demoUsername)
      window.sessionStorage.setItem('ut112-demo-username', selected.username)
      setCurrentUser(selected)
    } catch (requestError) {
      setError(requestError.message)
      setLoading(false)
    }
  }

  const openCard = async (incident) => {
    setError('')
    setLoading(true)
    try {
      const isSharedReadOnly = incident.training_group_id && !incident.can_edit
      const openedIncident = await requestJson(
        `/api/incidents/${incident.id}${isSharedReadOnly ? '' : '/open'}`,
        currentUser.username,
        isSharedReadOnly ? undefined : { method: 'POST' },
      )
      const [units, assignments] = await Promise.all([
        requestJson(`/api/response/units?incident_id=${incident.id}`, currentUser.username),
        requestJson(`/api/response/incidents/${incident.id}/assignments`, currentUser.username),
      ])
      const services = [...new Set([
        ...(openedIncident.source_snapshot?.notified_services || []),
        openedIncident.viewer_dds_profile,
      ].filter((service) => service && service.trim().toUpperCase() !== 'ДДС'))]
      setSelectedIncident(openedIncident)
      setPreviewStatuses({})
      setSelectedService(openedIncident.can_edit && openedIncident.viewer_dds_profile === 'ДДС'
        ? 'Служба 102'
        : services.includes(openedIncident.viewer_dds_profile)
          ? openedIncident.viewer_dds_profile : services[0] || '')
      setServiceHistoryOpen(false)
      setStatusEditorOpen(false)
      setSelectedAction(openedIncident.available_actions?.[0] || '')
      setActionOrderNumber('')
      setActionComment('')
      setResponseUnits(units)
      setResponseAssignments(assignments)
      setSelectedDispatchServiceId(String((openedIncident.source_snapshot?.scenario_services || []).find((service) => !assignments.some((assignment) => assignment.dispatch_service_id === service.service_id))?.service_id || ''))
      setSelectedResponseUnitId(String(units.find(
        (unit) => !assignments.some((assignment) => assignment.response_unit.id === unit.id),
      )?.id || ''))
      setIncidents((items) =>
        items.map((item) => (item.id === openedIncident.id ? openedIncident : item)),
      )
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  const claimCard = async () => {
    if (!selectedIncident?.can_claim) return
    setError('')
    setLoading(true)
    try {
      const claimed = await requestJson(`/api/incidents/${selectedIncident.id}/claim`, currentUser.username, { method: 'POST' })
      await openCard(claimed)
      setIncidents(await requestJson('/api/incidents', currentUser.username))
    } catch (requestError) {
      setError(requestError.message)
      setIncidents(await requestJson('/api/incidents', currentUser.username))
    } finally {
      setLoading(false)
    }
  }

  const closeCard = () => {
    setSelectedIncident(null)
    setSelectedService('')
    setServiceHistoryOpen(false)
    setStatusEditorOpen(false)
    setSelectedAction('')
    setActionOrderNumber('')
    setActionComment('')
    setPreviewStatuses({})
    setResponseUnits([])
    setResponseAssignments([])
    setSelectedResponseUnitId('')
  }

  const selectService = (service) => {
    if ((isPreviewMode || service === selectedIncident.viewer_dds_profile) && getServiceStatus(service) === 'AWAITING_DECISION' && getServiceActions(service).includes('ACCEPT')) {
      setSelectedService(service)
      setServiceHistoryOpen(false)
      setSelectedAction('')
      setActionOrderNumber('')
      setActionComment('')
      setStatusEditorOpen(true)
      return
    }
    if (selectedService === service) {
      setServiceHistoryOpen((isOpen) => !isOpen)
      return
    }
    setSelectedService(service)
    setServiceHistoryOpen(true)
  }

  const openStatusEditor = () => {
    setSelectedAction('')
    setActionOrderNumber('')
    setActionComment('')
    setStatusEditorOpen(true)
  }

  const submitIncidentAction = async (event) => {
    event.preventDefault()
    if (!selectedAction) return

    if (isPreviewMode) {
      if (!getServiceActions(selectedService).includes(selectedAction)) return
      if (commentRequiredActions.has(selectedAction) && !actionComment.trim()) return
      const entries = [
        ...(previewStatuses[selectedService] || []),
        {
          id: `preview-${Date.now()}`,
          action: selectedAction,
          status: previewActionStatuses[selectedAction],
          actor_display_name: currentUser.full_name,
          is_system: false,
          order_number: actionOrderNumber.trim() || null,
          comment: actionComment.trim() || null,
          created_at: new Date().toISOString(),
        },
      ]
      const nextStatuses = { ...previewStatuses, [selectedService]: entries }
      setPreviewStatuses(nextStatuses)
      setSelectedAction('')
      setActionOrderNumber('')
      setActionComment('')
      setStatusEditorOpen(false)
      setServiceHistoryOpen(true)
      return
    }

    setError('')
    setLoading(true)
    try {
      const updatedIncident = await requestJson(
        `/api/incidents/${selectedIncident.id}/actions`,
        currentUser.username,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action: selectedAction,
            order_number: actionOrderNumber || null,
            comment: actionComment || null,
          }),
        },
      )
      setSelectedIncident(updatedIncident)
      setSelectedAction('')
      setActionOrderNumber('')
      setActionComment('')
      setStatusEditorOpen(false)
      setServiceHistoryOpen(true)
      setIncidents((items) =>
        items.map((item) => (item.id === updatedIncident.id ? updatedIncident : item)),
      )
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  const submitResponseAssignment = async (event) => {
    event.preventDefault()
    if (!selectedResponseUnitId || (selectedIncident?.scenario_instance_id && !selectedDispatchServiceId)) return
    setError('')
    setLoading(true)
    try {
      const assignment = await requestJson(
        `/api/response/incidents/${selectedIncident.id}/assignments`,
        currentUser.username,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ response_unit_id: Number(selectedResponseUnitId), dispatch_service_id: selectedDispatchServiceId ? Number(selectedDispatchServiceId) : null }),
        },
      )
      const updated = [...responseAssignments, assignment]
      setResponseAssignments(updated)
      setSelectedDispatchServiceId(String((selectedIncident.source_snapshot?.scenario_services || []).find((service) => !updated.some((item) => item.dispatch_service_id === service.service_id))?.service_id || ''))
      setSelectedResponseUnitId(String(responseUnits.find(
        (unit) => !updated.some((item) => item.response_unit.id === unit.id),
      )?.id || ''))
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  const refreshResponseAssignments = async () => {
    setError('')
    try {
      setResponseAssignments(await requestJson(
        `/api/response/incidents/${selectedIncident.id}/assignments`,
        currentUser.username,
      ))
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  if (currentUser?.role === 'INSTRUCTOR') {
    return <InstructorWorkspace user={currentUser} users={users} selectUser={selectUser} requestJson={requestJson} />
  }

  if (currentUser?.role === 'ADMIN') {
    return <AdminWorkspace user={currentUser} users={users} selectUser={selectUser} requestJson={requestJson} onLogout={logout} onCurrentUserUpdated={updateCurrentUser} />
  }

  if (!currentUser) {
    return (
      <main className={styles.loginScreen}>
        <div className={styles.trainingRibbon}>Учебный контур · данные и действия являются демонстрационными</div>

        <section className={styles.loginPanel} aria-labelledby="login-title">
          <header className={styles.loginBrand}>
            <div className={styles.loginNumber}>112</div>
            <div>
              <span>Учебный тренажёр</span>
              <strong id="login-title">Вход в систему</strong>
            </div>
          </header>

          <form className={styles.loginForm} onSubmit={submitLogin}>
            <label>
              <span>Пользователь</span>
              <div className={styles.loginSelectField}>
                <select
                  autoComplete="username"
                  disabled={loading || !users.length}
                  onChange={(event) => setLoginUsername(event.target.value)}
                  value={loginUsername}
                >
                  {!users.length && <option value="">Загрузка пользователей…</option>}
                  {users.map((user) => (
                    <option key={user.id} value={user.username}>
                      {user.full_name}
                    </option>
                  ))}
                </select>
                <span className={styles.chevronIcon} aria-hidden="true" />
              </div>
            </label>
            <label>
              <span>Пароль</span>
              <div className={styles.passwordField}>
                <input
                  autoComplete="current-password"
                  disabled={loading}
                  onChange={(event) => setLoginPassword(event.target.value)}
                  type={passwordVisible ? 'text' : 'password'}
                  value={loginPassword}
                />
                <button
                  aria-label={passwordVisible ? 'Скрыть пароль' : 'Показать пароль'}
                  onClick={() => setPasswordVisible((visible) => !visible)}
                  type="button"
                >
                  {passwordVisible ? 'скрыть' : 'показать'}
                </button>
              </div>
            </label>

            {error && <div className={styles.loginError} role="alert">{error}</div>}

            <button className={styles.loginButton} disabled={loading || !users.length} type="submit">
              {loading ? 'Подключение…' : 'Войти'}
            </button>
          </form>

          <footer className={styles.loginFooter}>
            <div><span>Локальный demo-доступ</span><strong>{loginUsername || 'загрузка…'} / любой пароль</strong></div>
            <p>Интерфейс имитирует рабочее место ДДС. Не используйте реальные учётные данные.</p>
          </footer>
        </section>

      </main>
    )
  }

  if (currentUser && currentUser.role !== 'TRAINEE') {
    return (
      <main className={styles.roleScreen}>
        <section>
          <div className={styles.systemName}>ГБУ Система 112</div>
          <h1>{roleLabels[currentUser.role]}</h1>
          <p>Для просмотра рабочего места ДДС выберите пользователя с ролью «Диспетчер ДДС».</p>
          <select value={currentUser.username} onChange={selectUser}>
            {users.map((user) => (
              <option key={user.id} value={user.username}>
                {user.full_name}
              </option>
            ))}
          </select>
          <button className={styles.roleLogout} type="button" onClick={logout}>Выйти</button>
        </section>
      </main>
    )
  }

  const snapshot = selectedIncident?.source_snapshot
  const classifierCode = selectedIncident && registryIncidentType(selectedIncident)
  const ownService = selectedIncident?.viewer_dds_profile
  const isPreviewMode = selectedIncident?.can_edit && ownService === 'ДДС'
  const services = isPreviewMode
    ? previewServiceTiles
    : [...new Set([...(snapshot?.notified_services || []), ownService]
      .filter((service) => service && service.trim().toUpperCase() !== 'ДДС'))]
  const features = snapshot?.features || []
  const hasStatusTile = (service) => isPreviewMode
    ? Boolean(previewStatuses[service]?.length)
    : service === ownService && getServiceStatus(service) !== 'AWAITING_DECISION'
  const getServiceActions = (service) => isPreviewMode
    ? previewAvailableActions(previewStatuses[service] || [])
    : service === ownService ? selectedIncident?.available_actions || [] : []
  const getServiceStatus = (service) => isPreviewMode
    ? previewCurrentStatus(previewStatuses[service] || [])
    : selectedIncident?.dds_status
  const isOwnServiceSelected = isPreviewMode || selectedService === ownService
  const ownServiceHistory = isPreviewMode
    ? [...(selectedIncident?.actions || []).filter((entry) => entry.is_system), ...(previewStatuses[selectedService] || [])]
    : selectedIncident?.actions || []
  const newCount = incidents.filter((incident) => !incident.opened_at).length
  const filtersActive = Object.values(filters).some(Boolean)
  const [clockHours, clockMinutes, clockSeconds] = formatTime(now).split(':')
  const canAssignResponse = selectedIncident?.can_edit && [
    'ACCEPTED', 'RESPONSE_STARTED', 'ARRIVED', 'WORKING',
  ].includes(selectedIncident.dds_status)
  const availableResponseUnits = responseUnits.filter(
    (unit) => !responseAssignments.some((assignment) => assignment.response_unit.id === unit.id),
  )

  return (
    <main className={styles.armShell}>
      {currentUser?.role === 'TRAINEE' && <TrainingEnrollment user={currentUser} requestJson={requestJson} onJoined={setJoinedSessionId} />}
      {currentUser?.role === 'TRAINEE' && <TrainingResults user={currentUser} requestJson={requestJson} />}
      {error && (
        <div className={styles.errorBanner} role="alert">
          <strong>Ошибка:</strong> {error}
        </div>
      )}

      {selectedIncident ? (
        <section className={styles.incidentWorkspace} aria-busy={loading}>
          {selectedIncident.training_group_id && (
            <div className={styles.errorBanner}>
              {selectedIncident.claimant_name
                ? `В работе: ${selectedIncident.claimant_name} · АРМ ${selectedIncident.claimant_workstation_number}`
                : 'Новая карточка общей очереди'}
              {selectedIncident.can_claim && <button type="button" onClick={claimCard} disabled={loading}>Взять в работу</button>}
              {!selectedIncident.can_claim && !selectedIncident.available_actions.length && <span> · просмотр без права изменения</span>}
            </div>
          )}
          <header className={styles.telephonyStrip}>
            <div className={styles.callState}>
              <span className={styles.headsetIcon}><span className={styles.phoneReceiverIcon} aria-hidden="true" /></span>
              <div><span>Отключение</span></div>
              <div className={styles.callButtons}>
                <button type="button" disabled title="Архив записей телефонных разговоров">записи звонков</button>
                <button type="button" disabled title="Входящие и исходящие SMS">список SMS</button>
              </div>
            </div>
            <div className={styles.phoneField}><div className={styles.phoneFieldIcons}><span className={styles.phoneIcon} aria-hidden="true" /><span className={styles.messageIcon} aria-hidden="true" /></div><span>АОН<strong>{selectedIncident.applicant_phone || 'не определён'}</strong></span></div>
            <div className={styles.phoneField}><div className={styles.phoneFieldIcons}><span className={styles.phoneIcon} aria-hidden="true" /><span className={styles.messageIcon} aria-hidden="true" /></div><span>предоставленный<strong>{selectedIncident.applicant_phone || 'не указан'}</strong></span></div>
            <div className={styles.phoneField}><div className={styles.phoneFieldIcons}><span className={styles.phoneIcon} aria-hidden="true" /><span className={styles.messageIcon} aria-hidden="true" /></div><span>телефон на место<strong>не указан</strong></span></div>
            <div className={styles.incidentIdentity}>
              <strong>Происшествие {selectedIncident.incident_number}</strong>
              <span>Сохр. {formatSavedDateTime(selectedIncident.delivered_at)}</span>
              <span>{selectedIncident.viewer_workstation_number
                ? `Учебное АРМ ${selectedIncident.viewer_workstation_number}` : 'Учебное АРМ не указано'}</span>
            </div>
            <div className={styles.viewTabs}>
              <button className={styles.viewTabActive} type="button" title="Режим просмотра сохранённой карточки">просмотр</button>
              <button type="button" disabled title="Дополнения к карточке">дополнение</button>
            </div>
          </header>

          <div className={styles.incidentInfoStrip}>
            <div><strong>{selectedIncident.applicant_name || 'ФИО заявителя не указано'}</strong><span>заявитель</span></div>
            <div className={styles.incidentIndicators}>
              <div className={styles.indicatorSummary}>
                <span>Пострадавшие: {operationalValue(snapshot?.victims)}</span>
                <span>Отказ от скорой: {operationalValue(snapshot?.ambulance_refusal)}</span>
                <span>Заблокированные: {operationalValue(snapshot?.blocked_people)}</span>
              </div>
              <div className={styles.indicatorActions}>
                <button type="button" disabled title="Признак чрезвычайной ситуации">ЧС <span className={styles.chsBoltIcon} aria-hidden="true" /></button>
                <button className={styles.emergencyButton} type="button" disabled title="Признак чрезвычайного происшествия">ЧП <span className={styles.warningIcon} aria-hidden="true" /></button>
                <button className={styles.pencilButton} type="button" disabled title="Редактирование классификации доступно оператору Службы 112"><span className={styles.editPencilIcon} aria-hidden="true" /></button>
              </div>
            </div>
          </div>

          <div className={styles.incidentBody}>
            <section className={styles.callerColumn}>
              <div className={styles.addressPanel}>
                <strong>{selectedIncident.address}</strong>
                <span>{selectedIncident.latitude !== null && selectedIncident.longitude !== null
                  ? `Координаты: ${selectedIncident.latitude}, ${selectedIncident.longitude}`
                  : 'Координаты не указаны'}</span>
                <button type="button" disabled title="Открыть точку происшествия на карте">⌖</button>
              </div>
              <div className={styles.reportPanel}>
                <strong>{formatDateTime(selectedIncident.reported_at)}</strong>
                <p>{selectedIncident.description}</p>
                {selectedIncident.scenario_events?.map((item) => <p key={item.id}><b>Новая вводная · {formatDateTime(item.created_at)}</b><br />{item.body}</p>)}
                <span>Источник: {incidentSourceLabels[selectedIncident.source] || selectedIncident.source}</span>
              </div>
            </section>

            <section className={styles.classificationColumn}>
              <div className={styles.classificationTitle} id={`classification-title-${selectedIncident.id}`}>
                <a href={`#classifier-${selectedIncident.id}`}>Происшествие {classifierCode}</a>
              </div>
              <div className={styles.classificationLine}>
                <strong>{features.length ? features.join(' · ') : selectedIncident.description}</strong>
              </div>
              <div className={styles.classificationLine}>Класс: <strong>{selectedIncident.incident_type}</strong>;</div>
              <div className={styles.classificationLine}>[ВИС] Класс:</div>
              <section className={styles.classifierDetails} id={`classifier-${selectedIncident.id}`} aria-label={`Тип происшествия ${classifierCode}`}>
                <div className={styles.classifierDetailsHeader}>
                  <strong>Тип происшествия {classifierCode}</strong>
                  <a href={`#classification-title-${selectedIncident.id}`}>Свернуть</a>
                </div>
                <dl>
                  <div><dt>Наименование</dt><dd>{selectedIncident.incident_type}</dd></div>
                  {snapshot?.classifier_group && <div><dt>Группа</dt><dd>{snapshot.classifier_group}</dd></div>}
                  {snapshot?.classifier_feature_1 && <div><dt>Признак 1</dt><dd>{snapshot.classifier_feature_1}</dd></div>}
                  {snapshot?.classifier_feature_2 && <div><dt>Признак 2</dt><dd>{snapshot.classifier_feature_2}</dd></div>}
                  {snapshot?.classifier_version && <div><dt>Версия классификатора</dt><dd>{snapshot.classifier_version}</dd></div>}
                </dl>
              </section>
            </section>
          </div>

          <div className={styles.serviceArea}>
            {serviceHistoryOpen && (
              <div
                className={`${styles.serviceHistory} ${!hasStatusTile(selectedService) ? styles.serviceHistoryBase : ''}`}
                style={{ left: `${70 + Math.max(0, services.indexOf(selectedService)) * 104}px` }}
                aria-label={`История статусов ${selectedService}`}
              >
                <button type="button" onClick={() => setServiceHistoryOpen(false)} aria-label="Закрыть историю">×</button>
                {isOwnServiceSelected ? (
                  <>
                    <div className={styles.historyList}>
                      {ownServiceHistory.map((entry) => (
                        <article key={entry.id} className={styles.historyEntry} title={entry.order_number ? `Номер наряда: ${entry.order_number}` : undefined}>
                          <span className={styles.historyActor} title={entry.actor_display_name}>оп. {selectedIncident.viewer_workstation_number || 0}</span>
                          <span className={styles.historyArrow} aria-hidden="true">›</span>
                          <span className={styles.historyEvent}><time>{formatDateTime(entry.created_at)}</time> {incidentHistoryLabels[entry.status] || entry.status}</span>
                          {entry.comment && <span className={styles.historyArrow} aria-hidden="true">›</span>}
                          {entry.comment && <p>{entry.comment}</p>}
                        </article>
                      ))}
                    </div>
                    {!getServiceActions(selectedService).length && (
                      <p className={styles.statusLocked}>Изменение статусов закрыто. История доступна только для просмотра.</p>
                    )}
                    {!isPreviewMode && <details className={styles.responsePanel}>
                      <summary>Виртуальная группа реагирования</summary>
                      <div className={styles.responseHeading}>
                        <strong>Виртуальная группа реагирования</strong>
                        <button type="button" onClick={refreshResponseAssignments}>Обновить</button>
                      </div>
                      {responseAssignments.map((assignment) => (
                        <div key={assignment.id} className={styles.responseAssignment}>
                          <span>{assignment.response_unit.name}</span>
                          <b>{responseStateLabels[assignment.state]}</b>
                          <time>{formatDateTime(assignment.state_changed_at)}</time>
                          <details>
                            <summary>История группы</summary>
                            {assignment.events.map((entry) => (
                              <div key={entry.id}>
                                {formatDateTime(entry.created_at)} · {responseStateLabels[entry.to_state]}
                              </div>
                            ))}
                          </details>
                          <ResponseChat
                            assignment={assignment}
                            incidentNumber={selectedIncident.incident_number}
                            username={currentUser.username}
                            apiUrl={apiUrl}
                            requestJson={requestJson}
                            formatDateTime={formatDateTime}
                          />
                        </div>
                      ))}
                      {canAssignResponse && availableResponseUnits.length > 0 && (
                        <form onSubmit={submitResponseAssignment}>
                          {!!selectedIncident.source_snapshot?.scenario_services?.length && <select aria-label="Служба сценария" value={selectedDispatchServiceId} onChange={(event) => setSelectedDispatchServiceId(event.target.value)} required><option value="">Выберите службу</option>{selectedIncident.source_snapshot.scenario_services.filter((service) => !responseAssignments.some((assignment) => assignment.dispatch_service_id === service.service_id)).map((service) => <option key={service.service_id} value={service.service_id}>{service.name}</option>)}</select>}
                          <select
                            aria-label="Доступная группа реагирования"
                            value={selectedResponseUnitId}
                            onChange={(event) => setSelectedResponseUnitId(event.target.value)}
                          >
                            {availableResponseUnits.map((unit) => (
                              <option key={unit.id} value={unit.id}>{unit.name}</option>
                            ))}
                          </select>
                          <button type="submit" disabled={loading || !selectedResponseUnitId || (selectedIncident.scenario_instance_id && !selectedDispatchServiceId)}>Назначить группу</button>
                        </form>
                      )}
                      {!canAssignResponse && <small>Назначение доступно после принятия карточки.</small>}
                      {canAssignResponse && !availableResponseUnits.length && !responseAssignments.length && (
                        <small>Для профиля ДДС пока нет доступных групп.</small>
                      )}
                    </details>}
                  </>
                ) : (
                  <div className={styles.readOnlyServiceHistory}>
                    <div><span>система</span><b>›</b><time>{formatDateTime(selectedIncident.delivered_at)}</time><em>Добавлена</em></div>
                    <small>Статусы другой службы доступны только для просмотра.</small>
                  </div>
                )}
              </div>
            )}

            {statusEditorOpen && isOwnServiceSelected && (
              <>
                <div className={styles.statusEditorBackdrop} onClick={() => setStatusEditorOpen(false)} aria-hidden="true" />
                <form className={styles.statusEditor} onSubmit={submitIncidentAction} role="dialog" aria-modal="true" aria-label="Изменение статуса службы">
                  <select aria-label="Статус" value={selectedAction} onChange={(event) => setSelectedAction(event.target.value)} required>
                    <option value="" disabled hidden>Статус</option>
                    {(getServiceActions(selectedService).includes('ACCEPT')
                      ? getServiceActions(selectedService).filter((action) => action === 'ACCEPT' || action === 'REJECT')
                      : statusEditorActions()).map((action) => (
                      <option key={action} value={action} disabled={!getServiceActions(selectedService).includes(action)}>{actionLabels[action]}</option>
                    ))}
                  </select>
                  <input aria-label="Номер наряда" placeholder="Номер наряда" maxLength="80" value={actionOrderNumber} onChange={(event) => setActionOrderNumber(event.target.value)} />
                  <input aria-label="Комментарий" placeholder="Комментарий" maxLength="2000" value={actionComment} onChange={(event) => setActionComment(event.target.value)} required={commentRequiredActions.has(selectedAction)} />
                  <button type="submit" aria-label="Сохранить статус" title="Сохранить статус" disabled={loading || !selectedAction || (commentRequiredActions.has(selectedAction) && !actionComment.trim())}>✓</button>
                  <button type="button" aria-label="Отменить изменение статуса" title="Отменить" onClick={() => setStatusEditorOpen(false)}>×</button>
                </form>
              </>
            )}

            <div className={styles.servicesDock}>
              <div className={styles.servicesLabel}>Службы:</div>
              {services.map((service) => (
                <div className={styles.serviceTileWrapper} key={service}>
                  {hasStatusTile(service) && (
                    <div className={`${styles.statusTile} ${selectedService === service && getServiceStatus(service) !== 'AWAITING_DECISION' ? styles.statusTileActive : ''}`}>
                      <button type="button" className={styles.statusTileMain} onClick={() => selectService(service)} title="Показать историю статусов">
                        <span className={`${styles.chevronIcon} ${styles.serviceChevron}`} aria-hidden="true" />
                        <strong title={selectedIncident.address}>{selectedIncident.address}</strong>
                        <small>{formatTime(isPreviewMode ? previewStatuses[service]?.at(-1)?.created_at || selectedIncident.delivered_at : ownServiceHistory.at(-1)?.created_at)} {getServiceStatus(service) === 'AWAITING_DECISION' ? 'Добавлена' : ddsStatusLabels[getServiceStatus(service)]}</small>
                      </button>
                      {selectedService === service && getServiceActions(service).length > 0 && (
                        <button className={styles.serviceEditButton} type="button" onClick={openStatusEditor} aria-label={`Добавить статус службы ${service}`} title="Добавить статус"><span className={styles.serviceEditIcon} aria-hidden="true" /></button>
                      )}
                    </div>
                  )}
                  <button
                    className={`${styles.serviceTile} ${selectedService === service && !hasStatusTile(service) ? styles.serviceTileActive : ''} ${service === 'Деп. ЖКХ' ? styles.serviceTileSecondary : ''}`}
                    type="button"
                    onClick={() => selectService(service)}
                    title={(isPreviewMode || service === ownService) && getServiceStatus(service) === 'AWAITING_DECISION' ? 'Выбрать начальный статус' : 'Показать историю статусов'}
                  >
                    <span className={`${styles.chevronIcon} ${styles.serviceChevron}`} aria-hidden="true" />
                    <strong>{compactServiceName(service)}</strong>
                    <small>{formatTime(selectedIncident.delivered_at)} Добавлена</small>
                  </button>
                </div>
              ))}
              {!isPreviewMode && ['Доп. ЖКХ', 'ЦЭМП', 'ЦОДД', 'Мос.Без.'].map((service) => (
                <button className={`${styles.serviceTile} ${styles.serviceTileMuted}`} key={service} type="button" disabled>
                  <span className={`${styles.chevronIcon} ${styles.serviceChevron}`} aria-hidden="true" /><strong>{service}</strong><small>не оповещена</small>
                </button>
              ))}
              <button className={styles.dockControl} type="button" onClick={() => setServiceHistoryOpen((isOpen) => !isOpen)} title="Развернуть или свернуть историю выбранной службы">
                <span className={styles.dockChevronPair} aria-hidden="true">
                  <span className={`${styles.chevronIcon} ${styles.chevronUp}`} />
                  <span className={styles.chevronIcon} />
                </span>
              </button>
              <div className={styles.dockSpacer} />
              <button className={styles.dockControl} type="button" disabled title="Информация по карточке">
                <img className={styles.dockInformationIcon} src={informationIcon} alt="" />
              </button>
              <button className={styles.closeCardButton} type="button" onClick={closeCard} title="Закрыть карточку и вернуться к списку">×</button>
            </div>
          </div>
        </section>
      ) : (
        <section className={styles.registryWorkspace} aria-busy={loading}>
          <header className={styles.registrySearchArea}>
            <div className={styles.searchPanel}>
              <div className={styles.searchTitleRow}>
                <h1>Поиск происшествий</h1>
                <span aria-hidden="true">⌕</span>
              </div>
              <div className={styles.searchControls}>
                <button className={styles.expandSearchButton} type="button" aria-expanded={expandedSearch} onClick={() => setExpandedSearch((isOpen) => !isOpen)}>
                  расширенный по параметрам <span className={`${styles.chevronIcon} ${expandedSearch ? styles.chevronUp : ''}`} aria-hidden="true" />
                </button>
                <button type="button" onClick={() => setFilters(emptyFilters)} disabled={!filtersActive}>сбросить</button>
              </div>
            </div>

            <div className={styles.clockPanel}>
              <div className={styles.clockUpper}>
                <div className={styles.clockDetails}>
                  <strong>{formatClockDate(now)}</strong>
                  <div className={styles.clockToolbar}>
                    <span>УМЦ О.п.</span>
                    <label className={styles.clockUserPicker} title={`Сменить пользователя: ${currentUser?.full_name || ''}`}>
                      <span className={styles.clockMonitorIcon} aria-hidden="true" />
                      <select value={currentUser?.username || ''} onChange={selectUser} disabled={!users.length} aria-label="Текущий пользователь">
                        {users.map((user) => (
                          <option key={user.id} value={user.username}>{user.full_name}</option>
                        ))}
                      </select>
                    </label>
                    <span className={styles.clockGearIcon} aria-hidden="true" />
                    <span className={styles.clockHelpIcon} aria-hidden="true" />
                    <button className={styles.sessionExit} type="button" onClick={logout} aria-label="Выйти" title="Выйти">
                      <span className={styles.clockRunIcon} aria-hidden="true" />
                    </button>
                  </div>
                </div>
                <time className={styles.clockTime} dateTime={formatTime(now)}>
                  <span>{clockHours}:{clockMinutes}</span><sup>:{clockSeconds}</sup>
                </time>
              </div>
              <div className={styles.clockLower} aria-hidden="true" />
            </div>
          </header>

          {expandedSearch && (
            <form className={styles.advancedSearch} onSubmit={(event) => event.preventDefault()}>
              <label>тип происшествия<input name="type" value={filters.type} onChange={updateFilter} /></label>
              <label>признаки происшествия<input name="description" value={filters.description} onChange={updateFilter} /></label>
              <label>по адресу<input name="address" value={filters.address} onChange={updateFilter} /></label>
              <label>по заявителю (ФИО/АОН)<input name="applicant" value={filters.applicant} onChange={updateFilter} /></label>
              <label>источник происшествия<input name="source" value={filters.source} onChange={updateFilter} /></label>
              <label>по номеру карточки<input name="number" value={filters.number} onChange={updateFilter} /></label>
              <label>статус<select name="state" value={filters.state} onChange={updateFilter}><option value="">любой</option><option value="new">Добавлена</option><option value="opened">Получена службой</option></select></label>
              <button type="button" onClick={() => setFilters(emptyFilters)}>сбросить</button>
            </form>
          )}

          <section className={styles.registryContent}>
            <div className={styles.registryToolbar}>
              <h2>Список происшествий <span className={`${styles.chevronIcon} ${styles.chevronUp}`} aria-hidden="true" /></h2>
              <div><span>ⓘ уведомления</span><select disabled><option>выберите что показать</option></select></div>
            </div>

            <div className={styles.registryHeader} aria-hidden="true">
              <span /><span className={styles.linksHeader}>Связи</span><span className={styles.emergencyHeader}>ЧС</span><span>Опер.</span><span>АРМ</span><span>Номер</span><span className={styles.dateHeader}>Дата <span className={styles.arrowDownIcon} /></span><span>Время</span><span>Тип происшествия</span><span>Постр.</span><span>Адрес</span><span>Статус службы</span><span />
            </div>

            <div className={styles.registryRows}>
              {loading && !incidents.length ? (
                <div className={styles.registryEmpty}>Загрузка происшествий…</div>
              ) : visibleIncidents.length ? visibleIncidents.map((incident) => {
                const incidentTime = formatTime(incident.reported_at)
                return <button
                  key={incident.id}
                  className={`${styles.registryRow} ${!incident.opened_at ? styles.registryRowNew : ''}`}
                  type="button"
                  onClick={() => openCard(incident)}
                >
                  <span className={styles.linkCell}><span className={`${styles.chevronIcon} ${styles.chevronDownIcon}`} aria-hidden="true" /></span>
                  <span />
                  <span><span className={styles.emergencyBookmark} aria-hidden="true" /></span>
                  <span><span className={styles.electricityIcon} aria-hidden="true" /></span>
                  <span><span className={styles.timerIcon} aria-hidden="true" /></span>
                  <span className={`${styles.operatorCell} ${incident.opened_at ? styles.operatorCellZero : ''}`}>{incident.opened_at ? '0' : '!'}</span>
                  <span>{incident.viewer_workstation_number || '—'}</span>
                  <strong>{incident.incident_number}</strong>
                  <span>{formatDate(incident.reported_at)}</span>
                  <time dateTime={incidentTime}><span>{incidentTime.slice(0, 5)}</span><sup>{incidentTime.slice(5)}</sup></time>
                  <strong title={incident.incident_type}>{registryIncidentType(incident)}</strong>
                  <span>{operationalValue(incident.source_snapshot?.victims)}</span>
                  <strong className={styles.registryAddress}><span className={styles.registryAddressText}>{incident.address}</span><span className={styles.locationOffIcon} aria-hidden="true" /></strong>
                  <span className={styles.serviceState}>{incident.claimant_name ? `${incident.claimant_name} · АРМ ${incident.claimant_workstation_number} · ` : ''}{registryServiceStatus(incident)}</span>
                  <span className={styles.fileIconCell}><span className={styles.fileTextIcon} aria-hidden="true" /></span>
                  <small><b>Описание:</b><time>{formatDateTime(incident.reported_at)}</time><span>УМЦ О.п.</span><strong>{incident.description}</strong></small>
                </button>
              }) : (
                <div className={styles.registryEmpty}>{filtersActive ? 'Происшествия не найдены' : 'Происшествий нет'}</div>
              )}
            </div>

            <footer className={styles.registryPager}>
              <span>Новые: {newCount}</span>
              <span>Страница: 1 <span className={styles.chevronIcon} aria-hidden="true" /></span>
              <span>Записей на странице: 10 <span className={styles.chevronIcon} aria-hidden="true" /></span>
              <strong>{visibleIncidents.length ? `1-${visibleIncidents.length}` : '0'} из {visibleIncidents.length}</strong>
              <button type="button" disabled>‹</button><button type="button" disabled>›</button>
            </footer>
          </section>
        </section>
      )}
    </main>
  )
}

export default App
