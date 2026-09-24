/* eslint-disable react/prop-types */
import { useEffect, useState } from 'react'

function TrainingResults({ user, requestJson }) {
  const [results, setResults] = useState([])
  useEffect(() => {
    let active = true
    const refresh = () => requestJson('/api/training/my/results', user.username)
      .then((rows) => { if (active) setResults(rows) }).catch(() => {})
    refresh()
    const timer = window.setInterval(refresh, 15000)
    return () => { active = false; window.clearInterval(timer) }
  }, [requestJson, user.username])

  if (!results.length) return null
  return <details style={{ margin: '1rem', padding: '1rem', background: '#edf5f7', borderRadius: 8 }}>
    <summary>Результаты завершённых занятий ({results.length})</summary>
    {results.map((item) => <article key={item.session_id} style={{ padding: '1rem 0', borderBottom: '1px solid #cadce2' }}>
      <h3>{item.title} · {new Date(item.date).toLocaleDateString('ru-RU')}</h3>
      <p>{item.dds_profile} · {item.difficulty || 'Без сложности'} · карточек: {item.cards}</p>
      <strong>Итог: {item.result.final_score} / 100</strong>
      <p><b>Сильные стороны:</b> {item.result.metrics.reaction_violations === 0 ? 'Реакция в пределах норматива. ' : ''}{item.result.metrics.completed === item.result.metrics.cards ? 'Карточки завершены.' : ''}</p>
      <p><b>Требует отработки:</b> {item.result.deviations.length ? item.result.deviations.map((deviation) => deviation.description).join('; ') : 'Подтверждённых замечаний нет.'}</p>
      {item.result.final_comment && <p><b>Комментарий преподавателя:</b> {item.result.final_comment}</p>}
    </article>)}
  </details>
}

export default TrainingResults
