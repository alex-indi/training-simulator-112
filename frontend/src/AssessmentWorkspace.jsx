/* eslint-disable react/prop-types */
import { useCallback, useEffect, useState } from 'react'
import styles from './AssessmentWorkspace.module.css'

const summaryLabels = { trainees: 'Обучаемых', cards: 'Карточек', completed: 'Завершено', refusals: 'Отказов', reaction_violations: 'Нарушений норматива', critical_signals: 'Критических сигналов' }

function AssessmentWorkspace({ session, api, embedded = false }) {
  const [report, setReport] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [reason, setReason] = useState('')
  const [comment, setComment] = useState('')
  const [score, setScore] = useState('')
  const [manual, setManual] = useState({ description: '', weight: 5, incident_id: '', critical: false })
  const [audit, setAudit] = useState([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    const fresh = await api(`/api/training/sessions/${session.id}/assessment`)
    setReport(fresh)
    setSelectedId((id) => id || fresh.runs[0]?.run_id || null)
  }, [api, session.id])

  useEffect(() => { refresh().catch((cause) => setError(cause.message)) }, [refresh])
  const selected = report?.runs.find((run) => run.run_id === selectedId)
  useEffect(() => {
    setComment(selected?.final_comment || '')
    setScore(selected?.final_score ?? '')
    if (selectedId) api(`/api/training/sessions/${session.id}/runs/${selectedId}/assessment/audit`).then(setAudit).catch(() => setAudit([]))
  }, [api, selectedId, selected?.final_comment, selected?.final_score, session.id])

  const submit = async (path, body) => {
    setBusy(true)
    setError('')
    try {
      await api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      await refresh()
      setAudit(await api(`/api/training/sessions/${session.id}/runs/${selectedId}/assessment/audit`))
    } catch (cause) { setError(cause.message) } finally { setBusy(false) }
  }
  const base = `/api/training/sessions/${session.id}/runs/${selectedId}`
  const decide = (deviation, decision) => submit(`${base}/deviations/${deviation.id}/decision`, { decision, reason })
  const addManual = async () => {
    await submit(`${base}/deviations`, { ...manual, weight: Number(manual.weight), incident_id: manual.incident_id ? Number(manual.incident_id) : null, reason })
    setManual({ description: '', weight: 5, incident_id: '', critical: false })
  }
  const finalize = () => submit(`${base}/finalize`, { final_score: score === '' ? null : Number(score), final_comment: comment, reason })

  const Root = embedded ? 'div' : 'main'

  return <Root className={`${styles.shell} ${embedded ? styles.embedded : ''}`}>
    <h1>Разбор · {session.title}</h1>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {!report ? <p>Загружаем результаты…</p> : <>
      <div className={styles.summary}>{Object.entries(summaryLabels).map(([key, label]) => <div key={key}><span>{label}</span><strong>{report.summary[key]}</strong></div>)}</div>
      <div className={styles.layout}>
        <section><h2>Класс</h2><div className={styles.tableWrap}><table><thead><tr><th>Обучаемый</th><th>АРМ</th><th>ДДС</th><th>Карточки</th><th>Завершено</th><th>Реакция</th><th>Отклонения</th><th>Критические</th><th>Результат</th></tr></thead><tbody>{report.runs.map((run) => <tr key={run.run_id} className={run.run_id === selectedId ? styles.selected : ''} onClick={() => setSelectedId(run.run_id)}><td>{run.trainee_name}</td><td>{run.workstation_number ?? '—'}</td><td>{run.dds_profile}</td><td>{run.metrics.cards}</td><td>{run.metrics.completed}</td><td>{run.metrics.average_reaction_seconds ?? '—'} с</td><td>{run.deviations.length}</td><td>{run.metrics.critical_signals}</td><td>{run.confirmed_at ? `${run.final_score} / 100` : 'Предварительный'}</td></tr>)}</tbody></table></div></section>
        {selected && <section className={styles.detail}>
          <h2>{selected.trainee_name} · АРМ {selected.workstation_number ?? '—'}</h2>
          <p>{selected.dds_profile} · {selected.difficulty || 'Без сложности'}</p>
          <div className={styles.scores}><div><span>Предварительная оценка системы</span><strong>{selected.automatic_score} / 100</strong></div><div><span>С учётом решений</span><strong>{selected.calculated_score} / 100</strong></div><div><span>Итог</span><strong>{selected.confirmed_at ? `${selected.final_score} / 100` : 'Ожидает преподавателя'}</strong></div></div>
          <p>Получено карточек: {selected.metrics.cards} · завершено: {selected.metrics.completed} · средняя первичная реакция: {selected.metrics.average_reaction_seconds ?? '—'} с</p>
          <h3>Отклонения</h3>
          {selected.deviations.map((item) => <article key={item.id} className={styles.deviation}><b>{item.critical ? '⚠ ' : ''}{item.description}</b><span>Вес: {item.weight} · {item.decision === 'CONFIRMED' ? 'Подтверждено' : item.decision === 'DISMISSED' ? 'Снято' : 'Требует проверки'}</span><div><button disabled={busy || !reason.trim()} onClick={() => decide(item, 'CONFIRMED')}>Подтвердить</button><button disabled={busy || !reason.trim()} onClick={() => decide(item, 'DISMISSED')}>Не является ошибкой</button></div></article>)}
          {!selected.deviations.length && <p>Отклонений не найдено.</p>}
          <h3>Проблемные карточки</h3>
          {selected.problem_cards.map((card) => <details key={card.id}><summary>{card.incident_number}</summary><ol>{card.timeline.map((entry, index) => <li key={index}>{entry.at ? new Date(entry.at).toLocaleString('ru-RU') : '—'} · {entry.event}{entry.comment ? ` · ${entry.comment}` : ''}</li>)}</ol></details>)}
          <h3>Заметки преподавателя</h3>{selected.notes.map((note, index) => <p key={index}>{note.body}</p>)}{!selected.notes.length && <p>Заметок нет.</p>}
          <h3>Добавить замечание</h3><textarea aria-label="Новое замечание" value={manual.description} onChange={(event) => setManual({ ...manual, description: event.target.value })} /><div className={styles.inline}><label>Вес <input type="number" min="1" max="100" value={manual.weight} onChange={(event) => setManual({ ...manual, weight: event.target.value })} /></label><label>Карточка <select value={manual.incident_id} onChange={(event) => setManual({ ...manual, incident_id: event.target.value })}><option value="">Без карточки</option>{selected.problem_cards.map((card) => <option key={card.id} value={card.id}>{card.incident_number}</option>)}</select></label><label><input type="checkbox" checked={manual.critical} onChange={(event) => setManual({ ...manual, critical: event.target.checked })} /> Критическое</label></div><button disabled={busy || !reason.trim() || !manual.description.trim()} onClick={addManual}>Добавить замечание</button>
          <h3>Итог обучаемого</h3><label>Итоговая оценка (пусто — расчётная)<input type="number" min="0" max="100" value={score} onChange={(event) => setScore(event.target.value)} /></label><label>Комментарий преподавателя<textarea value={comment} onChange={(event) => setComment(event.target.value)} /></label><label>Причина решения или изменения<textarea value={reason} onChange={(event) => setReason(event.target.value)} /></label><button disabled={busy || !reason.trim() || selected.deviations.some((item) => item.decision === 'PENDING')} onClick={finalize}>{selected.confirmed_at ? 'Сохранить изменение итога' : 'Подтвердить итог'}</button>
          <details><summary>История корректировок ({audit.length})</summary><ol>{audit.map((item) => <li key={item.id}>{new Date(item.changed_at).toLocaleString('ru-RU')} · {item.action} · {item.reason} · пользователь #{item.changed_by}</li>)}</ol></details>
        </section>}
      </div>
    </>}
  </Root>
}

export default AssessmentWorkspace
