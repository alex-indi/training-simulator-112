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
  const [additionalConditions, setAdditionalConditions] = useState([])
  const [busy, setBusy] = useState(false)
  const [generationStatus, setGenerationStatus] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const selected = instances.find((item) => item.id === selectedId)
  const counts = instances.reduce((result, item) => {
    const name = item.template_snapshot.name
    result[name] = (result[name] || 0) + 1
    return result
  }, {})

  useEffect(() => {
    setText(selected?.initial_state_snapshot.render?.rendered_text || '')
    setFacts(selected?.initial_state_snapshot.variant_facts || {})
    setAdditionalConditions(selected?.initial_state_snapshot.additional_conditions || [])
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
  const canEdit = editable
  const savedConditions = selected?.initial_state_snapshot.additional_conditions || []
  const cleanedConditions = additionalConditions.map((value) => value.trim()).filter(Boolean)
  const conditionsChanged = JSON.stringify(cleanedConditions) !== JSON.stringify(savedConditions)
  const factsChanged = Object.keys(variantOptions).some((key) => facts[key] !== selected?.initial_state_snapshot.variant_facts?.[key])
  const textChanged = text !== selected?.initial_state_snapshot.render?.rendered_text
  const saveAdditionalConditions = () => {
    if ((textChanged || factsChanged || selected.initial_state_snapshot.render?.render_origin === 'MANUAL')
      && !window.confirm('Сохранение дополнительных условий заменит текущий текст и несохранённые правки карточки. Продолжить?')) return
    perform(`${path}/additional-conditions`, json('PATCH', { conditions: cleanedConditions }), 'Условия сохранены, текст обновлён', false, 'ИИ обновляет текст карточки…')
  }
  const rerenderSelected = async () => {
    const chosen = instances.filter((item) => selectedForRerender.includes(item.id))
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
      <button type="button" disabled={busy} onClick={() => onAddSaved(group.id)}>+ Добавить из библиотеки</button>
      <button type="button" disabled={busy} onClick={() => onAdd(group.id)}>+ Сформировать из шаблона</button>
      <button type="button" disabled={busy || !selectedForRerender.some((id) => instances.some((item) => item.id === id))} onClick={rerenderSelected}>Перегенерировать тексты выбранных</button>
    </div>}
    {!selected && generationStatus && <p className={styles.generationStatus} role="status">{generationStatus}</p>}
    {!!instances.length && <div className={styles.scenarioList}>
      <nav aria-label={`Карточки группы ${group.name}`} className={styles.cardList}>{instances.map((item, index) => <div key={item.id}>
        {editable && <input type="checkbox" aria-label={`Выбрать карточку ${index + 1} для перегенерации`} checked={selectedForRerender.includes(item.id)} onChange={(event) => setSelectedForRerender((current) => event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id))} />}
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
          <div className={styles.cardEditorClassification}>
            <span>Классификация</span>
            <strong>{selected.classifier_snapshot.incident_group || selected.classifier_snapshot.final_incident_type}</strong>
            {selected.classifier_snapshot.final_incident_type && selected.classifier_snapshot.final_incident_type !== selected.classifier_snapshot.incident_group && <small>Вид происшествия: {selected.classifier_snapshot.final_incident_type}</small>}
          </div>
          <div className={styles.cardEditorMeta}>
            <p><b>Объект</b><span>{selected.object_snapshot.name}</span></p>
            <p><b>Адрес</b><span>{selected.object_snapshot.address}</span></p>
          </div>
          <section className={styles.cardEditorSection}>
            <div className={styles.cardEditorSectionHeader}>
              <h4>Условия</h4>
            </div>
            <p className={styles.cardEditorHint}>Учебные варианты заданы шаблоном; классификация взята из справочника.</p>
            {canEdit && !!Object.keys(variantOptions).length ? <>
              <div className={styles.cardEditorFacts}>
                {Object.entries(variantOptions).map(([key, choices]) => <label key={key}>{factNames[key] || key}<select value={facts[key] ?? ''} onChange={(event) => setFacts((current) => ({ ...current, [key]: key === 'floor' ? Number(event.target.value) : event.target.value }))}>{choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}</select></label>)}
              </div>
              <div className={styles.cardEditorSectionActions}><button type="button" className={styles.cardEditorPrimary} disabled={busy || conditionsChanged || !factsChanged} title={conditionsChanged ? 'Сначала сохраните дополнительные условия' : ''} onClick={() => perform(`${path}/variant-facts`, json('PATCH', facts), 'Условия сохранены', false, 'ИИ обновляет текст карточки…')}>Сохранить условия</button></div>
            </> : <p>{Object.entries(selected.initial_state_snapshot.variant_facts || {}).map(([key, value]) => `${factNames[key] || key}: ${value}`).join(' · ') || 'Без дополнительных условий'}</p>}
            <div className={styles.cardEditorAdditional}>
              <div className={styles.cardEditorAdditionalHeader}><div><h5>Дополнительные условия</h5><small>Учитываются при формировании текста карточки.</small></div>{canEdit && <button type="button" disabled={busy || additionalConditions.length >= 8} onClick={() => setAdditionalConditions((current) => [...current, ''])}>+ Добавить условие</button>}</div>
              {additionalConditions.map((condition, index) => <div className={styles.cardEditorConditionRow} key={index}>
                <input aria-label={`Дополнительное условие ${index + 1}`} value={condition} maxLength={200} readOnly={!canEdit} placeholder="Например: запах дыма на лестничной клетке" onChange={(event) => setAdditionalConditions((current) => current.map((value, position) => position === index ? event.target.value : value))} />
                {canEdit && <button type="button" aria-label={`Удалить условие ${index + 1}`} disabled={busy} onClick={() => setAdditionalConditions((current) => current.filter((_, position) => position !== index))}>Удалить</button>}
              </div>)}
              {canEdit && conditionsChanged && <div className={styles.cardEditorSectionActions}><button type="button" className={styles.cardEditorPrimary} disabled={busy} onClick={saveAdditionalConditions}>Сохранить и обновить текст</button></div>}
            </div>
          </section>
          <section className={styles.cardEditorSection}>
            <div className={styles.cardEditorSectionHeader}>
              <h4>Текст карточки</h4>
            </div>
            <textarea aria-label="Текст карточки" value={text} readOnly={!canEdit} onChange={(event) => setText(event.target.value)} />
            {canEdit && <div className={styles.cardEditorSectionActions}>
              <button type="button" className={styles.cardEditorPrimary} disabled={busy || conditionsChanged || !text.trim() || !textChanged} title={conditionsChanged ? 'Сначала сохраните дополнительные условия' : ''} onClick={() => perform(`${path}/initial-message`, json('PATCH', { text }), 'Текст сохранён')}>Сохранить текст</button>
              <button type="button" disabled={busy || conditionsChanged || textChanged} onClick={() => perform(`${path}/rerender-initial-message`, { method: 'POST' }, 'Текст перегенерирован', false, 'ИИ перегенерирует текст карточки…')}>Перегенерировать текст</button>
            </div>}
          </section>
          <footer className={styles.cardEditorFooter}>
            {editable && <button type="button" className={styles.cardEditorLibrary} disabled={busy || textChanged || conditionsChanged} title={textChanged || conditionsChanged ? 'Сначала сохраните изменения карточки' : ''} onClick={() => perform(`/api/incident-cards/from-instance/${selected.id}`, { method: 'POST' }, 'Карточка сохранена в библиотеку')}>Сохранить в библиотеку</button>}
            {canEdit && <div className={styles.cardEditorOtherActions}>
              <button type="button" disabled={busy || conditionsChanged || textChanged} onClick={() => perform(`${path}/regenerate-card`, { method: 'POST' }, 'Карточка перегенерирована', false, 'ИИ перегенерирует карточку…')}>Перегенерировать карточку</button>
              <button type="button" className={styles.cardEditorDanger} disabled={busy} onClick={() => perform(path, { method: 'DELETE' }, 'Карточка исключена', true)}>Исключить</button>
            </div>}
          </footer>
          <p className={styles.cardEditorHint}>Работа служб формируется автоматически во время занятия.</p>
        </div>
      </section>
    </div>}
  </article>
}
