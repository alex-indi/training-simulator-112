import { useEffect, useState } from 'react'
import PropTypes from 'prop-types'

import styles from './App.module.css'

const weekdayFormatter = new Intl.DateTimeFormat('ru-RU', { weekday: 'long', timeZone: 'Europe/Moscow' })
const monthFormatter = new Intl.DateTimeFormat('ru-RU', { month: 'long', timeZone: 'Europe/Moscow' })
const dayYearFormatter = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', year: 'numeric', timeZone: 'Europe/Moscow' })
const timeFormatter = new Intl.DateTimeFormat('ru-RU', {
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZone: 'Europe/Moscow',
})

function formatDate(value) {
  const weekday = weekdayFormatter.format(value)
  const month = monthFormatter.format(value)
  const parts = dayYearFormatter.formatToParts(value)
  const day = parts.find((part) => part.type === 'day')?.value
  const year = parts.find((part) => part.type === 'year')?.value
  return `${weekday[0].toUpperCase()}${weekday.slice(1)}, ${day} ${month[0].toUpperCase()}${month.slice(1)} ${year}`
}

function WorkspaceClock({ user, users, selectUser, onLogout }) {
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const [hours, minutes, seconds] = timeFormatter.format(now).split(':')

  return <div className={styles.clockPanel}>
    <div className={styles.clockUpper}>
      <div className={styles.clockDetails}>
        <strong>{formatDate(now)}</strong>
        <div className={styles.clockToolbar}>
          <span>УМЦ О.п.</span>
          <label className={styles.clockUserPicker} title={`Сменить пользователя: ${user.full_name}`}>
            <span className={styles.clockMonitorIcon} aria-hidden="true" />
            <select value={user.username} onChange={selectUser} disabled={!users.length} aria-label="Текущий пользователь">
              {users.map((item) => <option key={item.id} value={item.username}>{item.full_name}</option>)}
            </select>
          </label>
          <span className={styles.clockGearIcon} aria-hidden="true" />
          <span className={styles.clockHelpIcon} aria-hidden="true" />
          <button className={styles.sessionExit} type="button" onClick={onLogout} aria-label="Выйти" title="Выйти">
            <span className={styles.clockRunIcon} aria-hidden="true" />
          </button>
        </div>
      </div>
      <time className={styles.clockTime} dateTime={now.toISOString()}>
        <span>{hours}:{minutes}</span><sup>:{seconds}</sup>
      </time>
    </div>
    <div className={styles.clockLower} aria-hidden="true" />
  </div>
}

WorkspaceClock.propTypes = {
  user: PropTypes.object.isRequired,
  users: PropTypes.array.isRequired,
  selectUser: PropTypes.func.isRequired,
  onLogout: PropTypes.func.isRequired,
}

export default WorkspaceClock
