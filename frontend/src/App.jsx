import { useEffect, useState } from 'react'

import styles from './App.module.css'

const apiUrl = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

const roleContent = {
  ADMIN: {
    label: 'Администратор',
    title: 'Настройка учебного стенда',
    description: 'Управляйте пользователями, ролями, ДДС и справочниками.',
    action: 'Открыть параметры стенда',
  },
  INSTRUCTOR: {
    label: 'Преподаватель',
    title: 'Управление обучением',
    description: 'Готовьте занятия, назначайте обучаемых и наблюдайте за ходом смены.',
    action: 'Создать учебную сессию',
  },
  TRAINEE: {
    label: 'Обучаемый',
    title: 'Рабочее место диспетчера ДДС',
    description: 'Получайте учебные карточки и принимайте решения по реагированию.',
    action: 'Перейти к карточкам',
  },
}

async function requestJson(path, demoUsername) {
  const headers = demoUsername ? { 'X-Demo-User': demoUsername } : {}
  const response = await fetch(`${apiUrl}${path}`, { headers })

  if (!response.ok) {
    throw new Error('Backend локального стенда недоступен')
  }

  return response.json()
}

function App() {
  const [users, setUsers] = useState([])
  const [currentUser, setCurrentUser] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([requestJson('/api/users/demo'), requestJson('/api/users/me')])
      .then(([demoUsers, user]) => {
        setUsers(demoUsers)
        setCurrentUser(user)
      })
      .catch((requestError) => setError(requestError.message))
  }, [])

  const selectUser = async (event) => {
    const demoUsername = event.target.value
    setError('')

    try {
      setCurrentUser(await requestJson('/api/users/me', demoUsername))
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  const currentRole = roleContent[currentUser?.role] || roleContent.TRAINEE

  return (
    <main className={styles.page}>
      <section className={styles.shell}>
        <header className={styles.header}>
          <div className={styles.brand}>
            <div className={styles.badge} aria-hidden="true">
              112
            </div>
            <div>
              <p className={styles.eyebrow}>Учебный тренажёр</p>
              <strong>Диспетчерская ДДС</strong>
            </div>
          </div>
          <label className={styles.userSelect}>
            <span>Текущий пользователь</span>
            <select value={currentUser?.username || ''} onChange={selectUser} disabled={!users.length}>
              {!currentUser && <option value="">Загрузка…</option>}
              {users.map((user) => (
                <option key={user.id} value={user.username}>
                  {user.full_name} · {roleContent[user.role].label}
                </option>
              ))}
            </select>
          </label>
        </header>

        <div className={styles.content}>
          <div className={styles.rolePill}>{currentRole.label}</div>
          <p className={styles.eyebrow}>Локальный демонстрационный стенд</p>
          <h1>{currentRole.title}</h1>
          <p className={styles.description}>{currentRole.description}</p>
          {error ? (
            <div className={styles.error} role="alert">{error}</div>
          ) : (
            <button className={styles.primaryAction} type="button" disabled={!currentUser}>
              {currentRole.action}
            </button>
          )}
        </div>

        <footer className={styles.footer}>
          <span className={styles.statusDot} />
          Роль определяется backend по выбранному demo-пользователю
        </footer>
      </section>
    </main>
  )
}

export default App
