/* eslint-disable react/prop-types */
import { useCallback, useEffect, useState } from 'react'
import styles from './AssessmentWorkspace.module.css'

const actionNames = {
  START_RESPONSE: 'Начало реагирования', MARK_ARRIVAL: 'Прибытие',
  START_WORK: 'Проведение работ', COMPLETE_WORK: 'Завершено',
}
const severityNames = { CRITICAL: 'Критическая', MAJOR: 'Основная', ADDITIONAL: 'Дополнительная', OK: 'Норма' }
const primaryNames = { ACCEPT: 'Принята', REJECT: 'Не принята' }
const dateTime = (value) => value ? new Date(value).toLocaleString('ru-RU') : '—'

function AssessmentWorkspace({ session, api, embedded = false }) {
  const [report, setReport] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [comment, setComment] = useState('')
  const [score, setScore] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    const fresh = await api(`/api/training/sessions/${session.id}/assessment`)
    setReport(fresh)
    setSelectedId((id) => fresh.runs.some((run) => run.run_id === id) ? id : fresh.runs[0]?.run_id || null)
  }, [api, session.id])

  useEffect(() => { refresh().catch((cause) => setError(cause.message)) }, [refresh])
  const selected = report?.runs.find((run) => run.run_id === selectedId)
  useEffect(() => {
    setComment(selected?.final_comment || '')
    setScore(selected?.final_score ?? '')
  }, [selectedId, selected?.final_comment, selected?.final_score])
  useEffect(() => {
    if (!selectedId || !selected || selected.ai_summary_generated_at) return
    let active = true
    api(`/api/training/sessions/${session.id}/runs/${selectedId}/assessment/summary`)
      .then(() => { if (active) refresh() })
      .catch((cause) => { if (active) setError(cause.message) })
    return () => { active = false }
  }, [api, refresh, selected, selectedId, session.id])

  const submit = async (path, body) => {
    setBusy(true)
    setError('')
    try {
      await api(path, { method: 'POST', ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}) })
      await refresh()
    } catch (cause) { setError(cause.message) } finally { setBusy(false) }
  }
  const base = `/api/training/sessions/${session.id}/runs/${selectedId}`
  const regenerate = () => submit(`${base}/assessment/regenerate-summary`, { instructor_comment: comment })
  const save = () => submit(`${base}/finalize`, { final_score: Number(score), final_comment: comment })
  const Root = embedded ? 'div' : 'main'

  return <Root className={`${styles.shell} ${embedded ? styles.embedded : ''}`}>
    <h1>Результаты занятия · {session.title}</h1>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {!report ? <p>Загружаем результаты…</p> : <>
      <div className={styles.summary}>
        <div><span>Обучаемых</span><strong>{report.summary.trainees}</strong></div>
        <div><span>Карточек</span><strong>{report.summary.cards}</strong></div>
        <div><span>Завершено</span><strong>{report.summary.completed}</strong></div>
      </div>
      <div className={styles.layout}>
        <section><h2>Обучаемые</h2><div className={styles.tableWrap}><table><thead><tr><th>Обучаемый</th><th>АРМ</th><th>Карточки</th><th>Критические</th><th>Основные</th><th>Дополнительные</th><th>Итог</th></tr></thead><tbody>
          {report.runs.map((run) => <tr key={run.run_id} className={run.run_id === selectedId ? styles.selected : ''} onClick={() => setSelectedId(run.run_id)}>
            <td>{run.trainee_name}</td><td>{run.workstation_number ?? '—'}</td><td>{run.metrics.cards}</td>
            <td>{run.deviations.filter((item) => item.severity === 'CRITICAL').length}</td>
            <td>{run.deviations.filter((item) => item.severity === 'MAJOR').length}</td>
            <td>{run.deviations.filter((item) => item.severity === 'ADDITIONAL').length}</td>
            <td>{run.confirmed_at ? `${run.final_score} / 100` : 'Не выставлена'}</td>
          </tr>)}
        </tbody></table></div></section>
        {selected && <section className={styles.detail}>
          <h2>{selected.trainee_name} · АРМ {selected.workstation_number ?? '—'}</h2>
          <p>{selected.dds_profile} · Обработано карточек: {selected.metrics.cards} · Завершено: {selected.metrics.completed}</p>
          <div className={styles.scores}>
            <div><span>Критические ошибки</span><strong>{selected.deviations.filter((item) => item.severity === 'CRITICAL').length}</strong></div>
            <div><span>Основные ошибки</span><strong>{selected.deviations.filter((item) => item.severity === 'MAJOR').length}</strong></div>
            <div><span>Дополнительные</span><strong>{selected.deviations.filter((item) => item.severity === 'ADDITIONAL').length}</strong></div>
          </div>
          <h3>Карточки и время реакции</h3>
          {(selected.metrics.card_results || []).map((card) => <details key={card.incident_id} open>
            <summary>{card.incident_number} · поступила {dateTime(card.delivered_at)}</summary>
            <p>Первичное решение: {card.primary ? `${primaryNames[card.primary.decision] || card.primary.decision} · ${dateTime(card.primary.at)} · ${card.primary.seconds} с / ${card.primary.limit_seconds} с · ${severityNames[card.primary.severity]}` : 'отсутствует'}</p>
            {card.brigade.map((step, index) => <p key={`${step.stage}-${index}`}>
              Бригада: {dateTime(step.at)} · {step.message}<br />
              ДДС: {actionNames[step.expected_action]} · {dateTime(step.action_at)} · {step.seconds == null ? 'нет реакции' : `${step.seconds} с / ${step.limit_seconds} с`} · {severityNames[step.severity]}
            </p>)}
          </details>)}
          <h3>Объективные замечания</h3>
          {selected.deviations.map((item) => <p key={item.id} className={styles.deviation}><b>{severityNames[item.severity]}:</b> {item.description}</p>)}
          {!selected.deviations.length && <p>Замечаний нет.</p>}
          <h3>Автоматическое резюме</h3>
          <p className={styles.aiSummary}>{selected.ai_summary}</p>
          <button type="button" disabled={busy} onClick={regenerate}>Перегенерировать резюме</button>
          <h3>Результат преподавателя</h3>
          <label>Комментарий преподавателя<textarea value={comment} onChange={(event) => setComment(event.target.value)} /></label>
          <label>Итоговая оценка, 0–100<input type="number" min="0" max="100" value={score} onChange={(event) => setScore(event.target.value)} /></label>
          <button type="button" disabled={busy || score === '' || Number(score) < 0 || Number(score) > 100} onClick={save}>Сохранить результат</button>
          {selected.confirmed_at && <p>Сохранено {dateTime(selected.confirmed_at)}</p>}
        </section>}
      </div>
    </>}
  </Root>
}

export default AssessmentWorkspace
