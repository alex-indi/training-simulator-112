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
  const [generationStatus, setGenerationStatus] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const selected = instances.find((item) => item.id === selectedId)
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

  useEffect(() => {
    if (!selectedId) return undefined
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setSelectedId(null)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [selectedId])

  const perform = async (path, options, success, closeAfter = false, status = '') => {
    setBusy(true)
    setGenerationStatus(status)
    setError('')
    setNotice('')
    try {
      await api(path, options)
      await refresh()
      if (closeAfter) setSelectedId(null)
      setNotice(success)
    } catch (cause) {
      setError(cause.message)
    } finally {
      setBusy(false)
      setGenerationStatus('')
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
    setGenerationStatus(`ИИ перегенерирует тексты: 1 из ${chosen.length}…`)
    setError('')
    setNotice('')
    try {
      for (const [index, card] of chosen.entries()) {
        setGenerationStatus(`ИИ перегенерирует тексты: ${index + 1} из ${chosen.length}…`)
        await api(`/api/scenario-instances/${card.id}/rerender-initial-message`, { method: 'POST' })
      }
      await refresh()
      setSelectedForRerender([])
      setNotice(`Тексты обновлены: ${chosen.length} карточек`)
    } catch (cause) {
      setError(cause.message)
    } finally {
      setBusy(false)
      setGenerationStatus('')
    }
  }

  return <article className={`${styles.card} ${styles.preparedGroupCard}`}>
    <header className={styles.preparedGroupHeader}>
      <h3>{group.name}</h3>
      <span>Подготовлено {instances.length} карточек</span>
    </header>
    <p>{group.member_count} человек · {group.difficulty || 'Без сложности'} · {group.queue_mode === 'SHARED_QUEUE' ? 'Общий пул' : 'Личный пул'}</p>
    {Object.entries(counts).map(([name, count]) => <p key={name}>{name} · {count}</p>)}
    {!selected && error && <p className={styles.error} role="alert">{error}</p>}
    {!selected && notice && <p className={styles.notice} role="status">{notice}</p>}
    {editable && <div className={styles.actions}>
      <button type="button" disabled={busy} onClick={() => onAddSaved(group.id)}>+ Добавить готовые карточки</button>
      <button type="button" disabled={busy} onClick={() => onAdd(group.id)}>+ Сформировать из шаблона</button>
      <button type="button" disabled={busy || !selectedForRerender.some((id) => drafts.some((item) => item.id === id))} onClick={rerenderSelected}>Перегенерировать тексты выбранных</button>
    </div>}
    {!selected && generationStatus && <p className={styles.generationStatus} role="status">{generationStatus}</p>}
    {!!instances.length && <div className={styles.scenarioList}>
      <nav aria-label={`Карточки группы ${group.name}`} className={styles.cardList}>{instances.map((item, index) => <div key={item.id}>
        {editable && item.status === 'DRAFT' && <input type="checkbox" aria-label={`Выбрать карточку ${index + 1} для перегенерации`} checked={selectedForRerender.includes(item.id)} onChange={(event) => setSelectedForRerender((current) => event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id))} />}
        <button type="button" onClick={() => { setError(''); setNotice(''); setSelectedId(item.id) }}><span>{index + 1}. {item.template_snapshot.name} · {item.object_snapshot.name}</span><span className={styles.openCardHint}>Открыть →</span></button>
      </div>)}</nav>
    </div>}
    {selected && <div className={styles.pickerOverlay} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedId(null) }}>
      <section className={`${styles.pickerDialog} ${styles.cardEditorDialog}`} role="dialog" aria-modal="true" aria-labelledby={`card-editor-${group.id}-${selected.id}`}>
        <header className={styles.cardEditorHeader}>
          <div><small>{group.name}</small><h3 id={`card-editor-${group.id}-${selected.id}`}>{selected.template_snapshot.name}</h3></div>
          <button type="button" autoFocus onClick={() => setSelectedId(null)}>Закрыть</button>
        </header>
        {error && <p className={styles.error} role="alert">{error}</p>}
        {notice && <p className={styles.notice} role="status">{notice}</p>}
        {generationStatus && <p className={styles.generationStatus} role="status">{generationStatus}</p>}
        <div className={styles.cardEditorBody}>
          <p><b>Объект:</b> {selected.object_snapshot.name}</p>
          <p><b>Адрес:</b> {selected.object_snapshot.address}</p>
          <p><b>Условия:</b> {Object.entries(selected.initial_state_snapshot.variant_facts || {}).map(([key, value]) => `${factNames[key] || key}: ${value}`).join(' · ') || 'Без дополнительных условий'}</p>
          {canEdit && !!Object.keys(variantOptions).length && <div className={styles.formGrid}>
            {Object.entries(variantOptions).map(([key, choices]) => <label key={key}>{factNames[key] || key}<select value={facts[key] ?? ''} onChange={(event) => setFacts((current) => ({ ...current, [key]: key === 'floor' ? Number(event.target.value) : event.target.value }))}>{choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}</select></label>)}
            <button type="button" disabled={busy || Object.keys(variantOptions).every((key) => facts[key] === selected.initial_state_snapshot.variant_facts[key])} onClick={() => perform(`${path}/variant-facts`, json('PATCH', facts), 'Условия сохранены', false, 'ИИ обновляет текст карточки…')}>Сохранить условия</button>
          </div>}
          <label>Текст карточки<textarea value={text} readOnly={!canEdit} onChange={(event) => setText(event.target.value)} /></label>
          {editable && <button type="button" disabled={busy || (canEdit && text !== selected.initial_state_snapshot.render?.rendered_text)} onClick={() => perform(`/api/incident-cards/from-instance/${selected.id}`, { method: 'POST' }, 'Карточка сохранена в библиотеку')}>Сохранить в библиотеку</button>}
          {canEdit && <div className={styles.actions}>
            <button type="button" disabled={busy || !text.trim() || text === selected.initial_state_snapshot.render?.rendered_text} onClick={() => perform(`${path}/initial-message`, json('PATCH', { text }), 'Текст сохранён')}>Исправить текст</button>
            <button type="button" disabled={busy} onClick={() => perform(`${path}/rerender-initial-message`, { method: 'POST' }, 'Текст перегенерирован', false, 'ИИ перегенерирует текст карточки…')}>Перегенерировать текст</button>
            <button type="button" disabled={busy} onClick={() => perform(`${path}/regenerate-card`, { method: 'POST' }, 'Карточка перегенерирована', false, 'ИИ перегенерирует карточку…')}>Перегенерировать карточку</button>
            <button type="button" disabled={busy} onClick={() => perform(path, { method: 'DELETE' }, 'Карточка исключена', true)}>Исключить</button>
          </div>}
          <p className={styles.hint}>Ход работы служб формируется тренажёром автоматически во время занятия. Здесь преподаватель проверяет только карточку, которую увидит ДДС.</p>
        </div>
      </section>
    </div>}
  </article>
}
