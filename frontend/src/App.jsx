import { useEffect, useMemo, useState } from 'react'
import { io } from 'socket.io-client'

import styles from './App.module.css'
import InstructorWorkspace from './InstructorWorkspace.jsx'
import TrainingEnrollment from './TrainingEnrollment.jsx'
import ResponseChat from './ResponseChat'

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

const ddsStatusLabels = {
  AWAITING_DECISION: 'Ожидает решения',
  ACCEPTED: 'Принята',
  REJECTED: 'Не принята',
  RESPONSE_STARTED: 'Начало реагирования',
  ARRIVED: 'Прибытие',
  WORKING: 'Проведение работ',
  COMPLETED: 'Работы завершены',
  WORK_REFUSED: 'Отказ от выполнения работ',
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

const historyStatusLabels = {
  SERVICE_ADDED: 'Добавлена',
  SERVICE_RECEIVED: 'Получена службой',
  ...ddsStatusLabels,
}

const responseStateLabels = {
  ASSIGNED: 'Назначена',
  ACKNOWLEDGED: 'Задание подтверждено',
  EN_ROUTE: 'Выехала',
  ARRIVED: 'Прибыла',
  WORKING: 'Выполняет работы',
  COMPLETED: 'Работы завершила',
  CANCELLED: 'Назначение отменено',
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

const fullDateFormatter = new Intl.DateTimeFormat('ru-RU', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
  timeZone: 'Europe/Moscow',
})

const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: '2-digit',
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
  const [selectedService, setSelectedService] = useState('')
  const [serviceHistoryOpen, setServiceHistoryOpen] = useState(false)
  const [selectedAction, setSelectedAction] = useState('')
  const [actionComment, setActionComment] = useState('')
  const [responseUnits, setResponseUnits] = useState([])
  const [responseAssignments, setResponseAssignments] = useState([])
  const [selectedResponseUnitId, setSelectedResponseUnitId] = useState('')
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
    const savedUsername = window.sessionStorage.getItem('ut112-demo-username')
    requestJson('/api/users/demo')
      .then(async (demoUsers) => {
        setUsers(demoUsers)
        const trainee = demoUsers.find((user) => user.role === 'TRAINEE')
        setLoginUsername(trainee?.username || demoUsers[0]?.username || '')
        if (savedUsername) {
          try {
            setCurrentUser(await requestJson('/api/users/me', savedUsername))
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
    const refresh = () => requestJson('/api/incidents', currentUser.username)
      .then((items) => { if (active) setIncidents(items) })
      .catch((cause) => { if (active) setError(cause.message) })
    const socket = io(apiUrl, { auth: { username: currentUser.username } })
    socket.on('connect', async () => {
      try {
        const sessions = await requestJson('/api/training/sessions', currentUser.username)
        if (!active) return
        sessions.filter((item) => item.trainee_ids.includes(currentUser.id))
          .forEach((item) => socket.emit('subscribe', { session_id: item.id }))
        refresh()
      } catch (cause) { if (active) setError(cause.message) }
    })
    socket.on('incident.delivered', refresh)
    socket.on('incident.claimed', refresh)
    socket.on('incident.updated', refresh)
    const fallback = window.setInterval(refresh, 30000)
    return () => { active = false; window.clearInterval(fallback); socket.disconnect() }
  }, [currentUser, joinedSessionId])

  useEffect(() => {
    if (!selectedIncident?.training_group_id) return
    const current = incidents.find((incident) => incident.id === selectedIncident.id)
    if (current) setSelectedIncident(current)
  }, [incidents, selectedIncident?.id, selectedIncident?.training_group_id])

  const visibleIncidents = useMemo(() => incidents.filter((incident) => {
    const stateMatches = !filters.state
      || (filters.state === 'new' && !incident.opened_at)
      || (filters.state === 'opened' && Boolean(incident.opened_at))
    return stateMatches
      && includesText(incident.incident_number, filters.number)
      && includesText(incident.incident_type, filters.type)
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
      const user = await requestJson('/api/users/me', demoUser.username)
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
    setFilters(emptyFilters)
    setError('')
  }

  const selectUser = async (event) => {
    const demoUsername = event.target.value
    setError('')
    setSelectedIncident(null)
    setSelectedService('')
    setServiceHistoryOpen(false)
    setSelectedAction('')
    setActionComment('')
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
      const services = openedIncident.source_snapshot?.notified_services || []
      setSelectedIncident(openedIncident)
      setSelectedService(services[0] || 'Служба ДДС')
      setServiceHistoryOpen(true)
      setSelectedAction(openedIncident.available_actions?.[0] || '')
      setActionComment('')
      setResponseUnits(units)
      setResponseAssignments(assignments)
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
    setSelectedAction('')
    setActionComment('')
    setResponseUnits([])
    setResponseAssignments([])
    setSelectedResponseUnitId('')
  }

  const selectService = (service) => {
    if (selectedService === service) {
      setServiceHistoryOpen((isOpen) => !isOpen)
      return
    }
    setSelectedService(service)
    setServiceHistoryOpen(true)
    if (service === services[0]) {
      setSelectedAction(selectedIncident.available_actions?.[0] || '')
      setActionComment('')
    }
  }

  const submitIncidentAction = async (event) => {
    event.preventDefault()
    if (!selectedAction) return

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
            comment: actionComment || null,
          }),
        },
      )
      setSelectedIncident(updatedIncident)
      setSelectedAction(updatedIncident.available_actions?.[0] || '')
      setActionComment('')
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
    if (!selectedResponseUnitId) return
    setError('')
    setLoading(true)
    try {
      const assignment = await requestJson(
        `/api/response/incidents/${selectedIncident.id}/assignments`,
        currentUser.username,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ response_unit_id: Number(selectedResponseUnitId) }),
        },
      )
      const updated = [...responseAssignments, assignment]
      setResponseAssignments(updated)
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
                <span aria-hidden="true">⌄</span>
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
  const services = snapshot?.notified_services || []
  const features = snapshot?.features || []
  const ownService = services[0] || 'Служба ДДС'
  const isOwnServiceSelected = selectedService === ownService
  const ownServiceHistory = selectedIncident?.actions || []
  const latestOwnStatus = ownServiceHistory[ownServiceHistory.length - 1]
  const newCount = incidents.filter((incident) => !incident.opened_at).length
  const filtersActive = Object.values(filters).some(Boolean)
  const canAssignResponse = selectedIncident && [
    'ACCEPTED', 'RESPONSE_STARTED', 'ARRIVED', 'WORKING',
  ].includes(selectedIncident.dds_status)
  const availableResponseUnits = responseUnits.filter(
    (unit) => !responseAssignments.some((assignment) => assignment.response_unit.id === unit.id),
  )

  return (
    <main className={styles.armShell}>
      {currentUser?.role === 'TRAINEE' && <TrainingEnrollment user={currentUser} requestJson={requestJson} onJoined={setJoinedSessionId} />}
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
              <div><span>не подключен</span><small>линия оператора</small></div>
              <div className={styles.callButtons}>
                <button type="button" disabled title="Архив записей телефонных разговоров">записи звонков</button>
                <button type="button" disabled title="Входящие и исходящие SMS">список SMS</button>
              </div>
            </div>
            <div className={styles.phoneField}><b><span className={styles.phoneIcon} aria-hidden="true" /></b><span>АОН<strong>{selectedIncident.applicant_phone || 'не определён'}</strong></span><i>▰</i></div>
            <div className={styles.phoneField}><b><span className={styles.phoneIcon} aria-hidden="true" /></b><span>предоставленный<strong>{selectedIncident.applicant_phone || 'не указан'}</strong></span><i>▰</i></div>
            <div className={styles.phoneField}><b><span className={styles.phoneIcon} aria-hidden="true" /></b><span>телефон на место<strong>не указан</strong></span></div>
            <div className={styles.incidentIdentity}>
              <strong>Происшествие {selectedIncident.incident_number}</strong>
              <span>Сохр. {formatDateTime(selectedIncident.delivered_at)}</span>
              <span>Опер. 0, АРМ 4, УМЦ О.п.</span>
            </div>
            <div className={styles.viewTabs}>
              <button className={styles.viewTabActive} type="button" title="Режим просмотра сохранённой карточки">просмотр</button>
              <button type="button" disabled title="Дополнения к карточке">дополнение</button>
            </div>
          </header>

          <div className={styles.incidentInfoStrip}>
            <div><strong>{selectedIncident.applicant_name || 'ФИО заявителя не указано'}</strong><span>заявитель</span></div>
            <div className={styles.incidentIndicators}>
              <span>Пострадавшие: нет</span>
              <span>Отказ от скорой: нет</span>
              <span>Заблокированные: нет</span>
              <button type="button" disabled title="Признак чрезвычайной ситуации">ЧС ⚡</button>
              <button className={styles.emergencyButton} type="button" disabled title="Признак чрезвычайного происшествия">ЧП ▲</button>
              <button className={styles.pencilButton} type="button" disabled title="Редактирование классификации доступно оператору Службы 112">✎</button>
            </div>
          </div>

          <div className={styles.incidentBody}>
            <section className={styles.callerColumn}>
              <div className={styles.addressPanel}>
                <strong>{selectedIncident.address}</strong>
                <span>{selectedIncident.latitude !== null && selectedIncident.longitude !== null
                  ? `Координаты: ${selectedIncident.latitude}, ${selectedIncident.longitude}`
                  : 'Описательный адрес не указан'}</span>
                <button type="button" disabled title="Открыть точку происшествия на карте">⌖</button>
              </div>
              <div className={styles.reportPanel}>
                <strong>{formatDateTime(selectedIncident.reported_at)} &nbsp; 0 УМЦ О.п.</strong>
                <p>{selectedIncident.description}</p>
                <span>Источник: {selectedIncident.source}</span>
              </div>
            </section>

            <section className={styles.classificationColumn}>
              <div className={styles.classificationTitle}>Происшествие {selectedIncident.incident_type}</div>
              <div className={styles.classificationLine}>
                <strong>{features.length ? features.join(' · ') : selectedIncident.description}</strong>
              </div>
              <div className={styles.classificationLine}>Класс: <strong>{selectedIncident.incident_type}</strong>;</div>
              <div className={styles.classificationLine}>[ВИС] Класс:</div>
            </section>
          </div>

          <div className={styles.serviceArea}>
            {serviceHistoryOpen && (
              <div className={styles.serviceHistory}>
                <button type="button" onClick={() => setServiceHistoryOpen(false)} aria-label="Закрыть историю">×</button>
                <strong>{selectedService}</strong>
                {isOwnServiceSelected ? (
                  <>
                    <div className={styles.currentDdsStatus}>
                      <span>Текущий статус</span>
                      <strong>{ddsStatusLabels[selectedIncident.dds_status]}</strong>
                    </div>
                    <div className={styles.historyList}>
                      {ownServiceHistory.map((entry) => (
                        <article key={entry.id} className={styles.historyEntry}>
                          <div>
                            <em>{historyStatusLabels[entry.status] || entry.status}</em>
                            <time>{formatDateTime(entry.created_at)}</time>
                          </div>
                          <small>{entry.actor_display_name}{entry.is_system ? ' · системное событие' : ''}</small>
                          {entry.comment && <p>{entry.comment}</p>}
                        </article>
                      ))}
                    </div>
                    {selectedIncident.available_actions.length ? (
                      <form className={styles.statusEditor} onSubmit={submitIncidentAction}>
                        <label>
                          Новый статус
                          <select value={selectedAction} onChange={(event) => setSelectedAction(event.target.value)}>
                            {selectedIncident.available_actions.map((action) => (
                              <option key={action} value={action}>{actionLabels[action]}</option>
                            ))}
                          </select>
                        </label>
                        <label>
                          Комментарий{commentRequiredActions.has(selectedAction) ? ' — обязателен' : ''}
                          <textarea
                            value={actionComment}
                            onChange={(event) => setActionComment(event.target.value)}
                            placeholder="Укажите факты, причину или результат реагирования"
                            rows="3"
                          />
                        </label>
                        <button
                          type="submit"
                          disabled={loading || (commentRequiredActions.has(selectedAction) && !actionComment.trim())}
                        >
                          Сохранить статус
                        </button>
                      </form>
                    ) : (
                      <p className={styles.statusLocked}>Изменение статусов закрыто. История доступна только для просмотра.</p>
                    )}
                    <div className={styles.responsePanel}>
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
                          <select
                            aria-label="Доступная группа реагирования"
                            value={selectedResponseUnitId}
                            onChange={(event) => setSelectedResponseUnitId(event.target.value)}
                          >
                            {availableResponseUnits.map((unit) => (
                              <option key={unit.id} value={unit.id}>{unit.name}</option>
                            ))}
                          </select>
                          <button type="submit" disabled={loading || !selectedResponseUnitId}>Назначить группу</button>
                        </form>
                      )}
                      {!canAssignResponse && <small>Назначение доступно после принятия карточки.</small>}
                      {canAssignResponse && !availableResponseUnits.length && !responseAssignments.length && (
                        <small>Для профиля ДДС пока нет доступных групп.</small>
                      )}
                    </div>
                  </>
                ) : (
                  <div className={styles.readOnlyServiceHistory}>
                    <div><span>система</span><b>›</b><time>{formatDateTime(selectedIncident.delivered_at)}</time><em>Добавлена</em></div>
                    <small>Статусы другой службы доступны только для просмотра.</small>
                  </div>
                )}
              </div>
            )}

            <div className={styles.servicesDock}>
              <div className={styles.servicesLabel}>Службы:</div>
              {(services.length ? services : ['Служба ДДС']).map((service, index) => (
                <button
                  className={`${styles.serviceTile} ${selectedService === service ? styles.serviceTileActive : ''}`}
                  key={service}
                  type="button"
                  onClick={() => selectService(service)}
                  title="Выбрать службу и показать историю статусов"
                >
                  <span className={styles.serviceChevron} aria-hidden="true" />
                  <strong>{compactServiceName(service)}</strong>
                  <small>{index === 0
                    ? `${formatTime(latestOwnStatus?.created_at)} ${historyStatusLabels[latestOwnStatus?.status] || 'Добавлена'}`
                    : `${formatTime(selectedIncident.delivered_at)} Добавлена`}</small>
                  {selectedService === service && index === 0 && <i title="Изменить статус и открыть историю">✎</i>}
                </button>
              ))}
              {['Доп. ЖКХ', 'ЦЭМП', 'ЦОДД', 'Мос.Без.'].map((service) => (
                <button className={`${styles.serviceTile} ${styles.serviceTileMuted}`} key={service} type="button" disabled>
                  <span className={styles.serviceChevron} aria-hidden="true" /><strong>{service}</strong><small>не оповещена</small>
                </button>
              ))}
              <button className={styles.dockControl} type="button" onClick={() => setServiceHistoryOpen((isOpen) => !isOpen)} title="Развернуть или свернуть историю выбранной службы">↕</button>
              <div className={styles.dockSpacer} />
              <button className={styles.dockControl} type="button" disabled title="Сообщения по карточке">▣</button>
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
                <button className={styles.expandSearchButton} type="button" onClick={() => setExpandedSearch((isOpen) => !isOpen)}>
                  расширенный по параметрам {expandedSearch ? '⌃' : '⌄'}
                </button>
                <button type="button" onClick={() => setFilters(emptyFilters)} disabled={!filtersActive}>сбросить</button>
              </div>
            </div>

            <div className={styles.clockPanel}>
              <div>
                <strong>{fullDateFormatter.format(now)}</strong>
                <label>
                  <select value={currentUser?.username || ''} onChange={selectUser} disabled={!users.length} aria-label="Текущий пользователь">
                    {!currentUser && <option value="">загрузка…</option>}
                    {users.map((user) => (
                      <option key={user.id} value={user.username}>
                        {user.full_name}
                      </option>
                    ))}
                  </select>
                </label>
                <button className={styles.sessionExit} type="button" onClick={logout}>выйти</button>
              </div>
              <time>{formatTime(now)}</time>
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
              <h2>Список происшествий <span>⌃</span></h2>
              <div><span>ⓘ уведомления</span><select disabled><option>выберите что показать</option></select></div>
            </div>

            <div className={styles.registryHeader} aria-hidden="true">
              <span>Связи</span><span>ЧС</span><span>Опер.</span><span>АРМ</span><span>Номер</span><span>Дата ↓</span><span>Время</span><span>Тип происшествия</span><span>Постр.</span><span>Адрес</span><span>Статус службы</span><span />
            </div>

            <div className={styles.registryRows}>
              {loading && !incidents.length ? (
                <div className={styles.registryEmpty}>Загрузка происшествий…</div>
              ) : visibleIncidents.length ? visibleIncidents.map((incident) => (
                <button
                  key={incident.id}
                  className={`${styles.registryRow} ${!incident.opened_at ? styles.registryRowNew : ''}`}
                  type="button"
                  onClick={() => openCard(incident)}
                >
                  <span className={styles.linkCell}><span className={styles.chevronDownIcon} aria-hidden="true" /></span>
                  <span><span className={styles.emergencyBookmark} aria-hidden="true" /></span>
                  <span className={`${styles.operatorCell} ${incident.opened_at ? styles.operatorCellZero : ''}`}>{incident.opened_at ? '0' : '!'}</span>
                  <span>{incident.claimant_workstation_number || '—'}</span>
                  <strong>{incident.incident_number}</strong>
                  <span>{formatDate(incident.reported_at)}</span>
                  <time>{formatTime(incident.reported_at)}</time>
                  <strong>{incident.incident_type}</strong>
                  <span>Нет</span>
                  <strong className={styles.registryAddress}>{incident.address}</strong>
                  <span className={styles.serviceState}>{incident.claimant_name ? `${incident.claimant_name} · АРМ ${incident.claimant_workstation_number} · ` : ''}{historyStatusLabels[incident.actions?.[incident.actions.length - 1]?.status] || lifecycleLabels[incident.lifecycle_state]}</span>
                  <span className={styles.fileIconCell}><span className={styles.fileTextIcon} aria-hidden="true" /></span>
                  <small><b>Описание:</b><time>{formatDateTime(incident.reported_at)}</time><span>УМЦ О.п.</span><strong>{incident.description}</strong></small>
                </button>
              )) : (
                <div className={styles.registryEmpty}>{filtersActive ? 'Происшествия не найдены' : 'Происшествий нет'}</div>
              )}
            </div>

            <footer className={styles.registryPager}>
              <span>Новые: {newCount}</span>
              <span>Страница: 1⌄</span>
              <span>Записей на странице: 10⌄</span>
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
