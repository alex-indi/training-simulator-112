/* eslint-disable react/prop-types */
import { useEffect, useState } from 'react'

import styles from './TrainingResults.module.css'

function TrainingResults({ user, requestJson }) {
  const [results, setResults] = useState([])
  const [open, setOpen] = useState(false)
  const [expandedSessionId, setExpandedSessionId] = useState(null)

  useEffect(() => {
    let active = true
    const refresh = () => requestJson('/api/training/my/results', user.username)
      .then((rows) => { if (active) setResults(rows) })
      .catch(() => {})
    refresh()
    const timer = window.setInterval(refresh, 15000)
    return () => { active = false; window.clearInterval(timer) }
  }, [open, requestJson, user.username])

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
      title="Показать результаты занятий"
    >
      Результаты занятий{results.length ? ` (${results.length})` : ''}
    </button>

    {open && <div className={styles.backdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false) }}>
      <section className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="training-results-title">
        <header className={styles.header}>
          <div>
            <small>Рабочее место ДДС</small>
            <h2 id="training-results-title">Результаты занятий</h2>
          </div>
          <button type="button" onClick={() => setOpen(false)} aria-label="Закрыть">×</button>
        </header>
        <div className={styles.content}>
          {!results.length && <p className={styles.empty}>Результаты занятий пока не опубликованы преподавателем.</p>}
          {results.map((item) => {
            const expanded = expandedSessionId === item.session_id
            const metrics = item.result.metrics
            return <article className={`${styles.result} ${expanded ? styles.resultExpanded : ''}`} key={item.session_id}>
              <button className={styles.resultToggle} type="button" aria-expanded={expanded} onClick={() => setExpandedSessionId(expanded ? null : item.session_id)}>
                <span>
                  <strong>{item.title} · {new Date(item.date).toLocaleDateString('ru-RU')}</strong>
                  <small>{item.dds_profile} · {item.difficulty || 'Без сложности'} · карточек: {item.cards}</small>
                </span>
                <b>{item.result.confirmed_at ? `Итог: ${item.result.final_score} / 100` : 'Нет оценки'}</b>
                <i aria-hidden="true">{expanded ? '−' : '+'}</i>
              </button>

              {expanded && <div className={styles.details}>
                <div className={styles.metrics}>
                  <div><span>Карточек</span><strong>{metrics.cards}</strong></div>
                  <div><span>Завершено</span><strong>{metrics.completed}</strong></div>
                  <div><span>Отказов</span><strong>{metrics.refusals}</strong></div>
                  <div><span>Средняя реакция</span><strong>{metrics.average_reaction_seconds == null ? '—' : `${metrics.average_reaction_seconds} сек.`}</strong></div>
                  <div><span>Нарушений реакции</span><strong>{metrics.reaction_violations}</strong></div>
                  <div><span>Критических замечаний</span><strong>{metrics.critical_signals}</strong></div>
                </div>
                <p><b>Сильные стороны:</b> {metrics.reaction_violations === 0 ? 'Реакция в пределах норматива. ' : ''}{metrics.completed === metrics.cards ? 'Карточки завершены.' : ''}</p>
                <p><b>Требует отработки:</b> {item.result.deviations.length ? item.result.deviations.map((deviation) => deviation.description).join('; ') : 'Подтверждённых замечаний нет.'}</p>
                {item.result.final_comment && <p><b>Комментарий преподавателя:</b> {item.result.final_comment}</p>}

                {!!metrics.card_results?.length && <section className={styles.cards}>
                  <h4>Подробно по карточкам</h4>
                  {metrics.card_results.map((card) => <article className={styles.card} key={card.incident_id}>
                    <header><strong>Карточка № {card.incident_number}</strong><span>{card.finished_at ? 'Завершена' : 'Не завершена'}</span></header>
                    <p><b>Первичное решение:</b> {card.primary ? `${card.primary.decision === 'ACCEPT' ? 'Принята' : 'Не принята'} · ${card.primary.seconds} сек. при нормативе ${card.primary.limit_seconds} сек.` : 'Не принято'}</p>
                    {card.primary?.comment && <p><b>Комментарий:</b> {card.primary.comment}</p>}
                    {!!card.brigade.length && <div className={styles.brigadeEvents}>
                      <b>Работа с сообщениями бригады:</b>
                      {card.brigade.map((event, index) => <div key={`${event.stage}-${index}`}>
                        <span>{event.message}</span>
                        <small>{event.action_at ? `Реакция: ${event.seconds} сек. · норматив ${event.limit_seconds} сек.` : 'Ожидаемое действие не выполнено'}</small>
                      </div>)}
                    </div>}
                    {item.result.deviations.filter((deviation) => deviation.incident_id === card.incident_id).map((deviation) => <p className={styles.deviation} key={deviation.id}>{deviation.description}</p>)}
                  </article>)}
                </section>}
              </div>}
            </article>
          })}
        </div>
      </section>
    </div>}
  </>
}

export default TrainingResults
