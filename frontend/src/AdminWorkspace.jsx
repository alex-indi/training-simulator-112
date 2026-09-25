import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import PropTypes from 'prop-types'

import styles from './AdminWorkspace.module.css'

const sections = [
  ['overview', 'Обзор'],
  ['users', 'Пользователи'],
  ['classifier', 'Классификатор'],
  ['services', 'Службы 112'],
  ['objects', 'Объекты Москвы'],
  ['types', 'Типы объектов'],
  ['imports', 'Импорт данных'],
  ['ai', 'AI'],
  ['scenarios', 'Сценарии'],
  ['audit', 'Аудит'],
  ['system', 'Система'],
]

const endpoints = {
  overview: '/api/admin/dashboard',
  users: '/api/admin/users',
  classifier: '/api/admin/classifier',
  services: '/api/admin/services',
  objects: '/api/admin/object-registry',
  types: '/api/admin/object-types',
  imports: '/api/admin/imports',
  ai: '/api/admin/ai',
  scenarios: '/api/admin/scenarios',
  audit: '/api/admin/audit',
  system: '/api/admin/system',
}

const roleLabels = { ADMIN: 'Администратор', INSTRUCTOR: 'Преподаватель', TRAINEE: 'Диспетчер ДДС' }
const aiHealthLabels = {
  AVAILABLE: 'подключение установлено',
  UNAVAILABLE: 'провайдер недоступен',
  MISCONFIGURED: 'настройки неполные',
}
const userGroups = [
  ['ADMIN', 'Администраторы'],
  ['INSTRUCTOR', 'Преподаватели'],
  ['TRAINEE', 'Диспетчеры ДДС'],
]

function formatDateTime(value) {
  return value ? new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value)) : '—'
}

function Empty({ children = 'Данных пока нет' }) {
  return <div className={styles.empty}>{children}</div>
}

Empty.propTypes = { children: PropTypes.node }

function AdminWorkspace({ user, users, selectUser, requestJson, onLogout, onCurrentUserUpdated }) {
  const [section, setSection] = useState('overview')
  const [data, setData] = useState(null)
  const [quality, setQuality] = useState([])
  const [usage, setUsage] = useState([])
  const [aiHealth, setAiHealth] = useState(null)
  const [aiDraft, setAiDraft] = useState({ provider: 'OPENAI', model: '', base_url: 'https://api.openai.com/v1', enabled: false, timeout_seconds: 30 })
  const [aiApiKey, setAiApiKey] = useState('')
  const [aiModels, setAiModels] = useState([])
  const [aiModelsLoading, setAiModelsLoading] = useState(false)
  const [aiModelsError, setAiModelsError] = useState('')
  const [aiModelsRefresh, setAiModelsRefresh] = useState(0)
  const [traineeGroups, setTraineeGroups] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState({})
  const [selectedObject, setSelectedObject] = useState(null)
  const [activeUserRole, setActiveUserRole] = useState('ADMIN')
  const [userForm, setUserForm] = useState({ username: '', full_name: '', password: '', role: 'ADMIN', group_id: null })
  const [userModal, setUserModal] = useState(null)
  const [groupDraft, setGroupDraft] = useState({ name: '', description: '' })
  const [groupModal, setGroupModal] = useState(null)
  const [deleteModal, setDeleteModal] = useState(null)
  const [typeDraft, setTypeDraft] = useState({ code: '', name: '', description: '', parent_id: '' })
  const loadRequestId = useRef(0)
  const aiModelsRequestId = useRef(0)
  const username = user.username

  const load = useCallback(async () => {
    const requestId = ++loadRequestId.current
    setLoading(true)
    setError('')
    setNotice('')
    try {
      const params = new URLSearchParams()
      if (search && ['classifier', 'services', 'objects'].includes(section)) params.set('search', search)
      Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value) })
      const suffix = params.size ? `?${params}` : ''
      const payload = await requestJson(`${endpoints[section]}${suffix}`, username)
      if (requestId !== loadRequestId.current) return
      setData(payload)
      if (section === 'users') {
        const nextGroups = await requestJson('/api/admin/user-groups', username)
        if (requestId !== loadRequestId.current) return
        setTraineeGroups(nextGroups)
      }
      if (section === 'imports') {
        const nextQuality = await requestJson('/api/admin/data-quality', username)
        if (requestId !== loadRequestId.current) return
        setQuality(nextQuality)
      }
      if (section === 'ai') {
        setAiDraft({
          provider: payload.provider.toUpperCase(),
          model: payload.model,
          base_url: payload.base_url,
          enabled: payload.enabled,
          timeout_seconds: payload.timeout_seconds,
        })
        const nextUsage = await requestJson('/api/admin/ai/usage', username)
        if (requestId !== loadRequestId.current) return
        setUsage(nextUsage)
      }
    } catch (cause) {
      if (requestId !== loadRequestId.current) return
      setError(cause.message)
      setData(null)
    } finally {
      if (requestId === loadRequestId.current) setLoading(false)
    }
  }, [filters, requestJson, search, section, username])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (section !== 'ai' || !data) return undefined
    const requestId = ++aiModelsRequestId.current
    if (aiDraft.provider === 'TEMPLATE') {
      setAiModels([])
      setAiModelsError('')
      setAiModelsLoading(false)
      return undefined
    }
    try { new URL(aiDraft.base_url) } catch {
      setAiModels([])
      setAiModelsError('Укажите корректный Base URL')
      setAiModelsLoading(false)
      return undefined
    }
    const timer = window.setTimeout(async () => {
      setAiModelsLoading(true)
      setAiModelsError('')
      try {
        const result = await requestJson('/api/admin/ai/models', username, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider: aiDraft.provider, base_url: aiDraft.base_url, ...(aiApiKey ? { api_key: aiApiKey } : {}) }),
        })
        if (requestId === aiModelsRequestId.current) setAiModels(result.models)
      } catch (cause) {
        if (requestId === aiModelsRequestId.current) {
          setAiModels([])
          setAiModelsError(cause.message)
        }
      } finally {
        if (requestId === aiModelsRequestId.current) setAiModelsLoading(false)
      }
    }, 350)
    return () => window.clearTimeout(timer)
  }, [aiApiKey, aiDraft.base_url, aiDraft.provider, aiModelsRefresh, data, requestJson, section, username])

  const mutate = async (path, options, message) => {
    setLoading(true)
    setError('')
    try {
      await requestJson(path, username, options)
      await load()
      setNotice(message)
      return true
    } catch (cause) {
      setError(cause.message)
      return false
    } finally {
      setLoading(false)
    }
  }

  const submitUser = async (event) => {
    event.preventDefault()
    if (userModal.mode === 'edit') {
      const changes = { ...userForm }
      if (!changes.password) delete changes.password
      if (await patchUser(userModal.item, changes)) setUserModal(null)
      return
    }
    const created = await mutate('/api/admin/users', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(userForm),
    }, 'Пользователь создан и действие записано в аудит.')
    if (created) setUserModal(null)
  }

  const openCreateUser = (role, groupId = null) => {
    setUserForm({ username: '', full_name: '', password: '', role, group_id: groupId })
    setUserModal({ mode: 'create' })
  }

  const openEditUser = (item) => {
    setUserForm({
      username: item.username,
      full_name: item.full_name,
      password: '',
      role: item.role,
      group_id: item.group_id,
    })
    setUserModal({ mode: 'edit', item })
  }

  const openCreateGroup = () => {
    setGroupDraft({ name: '', description: '' })
    setGroupModal({ mode: 'create' })
  }

  const openEditGroup = (group) => {
    setGroupDraft({ name: group.name, description: group.description || '' })
    setGroupModal({ mode: 'edit', group })
  }

  const submitGroup = async (event) => {
    event.preventDefault()
    const editing = groupModal.mode === 'edit'
    const saved = await mutate(editing ? `/api/admin/user-groups/${groupModal.group.id}` : '/api/admin/user-groups', {
      method: editing ? 'PATCH' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(groupDraft),
    }, editing ? 'Название и описание группы обновлены.' : 'Учебная группа создана.')
    if (saved) setGroupModal(null)
  }

  const confirmDelete = async () => {
    const isGroup = deleteModal.kind === 'group'
    const deleted = await mutate(
      isGroup ? `/api/admin/user-groups/${deleteModal.item.id}` : `/api/admin/users/${deleteModal.item.id}`,
      { method: 'DELETE' },
      isGroup
        ? 'Группа удалена. Диспетчеры перенесены в «Без группы».'
        : 'Пользователь удалён.',
    )
    if (deleted) setDeleteModal(null)
  }

  const patchUser = async (item, changes) => {
    setLoading(true)
    setError('')
    try {
      const updated = await requestJson(`/api/admin/users/${item.id}`, username, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(changes),
      })
      if (item.id === user.id) {
        setData((current) => Array.isArray(current)
          ? current.map((entry) => entry.id === updated.id ? updated : entry)
          : current)
        onCurrentUserUpdated(updated)
      } else {
        await load()
      }
      setNotice('Пользователь обновлён.')
      return true
    } catch (cause) {
      setError(cause.message)
      return false
    } finally {
      setLoading(false)
    }
  }

  const createType = async (event) => {
    event.preventDefault()
    const payload = { ...typeDraft, parent_id: typeDraft.parent_id ? Number(typeDraft.parent_id) : null }
    await mutate('/api/admin/object-types', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    }, 'Тип объекта создан.')
    setTypeDraft({ code: '', name: '', description: '', parent_id: '' })
  }

  const updateAI = async (event) => {
    event.preventDefault()
    setAiHealth(null)
    const saved = await mutate('/api/admin/ai', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...aiDraft, timeout_seconds: Number(aiDraft.timeout_seconds), ...(aiApiKey ? { api_key: aiApiKey } : {}) }),
    }, 'Конфигурация AI сохранена; значение ключа не возвращается через API.')
    if (saved) setAiApiKey('')
  }

  const filteredRows = useMemo(() => Array.isArray(data) ? data : [], [data])
  const groupedUsers = useMemo(
    () => userGroups.map(([role, label]) => ({
      role,
      label,
      users: filteredRows.filter((item) => item.role === role),
    })),
    [filteredRows],
  )
  const traineeBuckets = useMemo(() => [
    ...traineeGroups.map((group) => ({
      ...group,
      users: filteredRows.filter((item) => item.role === 'TRAINEE' && item.group_id === group.id),
    })),
    {
      id: null,
      name: 'Без группы',
      description: 'Диспетчеры, которым учебная группа ещё не назначена',
      users: filteredRows.filter((item) => item.role === 'TRAINEE' && item.group_id === null),
    },
  ], [filteredRows, traineeGroups])

  const updateFilter = (event) => setFilters({ ...filters, [event.target.name]: event.target.value })

  const renderFilters = () => {
    if (section === 'classifier') return <><input name="incident_group" placeholder="Группа происшествий" value={filters.incident_group || ''} onChange={updateFilter} /><input name="service" placeholder="Связанная служба" value={filters.service || ''} onChange={updateFilter} /></>
    if (section === 'services') return <input name="level" placeholder="Уровень службы" value={filters.level || ''} onChange={updateFilter} />
    if (section === 'objects') return <><input name="object_type_id" type="number" placeholder="ObjectType ID" value={filters.object_type_id || ''} onChange={updateFilter} /><input name="district" placeholder="Район" value={filters.district || ''} onChange={updateFilter} /><input name="administrative_area" placeholder="Округ" value={filters.administrative_area || ''} onChange={updateFilter} /><input name="source" placeholder="Источник" value={filters.source || ''} onChange={updateFilter} /><input name="tag" placeholder="Тег" value={filters.tag || ''} onChange={updateFilter} /></>
    return null
  }

  const renderOverview = () => data && (
    <>
      <div className={styles.cards}>
        <article><span>Пользователи</span><strong>{data.users}</strong><small>активных: {data.active_users}</small></article>
        <article><span>Сценарии READY</span><strong>{data.ready_scenarios}</strong></article>
        <article><span>Классификатор</span><strong>{data.classifier_rules}</strong><small>правил SRC-006</small></article>
        <article><span>Службы</span><strong>{data.services}</strong></article>
        <article><span>Объекты Москвы</span><strong>{data.objects}</strong></article>
        <article className={data.data_quality_open ? styles.warningCard : ''}><span>Требуют проверки</span><strong>{data.data_quality_open}</strong></article>
      </div>
      <div className={styles.statusGrid}>
        <article><h3>AI Renderer</h3><b>{data.ai.enabled ? '● включён' : '○ выключен'}</b><p>{data.ai.provider} · {data.ai.model || 'модель не выбрана'}</p><small>API key: {data.ai.api_key_configured ? 'configured' : 'not configured'}</small></article>
        <article><h3>Последний импорт</h3>{data.last_import ? <><b>{data.last_import.source} · {data.last_import.status}</b><p>{formatDateTime(data.last_import.finished_at || data.last_import.started_at)}</p></> : <p>Импорты ещё не запускались</p>}</article>
      </div>
    </>
  )

  const renderUserTable = (rows) => !rows.length ? <div className={styles.groupEmpty}>Пользователей в группе нет</div> : <div className={styles.table}>
    <div className={styles.tableHead}><span>ФИО</span><span>Логин</span><span>Роль / группа</span><span>Статус</span><span>Последний вход / пароль</span><span>Действия</span></div>
    {rows.map((item) => <div className={styles.tableRow} key={item.id}><strong>{item.full_name}</strong><code>{item.username}</code><span>{roleLabels[item.role]}</span><span className={item.is_active ? styles.ok : styles.muted}>{item.is_active ? 'Активен' : 'Отключён'}</span><span>{formatDateTime(item.last_login_at)}</span><div className={styles.rowActions}><button onClick={() => openEditUser(item)}>Изменить</button><button onClick={() => patchUser(item, { is_active: !item.is_active })}>{item.is_active ? 'Деактивировать' : 'Активировать'}</button><button className={styles.dangerButton} disabled={item.id === user.id} title={item.id === user.id ? 'Нельзя удалить текущую учётную запись' : ''} onClick={() => setDeleteModal({ kind: 'user', item })}>Удалить</button></div></div>)}
  </div>

  const renderUsers = () => {
    const currentGroup = groupedUsers.find((group) => group.role === activeUserRole)
    return <div className={styles.userGroups}>
      <div className={styles.userToolbar}>
        <div className={styles.roleTabs} role="tablist" aria-label="Категории пользователей">
          {groupedUsers.map((group) => <button type="button" role="tab" aria-selected={activeUserRole === group.role} className={activeUserRole === group.role ? styles.roleTabActive : styles.roleTab} key={group.role} onClick={() => setActiveUserRole(group.role)}><span>{group.label}</span><b>{group.users.length}</b></button>)}
        </div>
        <div className={styles.toolbarActions}>
          {activeUserRole === 'TRAINEE' && <button type="button" onClick={openCreateGroup}>Новая группа</button>}
          <button type="button" className={styles.primaryButton} onClick={() => openCreateUser(activeUserRole)}>Добавить {activeUserRole === 'ADMIN' ? 'администратора' : activeUserRole === 'INSTRUCTOR' ? 'преподавателя' : 'диспетчера'}</button>
        </div>
      </div>
      {activeUserRole !== 'TRAINEE' ? (
        <section className={styles.userGroup}><header><div><h3>{currentGroup.label}</h3><p>Управление учётными записями и доступом</p></div></header>{renderUserTable(currentGroup.users)}</section>
      ) : (
        <section className={styles.userGroup}>
          <div className={styles.groupIntro}><div><h3>Учебные группы диспетчеров</h3><p>Создавайте группы, назначайте в них обучаемых и меняйте названия в любое время.</p></div></div>
          <div className={styles.traineeGroups}>{traineeBuckets.map((group) => <article className={styles.traineeGroup} key={`TRAINEE:${group.id ?? 'none'}`}>
            <header><div><h4>{group.name}</h4><p>{group.description}</p></div><span>{group.users.length}</span><div className={styles.groupActions}>{group.id !== null && <><button type="button" onClick={() => openEditGroup(group)}>Изменить группу</button><button type="button" className={styles.dangerButton} onClick={() => setDeleteModal({ kind: 'group', item: group })}>Удалить группу</button></>}<button type="button" className={styles.primaryButton} onClick={() => openCreateUser('TRAINEE', group.id)}>Добавить диспетчера</button></div></header>
            {renderUserTable(group.users)}
          </article>)}</div>
        </section>
      )}
    </div>
  }

  const renderUserModal = () => userModal && <div className={styles.modalBackdrop} role="presentation">
    <section className={styles.modal} role="dialog" aria-modal="true" aria-labelledby="user-modal-title">
      <header className={styles.modalHeader}><div><small>{userModal.mode === 'edit' ? 'Редактирование пользователя' : 'Новый пользователь'}</small><h2 id="user-modal-title">{userModal.mode === 'edit' ? userModal.item.full_name : `Добавить: ${roleLabels[userForm.role]}`}</h2></div><button type="button" aria-label="Закрыть" onClick={() => setUserModal(null)}>×</button></header>
      <form className={styles.modalForm} onSubmit={submitUser}>
        <label><span>ФИО</span><input required autoFocus placeholder="Например, Иванов Иван Иванович" value={userForm.full_name} onChange={(event) => setUserForm({ ...userForm, full_name: event.target.value })} /></label>
        <label><span>Логин</span><input required autoComplete="off" placeholder="Логин для входа" value={userForm.username} onChange={(event) => setUserForm({ ...userForm, username: event.target.value })} /></label>
        <label><span>{userModal.mode === 'edit' ? 'Новый пароль' : 'Пароль'}</span><input required={userModal.mode === 'create'} minLength="8" maxLength="128" type="password" autoComplete="new-password" placeholder={userModal.mode === 'edit' ? 'Оставьте пустым, чтобы не менять' : 'Минимум 8 символов'} value={userForm.password} onChange={(event) => setUserForm({ ...userForm, password: event.target.value })} /></label>
        {userModal.mode === 'edit' ? <label><span>Роль</span><select value={userForm.role} onChange={(event) => setUserForm({ ...userForm, role: event.target.value, group_id: event.target.value === 'TRAINEE' ? userForm.group_id : null })}>{Object.entries(roleLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label> : <div className={styles.readonlyField}><span>Тип учётной записи</span><strong>{roleLabels[userForm.role]}</strong></div>}
        {userForm.role === 'TRAINEE' && <label><span>Учебная группа</span><select value={userForm.group_id ?? ''} onChange={(event) => setUserForm({ ...userForm, group_id: event.target.value ? Number(event.target.value) : null })}><option value="">Без группы</option>{traineeGroups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select></label>}
        <footer className={styles.modalActions}><button type="button" onClick={() => setUserModal(null)}>Отмена</button><button className={styles.primaryButton} disabled={loading}>{userModal.mode === 'edit' ? 'Сохранить изменения' : 'Создать пользователя'}</button></footer>
      </form>
    </section>
  </div>

  const renderGroupModal = () => groupModal && <div className={styles.modalBackdrop} role="presentation">
    <section className={styles.modal} role="dialog" aria-modal="true" aria-labelledby="group-modal-title">
      <header className={styles.modalHeader}><div><small>Учебные группы</small><h2 id="group-modal-title">{groupModal.mode === 'edit' ? 'Изменить группу' : 'Создать группу'}</h2></div><button type="button" aria-label="Закрыть" onClick={() => setGroupModal(null)}>×</button></header>
      <form className={styles.modalForm} onSubmit={submitGroup}>
        <label><span>Название группы</span><input required autoFocus minLength="2" maxLength="160" placeholder="Например, ДДС — осень 2026" value={groupDraft.name} onChange={(event) => setGroupDraft({ ...groupDraft, name: event.target.value })} /></label>
        <label><span>Описание</span><textarea maxLength="1000" rows="4" placeholder="Курс, поток или другая полезная информация" value={groupDraft.description} onChange={(event) => setGroupDraft({ ...groupDraft, description: event.target.value })} /></label>
        <footer className={styles.modalActions}><button type="button" onClick={() => setGroupModal(null)}>Отмена</button><button className={styles.primaryButton} disabled={loading}>{groupModal.mode === 'edit' ? 'Сохранить изменения' : 'Создать группу'}</button></footer>
      </form>
    </section>
  </div>

  const renderDeleteModal = () => deleteModal && <div className={styles.modalBackdrop} role="presentation">
    <section className={styles.confirmModal} role="alertdialog" aria-modal="true" aria-labelledby="delete-modal-title">
      <header className={styles.modalHeader}><div><small>Подтверждение удаления</small><h2 id="delete-modal-title">Удалить {deleteModal.kind === 'group' ? `группу «${deleteModal.item.name}»` : `пользователя «${deleteModal.item.full_name}»`}?</h2></div><button type="button" aria-label="Закрыть" onClick={() => setDeleteModal(null)}>×</button></header>
      <div className={styles.confirmContent}><p>{deleteModal.kind === 'group' ? 'Пользователи сохранятся и автоматически перейдут в раздел «Без группы».' : 'Учётная запись будет удалена без возможности восстановления. Если с ней связана учебная история, система предложит деактивацию.'}</p><footer className={styles.modalActions}><button type="button" onClick={() => setDeleteModal(null)}>Отмена</button><button type="button" className={styles.dangerPrimaryButton} disabled={loading} onClick={confirmDelete}>Удалить</button></footer></div>
    </section>
  </div>

  const renderClassifier = () => !filteredRows.length ? <Empty>Записи SRC-006 не импортированы</Empty> : <div className={styles.table}><div className={styles.tableHead}><span>Группа</span><span>Признаки</span><span>Тип</span><span>Код</span><span>Службы</span></div>{filteredRows.map((item) => <div className={styles.tableRow} key={item.id}><strong>{item.incident_group}</strong><span>{[item.feature_1, item.feature_2, item.feature_3].filter(Boolean).join(' → ') || '—'}</span><span>{item.incident_type}</span><code>{item.source_code}</code><span>{item.related_services.join(', ') || '—'}</span></div>)}</div>

  const renderServices = () => !filteredRows.length ? <Empty>Каталог служб ещё не импортирован. Создание служб вручную запрещено.</Empty> : <div className={styles.table}><div className={styles.tableHead}><span>Официальное название</span><span>Тип</span><span>Уровень</span><span>Организация</span><span>Источник</span><span>Статус</span></div>{filteredRows.map((item) => <div className={styles.tableRow} key={item.id}><strong>{item.official_name}</strong><span>{item.service_type}</span><span>{item.level || '—'}</span><span>{item.organization || '—'}</span><code>{item.source}</code><span>{item.data_status}</span></div>)}</div>

  const renderObjects = () => (
    <div className={styles.split}>
      {!filteredRows.length ? <Empty>Object Registry ещё не импортирован</Empty> : <div className={styles.objectList}>{filteredRows.map((item) => <button key={item.id} onClick={() => setSelectedObject(item)}><strong>{item.official_name}</strong><span>{item.address}</span><small>{item.district || 'район не указан'} · {item.dataset_id}</small></button>)}</div>}
      <aside className={styles.details}>{selectedObject ? <><h3>{selectedObject.official_name}</h3><dl><dt>Адрес</dt><dd>{selectedObject.address}</dd><dt>Район / округ</dt><dd>{selectedObject.district || '—'} / {selectedObject.administrative_area || '—'}</dd><dt>Координаты</dt><dd>{selectedObject.latitude ?? '—'}, {selectedObject.longitude ?? '—'}</dd><dt>Источник</dt><dd>{selectedObject.source}</dd><dt>Dataset / external ID</dt><dd>{selectedObject.dataset_id} / {selectedObject.external_id}</dd><dt>Теги</dt><dd>{selectedObject.tags.join(', ') || '—'}</dd><dt>Атрибуты</dt><dd><pre>{JSON.stringify(selectedObject.attributes, null, 2)}</pre></dd></dl></> : <p>Выберите объект для просмотра полной карточки.</p>}</aside>
    </div>
  )

  const renderTypes = () => (
    <>
      <form className={styles.inlineForm} onSubmit={createType}>
        <input required pattern="[A-Z0-9_]+" placeholder="CODE" value={typeDraft.code} onChange={(event) => setTypeDraft({ ...typeDraft, code: event.target.value.toUpperCase() })} />
        <input required placeholder="Название" value={typeDraft.name} onChange={(event) => setTypeDraft({ ...typeDraft, name: event.target.value })} />
        <input placeholder="Описание" value={typeDraft.description} onChange={(event) => setTypeDraft({ ...typeDraft, description: event.target.value })} />
        <select value={typeDraft.parent_id} onChange={(event) => setTypeDraft({ ...typeDraft, parent_id: event.target.value })}><option value="">Без родителя</option>{filteredRows.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{item.code}</option>)}</select>
        <button disabled={loading}>Создать тип</button>
      </form>
      {!filteredRows.length ? <Empty>Типы объектов ещё не настроены</Empty> : <div className={styles.typeTree}>{filteredRows.map((item) => <article key={item.id} className={!item.is_active ? styles.inactive : ''}><code>{item.code}</code><strong>{item.name}</strong><span>{item.parent_id ? `parent #${item.parent_id}` : 'корневой тип'}</span><p>{item.description || 'Без описания'}</p><button onClick={() => mutate(`/api/admin/object-types/${item.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_active: !item.is_active }) }, 'Тип объекта обновлён.')}>{item.is_active ? 'Деактивировать' : 'Активировать'}</button></article>)}</div>}
    </>
  )

  const renderImports = () => (
    <>
      <div className={styles.importSources}>{['src-006', 'services-112', 'object-registry'].map((source) => <article key={source}><strong>{source}</strong><p>Идемпотентный source adapter</p><button disabled={loading} onClick={() => mutate(`/api/admin/imports/${source}/run`, { method: 'POST' }, 'Импорт запущен.')}>Обновить данные</button></article>)}</div>
      <h3>История импорта</h3>
      {!filteredRows.length ? <Empty>История импорта пуста</Empty> : <div className={styles.compactList}>{filteredRows.map((item) => <article key={item.id}><b>{item.source}</b><span>{item.status}</span><span>{formatDateTime(item.started_at)}</span><small>получено {item.received} · создано {item.created} · обновлено {item.updated} · review {item.review} · ошибок {item.errors}</small></article>)}</div>}
      <h3>Требуют проверки</h3>
      {!quality.length ? <Empty>Открытых замечаний к данным нет</Empty> : <div className={styles.compactList}>{quality.map((item) => <article key={item.id}><b>{item.kind}</b><span>{item.entity_type} {item.entity_id || ''}</span><p>{item.reason}</p></article>)}</div>}
    </>
  )

  const renderAI = () => data && (
    <>
      <form className={styles.settingsForm} onSubmit={updateAI}>
        <label>Provider<select name="provider" value={aiDraft.provider} onChange={(event) => {
          const provider = event.target.value
          setAiDraft({ ...aiDraft, provider, model: '', base_url: provider === 'OPENAI' ? 'https://api.openai.com/v1' : aiDraft.base_url })
        }}><option value="OPENAI">OpenAI</option><option value="OPENAI_COMPATIBLE">OpenAI-compatible</option><option value="TEMPLATE">Шаблонный режим</option></select></label>
        <div className={styles.modelField}><span>Model</span><div className={styles.modelSelector}><select name="model" required={aiDraft.enabled && aiDraft.provider !== 'TEMPLATE'} disabled={aiDraft.provider === 'TEMPLATE'} value={aiDraft.model} onChange={(event) => setAiDraft({ ...aiDraft, model: event.target.value })}><option value="">{aiModelsLoading ? 'Загрузка моделей…' : aiDraft.provider === 'TEMPLATE' ? 'Не используется' : 'Выберите модель'}</option>{[...new Set([aiDraft.model, ...aiModels].filter(Boolean))].map((model) => <option key={model} value={model}>{model}</option>)}</select><button type="button" disabled={loading || aiModelsLoading || aiDraft.provider === 'TEMPLATE'} onClick={() => setAiModelsRefresh((value) => value + 1)}>Обновить список</button></div>{aiModelsError ? <small className={styles.fieldError}>{aiModelsError}</small> : !aiModelsLoading && aiDraft.provider !== 'TEMPLATE' && <small>Доступно моделей: {aiModels.length}</small>}</div>
        <label>Base URL<input name="base_url" type="url" disabled={aiDraft.provider === 'OPENAI'} value={aiDraft.base_url} onChange={(event) => setAiDraft({ ...aiDraft, base_url: event.target.value })} /></label>
        <label>API key<input name="api_key" type="password" autoComplete="new-password" placeholder={data.api_key_configured ? 'Ключ сохранён — введите новый для замены' : 'Введите ключ провайдера'} value={aiApiKey} onChange={(event) => setAiApiKey(event.target.value)} /></label>
        <label>Timeout, сек.<input name="timeout_seconds" type="number" min="1" max="300" value={aiDraft.timeout_seconds} onChange={(event) => setAiDraft({ ...aiDraft, timeout_seconds: event.target.value })} /></label>
        <label className={styles.checkbox}><input name="enabled" type="checkbox" checked={aiDraft.enabled} onChange={(event) => setAiDraft({ ...aiDraft, enabled: event.target.checked })} /> Активировать модель</label>
        <div className={styles.secretState}>API key: <b>{data.api_key_configured ? '● configured' : '○ not configured'}</b>. Значение ключа никогда не возвращается.</div>
        <button disabled={loading}>Применить</button>
        <button disabled={loading} type="button" onClick={async () => {
          setLoading(true); setError(''); setAiHealth(null)
          try { setAiHealth(await requestJson('/api/admin/ai/health', username, { method: 'POST' })) }
          catch (cause) { setError(cause.message) }
          finally { setLoading(false) }
        }}>Проверить подключение</button>
      </form>
      {aiHealth && <p role="status">Провайдер: {aiHealth.provider} · модель: {aiHealth.model || '—'} · состояние: {aiHealthLabels[aiHealth.status] || aiHealth.status}{aiHealth.available && !aiHealth.renderer_enabled ? ' · Модель не активирована' : ''}</p>}
      <h3>Usage за 31 день</h3>{!usage.length ? <Empty>Статистика usage не поступала</Empty> : <div className={styles.compactList}>{usage.map((item) => <article key={item.day}><b>{item.day}</b><span>запросов {item.requests}</span><small>input {item.input_tokens} · output {item.output_tokens} · fallback {item.fallbacks} · ошибок {item.errors}</small></article>)}</div>}
    </>
  )

  const renderScenarios = () => !filteredRows.length ? <Empty>Сценарии отсутствуют</Empty> : <div className={styles.compactList}>{filteredRows.map((item) => <article key={item.id}><b>{item.title}</b><span>{item.author}</span><span>{item.status}</span><small>{item.incident_type || 'тип не указан'} · {item.difficulty || 'сложность не указана'} · {formatDateTime(item.updated_at)}</small><button onClick={() => mutate(`/api/admin/scenarios/${item.id}/${item.archived ? 'restore' : 'archive'}`, { method: 'POST' }, 'Состояние сценария изменено.')}>{item.archived ? 'Восстановить' : 'Архивировать'}</button></article>)}</div>

  const renderAudit = () => !filteredRows.length ? <Empty>Административных действий ещё нет</Empty> : <div className={styles.compactList}>{filteredRows.map((item) => <article key={item.id}><time>{formatDateTime(item.created_at)}</time><b>{item.action}</b><span>admin #{item.admin_id} · {item.entity_type} {item.entity_id || ''}</span><details><summary>Изменения</summary><pre>{JSON.stringify({ before: item.before, after: item.after }, null, 2)}</pre></details></article>)}</div>

  const renderSystem = () => data && <div className={styles.systemGrid}><article><h3>Состояние</h3>{Object.entries(data.services).map(([name, value]) => <p key={name}><span>{name}</span><b className={value === 'OK' ? styles.ok : styles.muted}>● {value}</b></p>)}</article><article><h3>Версия приложения</h3><dl><dt>Version</dt><dd>{data.version}</dd><dt>Git commit</dt><dd>{data.git_commit}</dd><dt>DB revision</dt><dd>{data.db_revision}</dd><dt>Environment</dt><dd>{data.environment}</dd><dt>Server time</dt><dd>{formatDateTime(data.server_time)}</dd></dl></article></div>

  const content = { overview: renderOverview, users: renderUsers, classifier: renderClassifier, services: renderServices, objects: renderObjects, types: renderTypes, imports: renderImports, ai: renderAI, scenarios: renderScenarios, audit: renderAudit, system: renderSystem }[section]
  const title = sections.find(([key]) => key === section)?.[1]

  return (
    <main className={styles.shell}>
      <aside className={styles.sidebar}>
        <header><span>112</span><div><small>Учебный тренажёр</small><strong>Администрирование</strong></div></header>
        <nav>{sections.map(([key, label]) => <button className={section === key ? styles.active : ''} key={key} onClick={() => { loadRequestId.current += 1; setData(null); setQuality([]); setUsage([]); setSection(key); setSearch(''); setFilters({}); setSelectedObject(null) }}>{label}</button>)}</nav>
        <footer><select value={user.username} onChange={selectUser}>{users.map((item) => <option key={item.id} value={item.username}>{item.full_name}</option>)}</select><small>{roleLabels[user.role]}</small><button type="button" onClick={onLogout}>Выйти</button></footer>
      </aside>
      <section className={styles.workspace}>
        <header className={styles.topbar}><div><small>Системное управление</small><h1>{title}</h1></div>{['classifier', 'services', 'objects'].includes(section) && <form onSubmit={(event) => { event.preventDefault(); load() }}><input aria-label="Поиск" placeholder="Поиск…" value={search} onChange={(event) => setSearch(event.target.value)} />{renderFilters()}<button>Найти</button></form>}<button onClick={load}>Обновить</button></header>
        {error && <div className={styles.error} role="alert">{error}</div>}
        {notice && <div className={styles.notice}>{notice}</div>}
        <div className={styles.content} aria-busy={loading}>{loading && data === null ? <div className={styles.loading}>Загрузка…</div> : content()}</div>
      </section>
      {renderUserModal()}
      {renderGroupModal()}
      {renderDeleteModal()}
    </main>
  )
}

AdminWorkspace.propTypes = {
  user: PropTypes.object.isRequired,
  users: PropTypes.array.isRequired,
  selectUser: PropTypes.func.isRequired,
  requestJson: PropTypes.func.isRequired,
  onLogout: PropTypes.func.isRequired,
  onCurrentUserUpdated: PropTypes.func.isRequired,
}

export default AdminWorkspace
