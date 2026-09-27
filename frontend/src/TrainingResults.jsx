/* eslint-disable react/prop-types */
import { useEffect, useState } from 'react'

import styles from './TrainingResults.module.css'

function TrainingResults({ user, requestJson }) {
  const [results, setResults] = useState([])
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let active = true
    const refresh = () => requestJson('/api/training/my/results', user.username)
      .then((rows) => { if (active) setResults(rows) })
      .catch(() => {})
    refresh()
    const timer = window.setInterval(refresh, 15000)
    return () => { active = false; window.clearInterval(timer) }
  }, [requestJson, user.username])

  useEffect(() => {
    if (!open) return undefined
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open])

  return <>
    <button
      className={styles.resultsButton}
      type="button"
      onClick={() => setOpen(true)}
      title="Показать результаты заданий"
    >
      Результаты{results.length ? ` (${results.length})` : ''}
    </button>

    {open && <div className={styles.backdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false) }}>
      <section className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="training-results-title">
        <header className={styles.header}>
          <div>
            <small>Рабочее место ДДС</small>
            <h2 id="training-results-title">Результаты завершённых заданий</h2>
          </div>
          <button type="button" onClick={() => setOpen(false)} aria-label="Закрыть">×</button>
        </header>
        <div className={styles.content}>
          {!results.length && <p className={styles.empty}>Результаты завершённых заданий пока не опубликованы преподавателем.</p>}
          {results.map((item) => <article className={styles.result} key={item.session_id}>
            <h3>{item.title} · {new Date(item.date).toLocaleDateString('ru-RU')}</h3>
            <p>{item.dds_profile} · {item.difficulty || 'Без сложности'} · карточек: {item.cards}</p>
            <strong>Итог: {item.result.final_score} / 100</strong>
            <p><b>Сильные стороны:</b> {item.result.metrics.reaction_violations === 0 ? 'Реакция в пределах норматива. ' : ''}{item.result.metrics.completed === item.result.metrics.cards ? 'Карточки завершены.' : ''}</p>
            <p><b>Требует отработки:</b> {item.result.deviations.length ? item.result.deviations.map((deviation) => deviation.description).join('; ') : 'Подтверждённых замечаний нет.'}</p>
            {item.result.final_comment && <p><b>Комментарий преподавателя:</b> {item.result.final_comment}</p>}
          </article>)}
        </div>
      </section>
    </div>}
  </>
}

export default TrainingResults
