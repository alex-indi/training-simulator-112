import { useCallback, useEffect, useMemo, useState } from 'react'
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

function formatDateTime(value) {
  return value ? new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value)) : '—'
}

function Empty({ children = 'Данных пока нет' }) {
  return <div className={styles.empty}>{children}</div>
}

Empty.propTypes = { children: PropTypes.node }

function AdminWorkspace({ user, users, selectUser, requestJson, onLogout }) {
  const [section, setSection] = useState('overview')
  const [data, setData] = useState(null)
  const [quality, setQuality] = useState([])
  const [usage, setUsage] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState({})
  const [selectedObject, setSelectedObject] = useState(null)
  const [userDraft, setUserDraft] = useState({ username: '', full_name: '', role: 'TRAINEE' })
  const [typeDraft, setTypeDraft] = useState({ code: '', name: '', description: '', parent_id: '' })
  const username = user.username

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    setNotice('')
    try {
      const params = new URLSearchParams()
      if (search && ['classifier', 'services', 'objects'].includes(section)) params.set('search', search)
      Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value) })
      const suffix = params.size ? `?${params}` : ''
      const payload = await requestJson(`${endpoints[section]}${suffix}`, username)
      setData(payload)
      if (section === 'imports') {
        setQuality(await requestJson('/api/admin/data-quality', username))
      }
      if (section === 'ai') {
        setUsage(await requestJson('/api/admin/ai/usage', username))
      }
    } catch (cause) {
      setError(cause.message)
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [filters, requestJson, search, section, username])

  useEffect(() => { load() }, [load])

  const mutate = async (path, options, message) => {
    setLoading(true)
    setError('')
    try {
      await requestJson(path, username, options)
      await load()
      setNotice(message)
    } catch (cause) {
      setError(cause.message)
    } finally {
      setLoading(false)
    }
  }

  const createUser = async (event) => {
    event.preventDefault()
    await mutate('/api/admin/users', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(userDraft),
    }, 'Пользователь создан и действие записано в аудит.')
    setUserDraft({ username: '', full_name: '', role: 'TRAINEE' })
  }

  const patchUser = (item, changes) => mutate(`/api/admin/users/${item.id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes),
  }, 'Пользователь обновлён.')

  const createType = async (event) => {
    event.preventDefault()
    const payload = { ...typeDraft, parent_id: typeDraft.parent_id ? Number(typeDraft.parent_id) : null }
    await mutate('/api/admin/object-types', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    }, 'Тип объекта создан.')
    setTypeDraft({ code: '', name: '', description: '', parent_id: '' })
  }

  const updateAI = (event) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    return mutate('/api/admin/ai', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: form.get('provider'), model: form.get('model'), base_url: form.get('base_url'),
        enabled: form.get('enabled') === 'on', timeout_seconds: Number(form.get('timeout_seconds')),
      }),
    }, 'Конфигурация AI сохранена; секрет не передавался через API.')
  }

  const filteredRows = useMemo(() => Array.isArray(data) ? data : [], [data])

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

  const renderUsers = () => (
    <>
      <form className={styles.inlineForm} onSubmit={createUser}>
        <input required placeholder="Логин" value={userDraft.username} onChange={(event) => setUserDraft({ ...userDraft, username: event.target.value })} />
        <input required placeholder="ФИО" value={userDraft.full_name} onChange={(event) => setUserDraft({ ...userDraft, full_name: event.target.value })} />
        <select value={userDraft.role} onChange={(event) => setUserDraft({ ...userDraft, role: event.target.value })}>{Object.keys(roleLabels).map((role) => <option key={role}>{role}</option>)}</select>
        <button disabled={loading}>Создать пользователя</button>
      </form>
      {!filteredRows.length ? <Empty /> : <div className={styles.table}><div className={styles.tableHead}><span>ФИО</span><span>Логин</span><span>Роль</span><span>Статус</span><span>Последний вход</span><span>Действия</span></div>{filteredRows.map((item) => <div className={styles.tableRow} key={item.id}><strong>{item.full_name}</strong><code>{item.username}</code><select aria-label={`Роль ${item.username}`} value={item.role} onChange={(event) => patchUser(item, { role: event.target.value })}>{Object.entries(roleLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select><span className={item.is_active ? styles.ok : styles.muted}>{item.is_active ? 'Активен' : 'Отключён'}</span><span>{formatDateTime(item.last_login_at)}</span><button onClick={() => patchUser(item, { is_active: !item.is_active })}>{item.is_active ? 'Деактивировать' : 'Активировать'}</button></div>)}</div>}
    </>
  )

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
        <label>Provider<input name="provider" defaultValue={data.provider} /></label>
        <label>Model<input name="model" defaultValue={data.model} /></label>
        <label>Base URL<input name="base_url" type="url" defaultValue={data.base_url} /></label>
        <label>Timeout, сек.<input name="timeout_seconds" type="number" min="1" max="300" defaultValue={data.timeout_seconds} /></label>
        <label className={styles.checkbox}><input name="enabled" type="checkbox" defaultChecked={data.enabled} /> Renderer включён</label>
        <div className={styles.secretState}>API key: <b>{data.api_key_configured ? '● configured' : '○ not configured'}</b>. Значение ключа никогда не возвращается.</div>
        <button disabled={loading}>Применить</button>
        <button disabled={loading} type="button" onClick={() => mutate('/api/admin/ai/health', { method: 'POST' }, 'Проверка подключения завершена.')}>Проверить подключение</button>
      </form>
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
        <nav>{sections.map(([key, label]) => <button className={section === key ? styles.active : ''} key={key} onClick={() => { setSection(key); setSearch(''); setFilters({}); setSelectedObject(null) }}>{label}</button>)}</nav>
        <footer><select value={user.username} onChange={selectUser}>{users.map((item) => <option key={item.id} value={item.username}>{item.full_name}</option>)}</select><small>{roleLabels[user.role]}</small><button type="button" onClick={onLogout}>Выйти</button></footer>
      </aside>
      <section className={styles.workspace}>
        <header className={styles.topbar}><div><small>Системное управление</small><h1>{title}</h1></div>{['classifier', 'services', 'objects'].includes(section) && <form onSubmit={(event) => { event.preventDefault(); load() }}><input aria-label="Поиск" placeholder="Поиск…" value={search} onChange={(event) => setSearch(event.target.value)} />{renderFilters()}<button>Найти</button></form>}<button onClick={load}>Обновить</button></header>
        {error && <div className={styles.error} role="alert">{error}</div>}
        {notice && <div className={styles.notice}>{notice}</div>}
        <div className={styles.content} aria-busy={loading}>{loading && data === null ? <div className={styles.loading}>Загрузка…</div> : content()}</div>
      </section>
    </main>
  )
}

AdminWorkspace.propTypes = {
  user: PropTypes.object.isRequired,
  users: PropTypes.array.isRequired,
  selectUser: PropTypes.func.isRequired,
  requestJson: PropTypes.func.isRequired,
  onLogout: PropTypes.func.isRequired,
}

export default AdminWorkspace
