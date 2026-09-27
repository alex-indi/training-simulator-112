/* eslint-disable react/prop-types */
import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { factNames } from './cardVariantFacts'
import styles from './ScenarioLibrary.module.css'
import editorStyles from './InstructorWorkspace.module.css'
import StatusMessage from './StatusMessage.jsx'

const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const searchable = (value) => String(value || '').toLocaleLowerCase('ru').replaceAll('ё', 'е')

export default function SavedIncidentCards({ user, requestJson, sessionId, groupId, onCompleted, picker = false, embedded = false }) {
  const api = useCallback((path, options) => requestJson(path, user.username, options), [requestJson, user.username])
  const [cards, setCards] = useState([])
  const [packages, setPackages] = useState([])
  const [activeTab, setActiveTab] = useState('cards')
  const [packageDraft, setPackageDraft] = useState(null)
  const [templateFilter, setTemplateFilter] = useState('all')
  const [usedIds, setUsedIds] = useState(new Set())
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState([])
  const [openedId, setOpenedId] = useState(null)
  const [facts, setFacts] = useState({})
  const [text, setText] = useState('')
  const [additionalConditions, setAdditionalConditions] = useState([])
  const [busy, setBusy] = useState(false)
  const [generationStatus, setGenerationStatus] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const reload = useCallback(async () => {
    const [saved, savedPackages, instances] = await Promise.all([
      api('/api/incident-cards'),
      api('/api/incident-cards/packages'),
      picker ? api(`/api/training/sessions/${sessionId}/scenario-instances`) : Promise.resolve([]),
    ])
    setCards(saved)
    setPackages(savedPackages)
    const assigned = new Set(saved.filter((card) => instances.some((item) =>
      item.training_group_id === Number(groupId) && (
        item.template_snapshot?.source_saved_card_id === card.id || (
          item.scenario_template_id === card.source_template_id
          && JSON.stringify(item.object_snapshot) === JSON.stringify(card.object_snapshot)
          && JSON.stringify(item.initial_state_snapshot) === JSON.stringify(card.initial_state_snapshot)
        )
      )
    )).map((card) => card.id))
    setUsedIds(assigned)
    setSelected((current) => current.filter((id) => !assigned.has(id)))
  }, [api, groupId, picker, sessionId])
  useEffect(() => { reload().catch((cause) => setError(cause.message)) }, [reload])

  const openedCard = cards.find((card) => card.id === openedId)
  const canEditOpened = openedCard && (user.role === 'ADMIN' || openedCard.created_by_user_id === user.id)
  const variantOptions = openedCard?.template_snapshot.variant_options || {}
  const savedConditions = openedCard?.initial_state_snapshot.additional_conditions || []
  const cleanedConditions = additionalConditions.map((value) => value.trim()).filter(Boolean)
  const conditionsChanged = JSON.stringify(cleanedConditions) !== JSON.stringify(savedConditions)
  const factsChanged = Object.keys(variantOptions).some((key) => facts[key] !== openedCard?.initial_state_snapshot.variant_facts?.[key])
  const textChanged = text !== (openedCard?.initial_state_snapshot.render?.rendered_text || '')
  useEffect(() => {
    setText(openedCard?.initial_state_snapshot.render?.rendered_text || '')
    setFacts(openedCard?.initial_state_snapshot.variant_facts || {})
    setAdditionalConditions(openedCard?.initial_state_snapshot.additional_conditions || [])
  }, [openedCard])
  const terms = searchable(search).trim().split(/\s+/).filter(Boolean)
  const visibleCards = cards.filter((card) => {
    const content = searchable([
      card.name,
      card.classifier_snapshot?.final_incident_type,
      card.object_snapshot?.name,
      card.object_snapshot?.address,
      card.initial_state_snapshot?.render?.rendered_text,
    ].join(' '))
    return terms.every((term) => content.includes(term))
  })
  const selectableVisibleCards = visibleCards.filter((card) => !usedIds.has(card.id))
  const allVisibleSelected = selectableVisibleCards.length > 0
    && selectableVisibleCards.every((card) => selected.includes(card.id))
  const templates = [...new Map(cards.map((card) => [
    String(card.source_template_id ?? 'none'),
    card.template_snapshot?.name || 'Без шаблона',
  ])).entries()]
  const packageCandidates = cards.filter((card) =>
    templateFilter === 'all' || String(card.source_template_id ?? 'none') === templateFilter
  )

  useEffect(() => {
    if (!openedId) return undefined
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setOpenedId(null)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [openedId])

  const perform = async (action, status = '') => {
    setBusy(true); setGenerationStatus(status); setError(''); setNotice('')
    try { await action() } catch (cause) { setError(cause.message) } finally { setBusy(false); setGenerationStatus('') }
  }
  const toggleSelected = (id) => setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])
  const openCard = (card) => {
    setOpenedId(card.id)
    setError('')
    setNotice('')
  }
  const saveText = (card) => perform(async () => {
    await api(`/api/incident-cards/${card.id}/text`, json('PATCH', { text }))
    await reload(); setNotice('Текст сохранён')
  })
  const saveFacts = (card) => perform(async () => {
    await api(`/api/incident-cards/${card.id}/facts`, json('PATCH', { facts }))
    await reload(); setNotice('Условия и текст карточки обновлены')
  }, 'ИИ обновляет текст карточки…')
  const saveAdditionalConditions = (card) => {
    if ((textChanged || factsChanged || card.initial_state_snapshot.render?.render_origin === 'MANUAL')
      && !window.confirm('Сохранение дополнительных условий заменит текущий текст и несохранённые правки карточки. Продолжить?')) return
    perform(async () => {
      await api(`/api/incident-cards/${card.id}/additional-conditions`, json('PATCH', { conditions: cleanedConditions }))
      await reload(); setNotice('Условия сохранены, текст обновлён')
    }, 'ИИ обновляет текст карточки…')
  }
  const rerenderText = (card) => {
    if (text !== card.initial_state_snapshot.render?.rendered_text && !window.confirm('Несохранённые правки текста будут заменены. Продолжить?')) return
    perform(async () => {
      const updated = await api(`/api/incident-cards/${card.id}/rerender-text`, { method: 'POST' })
      setText(updated.initial_state_snapshot.render.rendered_text)
      await reload()
      setNotice('Текст карточки перегенерирован')
    }, 'ИИ перегенерирует текст карточки…')
  }
  const remove = (card) => {
    if (!window.confirm(`Удалить карточку «${card.name}»?`)) return
    perform(async () => {
      await api(`/api/incident-cards/${card.id}`, { method: 'DELETE' })
      await reload()
      setOpenedId(null)
      setSelected((current) => current.filter((id) => id !== card.id))
      setNotice('Карточка удалена')
    })
  }
  const add = () => perform(async () => {
    for (const id of selected) await api(`/api/incident-cards/${id}/add-to-group`, json('POST', { session_id: sessionId, group_id: groupId }))
    setNotice(`Добавлено ${selected.length} карточек`); setSelected([]); onCompleted?.()
  })
  const startPackage = (item = null) => {
    setPackageDraft(item ? {
      id: item.id, name: item.name, description: item.description,
      card_ids: [...item.card_ids],
    } : { name: '', description: '', card_ids: [] })
    setTemplateFilter('all')
    setActiveTab('packages')
    setError('')
  }
  const togglePackageCard = (id) => setPackageDraft((current) => ({
    ...current,
    card_ids: current.card_ids.includes(id)
      ? current.card_ids.filter((item) => item !== id)
      : [...current.card_ids, id],
  }))
  const savePackage = () => perform(async () => {
    const path = packageDraft.id ? `/api/incident-cards/packages/${packageDraft.id}` : '/api/incident-cards/packages'
    await api(path, json(packageDraft.id ? 'PATCH' : 'POST', packageDraft))
    await reload()
    setPackageDraft(null)
    setNotice('Пакет сохранён')
  })
  const removePackage = (item) => {
    if (!window.confirm(`Удалить пакет «${item.name}»? Карточки останутся в библиотеке.`)) return
    perform(async () => {
      await api(`/api/incident-cards/packages/${item.id}`, { method: 'DELETE' })
      await reload()
      setNotice('Пакет удалён')
    })
  }
  const addPackage = (item) => perform(async () => {
    const result = await api(`/api/incident-cards/packages/${item.id}/add-to-group`, json('POST', { session_id: sessionId, group_id: groupId }))
    setNotice(`Добавлено ${result.added_count} карточек`)
    onCompleted?.()
  })

  return <main className={`${styles.shell} ${embedded ? styles.embedded : ''}`}><div className={styles.content}>
    <div className={styles.savedLibraryToolbar}>
      <div><h2>Библиотека карточек</h2><p>Карточки и пакеты можно использовать в разных занятиях.</p></div>
      {activeTab === 'cards' && <div className={styles.savedLibraryControls}>
        <label className={styles.savedSearch}>Поиск карточки
          <span><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Название, объект, тип или адрес" />{search && <button type="button" onClick={() => setSearch('')} aria-label="Очистить поиск">×</button>}</span>
        </label>
        {picker && <button type="button" className={styles.savedAddButton} disabled={busy || !selected.length} onClick={add}>Добавить выбранные ({selected.length})</button>}
      </div>}
      <div className={styles.savedTabs} role="tablist" aria-label="Разделы библиотеки">
        <button type="button" role="tab" aria-selected={activeTab === 'cards'} onClick={() => setActiveTab('cards')}>Карточки ({cards.length})</button>
        <button type="button" role="tab" aria-selected={activeTab === 'packages'} onClick={() => setActiveTab('packages')}>Пакеты ({packages.length})</button>
      </div>
      {activeTab === 'cards' && <div className={styles.savedSelectionBar}>
        <small>Показано {visibleCards.length} из {cards.length}</small>
        {picker && !!selectableVisibleCards.length && <label>
          <input type="checkbox" checked={allVisibleSelected} onChange={(event) => {
            const visibleIds = new Set(selectableVisibleCards.map((card) => card.id))
            setSelected((current) => event.target.checked
              ? [...new Set([...current, ...visibleIds])]
              : current.filter((id) => !visibleIds.has(id)))
          }} />
          <span>Выбрать все показанные</span>
        </label>}
      </div>}
    </div>
    {!openedCard && <StatusMessage message={error} tone="error" />}
    {!openedCard && <StatusMessage message={notice} tone="success" />}
    {activeTab === 'cards' && <><div className={styles.savedCardGrid}>{visibleCards.map((card) => {
      const isSelected = selected.includes(card.id)
      const summary = <><strong>{card.name}</strong><small>{card.classifier_snapshot.final_incident_type}</small></>
      const isUsed = usedIds.has(card.id)
      return <article className={`${styles.savedCard} ${isSelected ? styles.savedCardSelected : ''} ${isUsed ? styles.savedCardUsed : ''}`} key={card.id}>
        {picker ? <label className={styles.savedCardMain}>
          <input type="checkbox" checked={isSelected} disabled={isUsed} onChange={() => toggleSelected(card.id)} aria-label={isUsed ? `Карточка уже добавлена: ${card.name}` : `Выбрать карточку: ${card.name}`} />
          <span className={styles.savedCardSummary}>{summary}{isUsed && <small>Уже добавлена в группу</small>}</span>
        </label> : <div className={styles.savedCardMain}><span className={styles.savedCardSummary}>{summary}</span></div>}
        <button type="button" className={styles.savedPreviewButton} onClick={() => openCard(card)}>{user.role === 'ADMIN' || card.created_by_user_id === user.id ? 'Предпросмотр и редактирование' : 'Предпросмотр карточки'}</button>
      </article>
    })}</div>
    {!cards.length && <p>Сохранённых карточек пока нет.</p>}
    {!!cards.length && !visibleCards.length && <p>По запросу ничего не найдено.</p>}</>}
    {activeTab === 'packages' && <section className={styles.savedPackages}>
      {!picker && !packageDraft && <button type="button" className={styles.savedAddButton} onClick={() => startPackage()}>+ Создать пакет</button>}
      {packageDraft && <div className={styles.savedPackageEditor}>
        <h3>{packageDraft.id ? 'Изменить пакет' : 'Новый пакет'}</h3>
        <label>Название пакета<input value={packageDraft.name} maxLength={160} onChange={(event) => setPackageDraft((current) => ({ ...current, name: event.target.value }))} placeholder="Например: Пожар в школе" /></label>
        <label>Описание (необязательно)<input value={packageDraft.description} maxLength={500} onChange={(event) => setPackageDraft((current) => ({ ...current, description: event.target.value }))} placeholder="Для какого занятия или темы" /></label>
        <div className={styles.savedPackageSelectionHeader}>
          <label>Карточки по шаблону<select value={templateFilter} onChange={(event) => setTemplateFilter(event.target.value)}><option value="all">Все шаблоны</option>{templates.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
          <button type="button" onClick={() => setPackageDraft((current) => ({ ...current, card_ids: [...new Set([...current.card_ids, ...packageCandidates.map((card) => card.id)])] }))}>Выбрать показанные</button>
          <button type="button" onClick={() => { const shown = new Set(packageCandidates.map((card) => card.id)); setPackageDraft((current) => ({ ...current, card_ids: current.card_ids.filter((id) => !shown.has(id)) })) }}>Снять выбор</button>
        </div>
        <div className={styles.savedPackageChecklist}>{packageCandidates.map((card) => <label key={card.id}>
          <input type="checkbox" checked={packageDraft.card_ids.includes(card.id)} onChange={() => togglePackageCard(card.id)} />
          <span><strong>{card.name}</strong><small>{card.template_snapshot?.name || 'Без шаблона'} · {card.object_snapshot?.name}</small></span>
        </label>)}</div>
        <p>Выбрано карточек: {packageDraft.card_ids.length}</p>
        <div className={styles.savedPackageActions}><button type="button" className={styles.savedAddButton} disabled={busy || !packageDraft.name.trim() || !packageDraft.card_ids.length || packageDraft.card_ids.length > 100} onClick={savePackage}>Сохранить пакет</button><button type="button" disabled={busy} onClick={() => setPackageDraft(null)}>Отмена</button></div>
      </div>}
      {!packageDraft && <div className={styles.savedPackageGrid}>{packages.map((item) => {
        const members = item.card_ids.map((id) => cards.find((card) => card.id === id)).filter(Boolean)
        const available = members.filter((card) => !usedIds.has(card.id)).length
        const canEdit = user.role === 'ADMIN' || item.created_by_user_id === user.id
        return <article className={styles.savedPackage} key={item.id}>
          <h3>{item.name}</h3>
          {item.description && <p>{item.description}</p>}
          <small>{members.length} карточек{picker && available !== members.length ? ` · новых для группы: ${available}` : ''}</small>
          <ul>{members.slice(0, 5).map((card) => <li key={card.id}>{card.name}</li>)}{members.length > 5 && <li>И ещё {members.length - 5}</li>}</ul>
          <div className={styles.savedPackageActions}>
            {picker && <button type="button" className={styles.savedAddButton} disabled={busy || !available} onClick={() => addPackage(item)}>Добавить пакет</button>}
            {!picker && canEdit && <><button type="button" onClick={() => startPackage(item)}>Изменить</button><button type="button" disabled={busy} onClick={() => removePackage(item)}>Удалить</button></>}
          </div>
        </article>
      })}</div>}
      {!packageDraft && !packages.length && <p>Пакетов пока нет. Создайте пакет из карточек библиотеки.</p>}
    </section>}
  </div>
  {openedCard && createPortal(<div className={`${editorStyles.shell} ${editorStyles.pickerOverlay}`} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpenedId(null) }}>
    <section className={`${editorStyles.pickerDialog} ${editorStyles.cardEditorDialog}`} role="dialog" aria-modal="true" aria-labelledby={`saved-card-${openedCard.id}`}>
      <header className={editorStyles.cardEditorHeader}>
        <div><small>Библиотека карточек</small><h3 id={`saved-card-${openedCard.id}`}>{openedCard.template_snapshot.name || openedCard.name}</h3></div>
        <button type="button" autoFocus onClick={() => setOpenedId(null)}>Закрыть</button>
      </header>
      <StatusMessage message={error} tone="error" />
      <StatusMessage message={notice} tone="success" />
      <StatusMessage message={generationStatus} />
      <div className={editorStyles.cardEditorBody}>
        <div className={editorStyles.cardEditorClassification}>
          <span>Классификация</span>
          <strong>{openedCard.classifier_snapshot.incident_group || openedCard.classifier_snapshot.final_incident_type}</strong>
          {openedCard.classifier_snapshot.final_incident_type !== openedCard.classifier_snapshot.incident_group && <small>Вид происшествия: {openedCard.classifier_snapshot.final_incident_type}</small>}
        </div>
        <div className={editorStyles.cardEditorMeta}>
          <p><b>Объект</b><span>{openedCard.object_snapshot.name}</span></p>
          <p><b>Адрес</b><span>{openedCard.object_snapshot.address}</span></p>
        </div>
        <section className={editorStyles.cardEditorSection}>
          <div className={editorStyles.cardEditorSectionHeader}><h4>Условия</h4></div>
          <p className={editorStyles.cardEditorHint}>Учебные варианты заданы шаблоном; классификация взята из справочника.</p>
          {canEditOpened && !!Object.keys(variantOptions).length ? <>
            <div className={editorStyles.cardEditorFacts}>{Object.entries(variantOptions).map(([key, choices]) => <label key={key}>{factNames[key] || key}<select value={facts[key] ?? ''} onChange={(event) => setFacts((current) => ({ ...current, [key]: key === 'floor' ? Number(event.target.value) : event.target.value }))}>{choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}</select></label>)}</div>
            <div className={editorStyles.cardEditorSectionActions}><button type="button" className={editorStyles.cardEditorPrimary} disabled={busy || conditionsChanged || !factsChanged} title={conditionsChanged ? 'Сначала сохраните дополнительные условия' : ''} onClick={() => saveFacts(openedCard)}>Сохранить условия</button></div>
          </> : <p>{Object.entries(openedCard.initial_state_snapshot.variant_facts || {}).map(([key, value]) => `${factNames[key] || key}: ${value}`).join(' · ') || 'Без дополнительных условий'}</p>}
          <div className={editorStyles.cardEditorAdditional}>
            <div className={editorStyles.cardEditorAdditionalHeader}><div><h5>Дополнительные условия</h5><small>Учитываются при формировании текста карточки.</small></div>{canEditOpened && <button type="button" disabled={busy || additionalConditions.length >= 8} onClick={() => setAdditionalConditions((current) => [...current, ''])}>+ Добавить условие</button>}</div>
            {additionalConditions.map((condition, index) => <div className={editorStyles.cardEditorConditionRow} key={index}>
              <input aria-label={`Дополнительное условие ${index + 1}`} value={condition} maxLength={200} readOnly={!canEditOpened} placeholder="Например: запах дыма на лестничной клетке" onChange={(event) => setAdditionalConditions((current) => current.map((value, position) => position === index ? event.target.value : value))} />
              {canEditOpened && <button type="button" aria-label={`Удалить условие ${index + 1}`} disabled={busy} onClick={() => setAdditionalConditions((current) => current.filter((_, position) => position !== index))}>Удалить</button>}
            </div>)}
            {canEditOpened && conditionsChanged && <div className={editorStyles.cardEditorSectionActions}><button type="button" className={editorStyles.cardEditorPrimary} disabled={busy} onClick={() => saveAdditionalConditions(openedCard)}>Сохранить и обновить текст</button></div>}
          </div>
        </section>
        <section className={editorStyles.cardEditorSection}>
          <div className={editorStyles.cardEditorSectionHeader}><h4>Текст карточки</h4></div>
          <textarea aria-label="Текст карточки" value={text} readOnly={!canEditOpened} onChange={(event) => setText(event.target.value)} />
          {canEditOpened && <div className={editorStyles.cardEditorSectionActions}>
            <button type="button" className={editorStyles.cardEditorPrimary} disabled={busy || conditionsChanged || !text.trim() || !textChanged} title={conditionsChanged ? 'Сначала сохраните дополнительные условия' : ''} onClick={() => saveText(openedCard)}>Сохранить текст</button>
            <button type="button" disabled={busy || conditionsChanged || textChanged} onClick={() => rerenderText(openedCard)}>Перегенерировать текст</button>
          </div>}
        </section>
        {canEditOpened && !picker && <footer className={editorStyles.cardEditorFooter}><button type="button" className={editorStyles.cardEditorDanger} disabled={busy} onClick={() => remove(openedCard)}>Удалить</button></footer>}
        <p className={editorStyles.cardEditorHint}>Работа служб формируется автоматически во время занятия.</p>
      </div>
    </section>
  </div>, document.body)}
  </main>
}
