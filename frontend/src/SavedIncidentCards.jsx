/* eslint-disable react/prop-types */
import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import styles from './ScenarioLibrary.module.css'

const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const factNames = { floor: 'Этаж', room: 'Место', observation: 'Задымление', casualties: 'Пострадавшие' }
const searchable = (value) => String(value || '').toLocaleLowerCase('ru').replaceAll('ё', 'е')

export default function SavedIncidentCards({ user, requestJson, sessionId, groupId, onCompleted, picker = false }) {
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
  const [editingId, setEditingId] = useState(null)
  const [editingFactsId, setEditingFactsId] = useState(null)
  const [facts, setFacts] = useState({})
  const [text, setText] = useState('')
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
    setEditingId(null)
    setEditingFactsId(null)
    setError('')
    setNotice('')
  }
  const saveText = (card) => perform(async () => {
    await api(`/api/incident-cards/${card.id}/text`, json('PATCH', { text }))
    await reload(); setEditingId(null); setNotice('Текст сохранён')
  })
  const saveFacts = (card) => perform(async () => {
    await api(`/api/incident-cards/${card.id}/facts`, json('PATCH', { facts }))
    await reload(); setEditingFactsId(null); setNotice('Условия и текст карточки обновлены')
  }, 'ИИ обновляет текст карточки…')
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

  return <main className={styles.shell}><div className={styles.content}>
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
      {activeTab === 'cards' && <small>Показано {visibleCards.length} из {cards.length}</small>}
    </div>
    {!openedCard && error && <p className={styles.error} role="alert">{error}</p>}
    {!openedCard && notice && <p className={styles.notice} role="status">{notice}</p>}
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
  {openedCard && createPortal(<div className={styles.savedPreviewOverlay} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpenedId(null) }}>
    <section className={styles.savedPreviewDialog} role="dialog" aria-modal="true" aria-labelledby={`saved-card-${openedCard.id}`}>
      <header className={styles.savedPreviewHeader}><h2 id={`saved-card-${openedCard.id}`}>{openedCard.name}</h2><button type="button" autoFocus onClick={() => setOpenedId(null)}>Закрыть</button></header>
      {error && <p className={styles.error} role="alert">{error}</p>}
      {notice && <p className={styles.notice} role="status">{notice}</p>}
      {generationStatus && <p className={styles.generationStatus} role="status">{generationStatus}</p>}
      <div className={styles.savedPreviewBody}>
        <p><b>Тип:</b> {openedCard.classifier_snapshot.final_incident_type}</p>
        <p><b>Объект:</b> {openedCard.object_snapshot.name}</p>
        <p><b>Адрес:</b> {openedCard.object_snapshot.address}</p>
        <p><b>Условия:</b> {Object.entries(openedCard.initial_state_snapshot.variant_facts || {}).map(([key, value]) => `${factNames[key] || key}: ${value}`).join(' · ') || 'Без дополнительных условий'}</p>
        {editingFactsId === openedCard.id && <div className={styles.savedEditFacts}>{Object.entries(openedCard.template_snapshot.variant_options || {}).map(([key, values]) => <label key={key}>{factNames[key] || key}<select value={facts[key] ?? ''} onChange={(event) => setFacts((current) => ({ ...current, [key]: key === 'floor' ? Number(event.target.value) : event.target.value }))}>{values.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>)}<div className={styles.savedEditActions}><button type="button" disabled={busy} onClick={() => saveFacts(openedCard)}>Сохранить условия</button><button type="button" onClick={() => setEditingFactsId(null)}>Отмена</button></div></div>}
        <div className={styles.savedCardText}><b>Текст карточки</b>{editingId === openedCard.id ? <><textarea value={text} onChange={(event) => setText(event.target.value)} /><div className={styles.savedEditActions}><button type="button" disabled={busy || !text.trim()} onClick={() => saveText(openedCard)}>Сохранить текст</button><button type="button" disabled={busy} onClick={() => rerenderText(openedCard)}>Перегенерировать текст</button><button type="button" onClick={() => setEditingId(null)}>Отмена</button></div></> : <p>{openedCard.initial_state_snapshot.render?.rendered_text}</p>}</div>
        <div><b>Службы по классификатору</b><ul>{openedCard.service_snapshot.map((service) => <li key={service.service_id}>{service.official_name}</li>)}</ul></div>
        {canEditOpened && <div className={styles.savedEditActions}>
          <button type="button" onClick={() => { setEditingId(openedCard.id); setEditingFactsId(null); setText(openedCard.initial_state_snapshot.render?.rendered_text || '') }}>Редактировать текст</button>
          {!!Object.keys(openedCard.template_snapshot.variant_options || {}).length && <button type="button" onClick={() => { setEditingFactsId(openedCard.id); setEditingId(null); setFacts(openedCard.initial_state_snapshot.variant_facts || {}) }}>Изменить условия</button>}
          {!picker && <button type="button" disabled={busy} onClick={() => remove(openedCard)}>Удалить</button>}
        </div>}
      </div>
    </section>
  </div>, document.body)}
  </main>
}
