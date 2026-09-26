/* eslint-disable react/prop-types */
import { useEffect, useState } from 'react'

import styles from './InstructorWorkspace.module.css'

const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const factNames = { floor: 'Этаж', room: 'Помещение', observation: 'Обстановка', casualties: 'Пострадавшие' }

export default function PreparedGroupCards({ group, instances, editable, api, refresh, onAdd, onAddSaved }) {
  const [selectedId, setSelectedId] = useState(null)
  const [selectedForRerender, setSelectedForRerender] = useState([])
  const [text, setText] = useState('')
  const [facts, setFacts] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const selected = instances.find((item) => item.id === selectedId) || instances[0]
  const drafts = instances.filter((item) => item.status === 'DRAFT')
  const counts = instances.reduce((result, item) => {
    const name = item.template_snapshot.name
    result[name] = (result[name] || 0) + 1
    return result
  }, {})

  useEffect(() => {
    setText(selected?.initial_state_snapshot.render?.rendered_text || '')
    setFacts(selected?.initial_state_snapshot.variant_facts || {})
  }, [selected])

  const perform = async (path, options, success) => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await api(path, options)
      await refresh()
      setNotice(success)
    } catch (cause) {
      setError(cause.message)
    } finally {
      setBusy(false)
    }
  }
  const path = selected ? `/api/scenario-instances/${selected.id}` : ''
  const variantOptions = selected?.template_snapshot.variant_options || {}
  const canEdit = editable && selected?.status === 'DRAFT'
  const rerenderSelected = async () => {
    const chosen = drafts.filter((item) => selectedForRerender.includes(item.id))
    if (!chosen.length) return
    if (chosen.some((item) => item.initial_state_snapshot.render?.render_origin === 'MANUAL')
      && !window.confirm('Выбранные карточки содержат ручные правки текста. Заменить их?')) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      for (const card of chosen) {
        await api(`/api/scenario-instances/${card.id}/rerender-initial-message`, { method: 'POST' })
      }
      await refresh()
      setSelectedForRerender([])
      setNotice(`Тексты обновлены: ${chosen.length} карточек`)
    } catch (cause) {
      setError(cause.message)
    } finally {
      setBusy(false)
    }
  }

  return <article className={styles.card}>
    <h3>{group.name}</h3>
    <p>{group.difficulty || 'Без сложности'} · {group.queue_mode === 'SHARED_QUEUE' ? 'Общий пул' : 'Личный пул'}</p>
    <p>Подготовлено {instances.length} карточек</p>
    {Object.entries(counts).map(([name, count]) => <p key={name}>{name} · {count}</p>)}
    {error && <p className={styles.error} role="alert">{error}</p>}
    {notice && <p className={styles.notice} role="status">{notice}</p>}
    {editable && <div className={styles.actions}>
      <button type="button" disabled={busy} onClick={() => onAddSaved(group.id)}>+ Добавить готовые карточки</button>
      <button type="button" disabled={busy} onClick={() => onAdd(group.id)}>+ Сформировать из шаблона</button>
      <button type="button" disabled={busy || !selectedForRerender.some((id) => drafts.some((item) => item.id === id))} onClick={rerenderSelected}>Перегенерировать тексты выбранных</button>
    </div>}
    {!!instances.length && <div className={styles.scenarioList}>
      <nav aria-label={`Карточки группы ${group.name}`} className={styles.cardList}>{instances.map((item, index) => <div key={item.id}>
        {editable && item.status === 'DRAFT' && <input type="checkbox" aria-label={`Выбрать карточку ${index + 1} для перегенерации`} checked={selectedForRerender.includes(item.id)} onChange={(event) => setSelectedForRerender((current) => event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id))} />}
        <button type="button" className={item.id === selected?.id ? styles.selectedCard : ''} onClick={() => setSelectedId(item.id)}>{index + 1}. {item.template_snapshot.name} · {item.object_snapshot.name}</button>
      </div>)}</nav>
      {selected && <section className={styles.scenario}>
        <h4>{selected.template_snapshot.name}</h4>
        <p><b>Объект:</b> {selected.object_snapshot.name}</p>
        <p><b>Адрес:</b> {selected.object_snapshot.address}</p>
        <p><b>Условия:</b> {Object.entries(selected.initial_state_snapshot.variant_facts || {}).map(([key, value]) => `${factNames[key] || key}: ${value}`).join(' · ') || 'Без дополнительных условий'}</p>
        {canEdit && !!Object.keys(variantOptions).length && <div className={styles.formGrid}>
          {Object.entries(variantOptions).map(([key, choices]) => <label key={key}>{factNames[key] || key}<select value={facts[key] ?? ''} onChange={(event) => setFacts((current) => ({ ...current, [key]: key === 'floor' ? Number(event.target.value) : event.target.value }))}>{choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}</select></label>)}
          <button type="button" disabled={busy || Object.keys(variantOptions).every((key) => facts[key] === selected.initial_state_snapshot.variant_facts[key])} onClick={() => perform(`${path}/variant-facts`, json('PATCH', facts), 'Условия сохранены')}>Сохранить условия</button>
        </div>}
        <label>Текст карточки<textarea value={text} readOnly={!canEdit} onChange={(event) => setText(event.target.value)} /></label>
        {editable && <button type="button" disabled={busy || (canEdit && text !== selected.initial_state_snapshot.render?.rendered_text)} onClick={() => perform(`/api/incident-cards/from-instance/${selected.id}`, { method: 'POST' }, 'Карточка сохранена в библиотеку')}>Сохранить в библиотеку</button>}
        {canEdit && <div className={styles.actions}>
          <button type="button" disabled={busy || !text.trim() || text === selected.initial_state_snapshot.render?.rendered_text} onClick={() => perform(`${path}/initial-message`, json('PATCH', { text }), 'Текст сохранён')}>Исправить текст</button>
          <button type="button" disabled={busy} onClick={() => perform(`${path}/rerender-initial-message`, { method: 'POST' }, 'Текст перегенерирован')}>Перегенерировать текст</button>
          <button type="button" disabled={busy} onClick={() => perform(`${path}/regenerate-card`, { method: 'POST' }, 'Карточка перегенерирована')}>Перегенерировать карточку</button>
          <button type="button" disabled={busy} onClick={() => perform(path, { method: 'DELETE' }, 'Карточка исключена')}>Исключить</button>
        </div>}
        <p className={styles.hint}>Ход работы служб формируется тренажёром автоматически во время занятия. Здесь преподаватель проверяет только карточку, которую увидит ДДС.</p>
      </section>}
    </div>}
  </article>
}
