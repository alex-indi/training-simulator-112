/* eslint-disable react/prop-types */
import { useCallback, useEffect, useState } from 'react'
import styles from './ScenarioLibrary.module.css'
import { difficultyLabels, renderOriginLabels } from './uiLabels.js'
import IncidentTemplates from './IncidentTemplates.jsx'

const options = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const variantFactLabels = { floor: 'Этаж', room: 'Помещение', observation: 'Обстановка', casualties: 'Пострадавшие' }

export default function ScenarioLibrary({ user, requestJson, onBack, sessionId, groupId, groupDifficulty, initialTemplate = null, onCompleted, embedded = false, picker = false }) {
  const api = useCallback((path, init) => requestJson(path, user.username, init), [requestJson, user.username])
  const [templates, setTemplates] = useState([])
  const [sessions, setSessions] = useState([])
  const [catalog, setCatalog] = useState({ services: [], object_types: [] })
  const [chosen, setChosen] = useState(initialTemplate)
  const [search, setSearch] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)
  const [selectedSessionId, setSelectedSessionId] = useState(sessionId || '')
  const [count, setCount] = useState(5)
  const [distinctObjects, setDistinctObjects] = useState(true)
  const [target, setTarget] = useState(picker ? `group:${groupId}` : '')
  const [cards, setCards] = useState([])
  const [saveSelected, setSaveSelected] = useState([])
  const [savedIds, setSavedIds] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [editedText, setEditedText] = useState('')
  const [variantDraft, setVariantDraft] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    Promise.all([
      api('/api/scenario-templates/simple'),
      picker ? Promise.resolve([]) : api('/api/training/sessions'),
      api('/api/scenario-templates/catalog'),
    ]).then(([library, available, names]) => {
      setTemplates(library.filter((item) => item.usable))
      setSessions(available.filter((item) => ['DRAFT', 'READY'].includes(item.state)))
      setCatalog(names)
    }).catch((cause) => setError(cause.message))
  }, [api, picker])

  useEffect(() => {
    if (!chosen?.id || !selectedSessionId || picker) return undefined
    let active = true
    api(`/api/training/sessions/${selectedSessionId}/scenario-instances`)
      .then((instances) => {
        if (!active) return
        const drafts = instances.filter((item) => item.scenario_template_id === chosen.id && item.status === 'DRAFT')
        const latestBatch = drafts.at(-1)?.template_snapshot?.batch_seed
        const currentBatch = drafts.filter((item) => item.template_snapshot?.batch_seed === latestBatch)
        setCards(currentBatch)
        setSelectedId(currentBatch[0]?.id || null)
      }).catch((cause) => { if (active) setError(cause.message) })
    return () => { active = false }
  }, [api, chosen?.id, picker, selectedSessionId])

  const session = sessions.find((item) => item.id === Number(selectedSessionId))
  const selected = cards.find((item) => item.id === selectedId) || cards[0]
  const targets = session && !picker ? [
    ...session.groups.filter((group) => group.queue_mode === 'SHARED_QUEUE' && group.run_ids.length)
      .map((group) => ({ value: `group:${group.id}`, label: `Общий пул · ${group.name}` })),
    ...session.runs.filter((run) => run.queue_mode === 'INDIVIDUAL_QUEUE')
      .map((run) => ({ value: `run:${run.id}`, label: `Персонально · АРМ ${run.workstation_number}` })),
  ] : []

  useEffect(() => {
    setEditedText(selected?.initial_state_snapshot?.render?.rendered_text || '')
  }, [selectedId, selected?.initial_state_snapshot?.render?.rendered_text])

  useEffect(() => {
    setVariantDraft(selected?.initial_state_snapshot?.variant_facts || {})
  }, [selectedId, selected?.initial_state_snapshot?.variant_facts])

  const perform = async (action) => {
    setBusy(true)
    setError('')
    setNotice('')
    try { await action() } catch (cause) { setError(cause.message) } finally { setBusy(false) }
  }

  const updateCard = (updated) => setCards((current) => current.map((item) => item.id === updated.id ? updated : item))
  const hasManualEdits = cards.some((card) => card.initial_state_snapshot.render?.render_origin === 'MANUAL')
  const confirmOverwrite = () => !hasManualEdits || window.confirm('В наборе есть правки преподавателя. Заменить эти тексты?')

  const createBatch = () => perform(async () => {
    const generated = await api(`/api/scenario-templates/${chosen.id}/batch`, options('POST', {
      count: Number(count),
      seed: Math.floor(Math.random() * 2147483647),
      distinct_objects: distinctObjects,
      training_session_id: Number(selectedSessionId),
      training_group_id: groupId || null,
    }))
    setCards(generated)
    setSelectedId(generated[0]?.id)
    setSaveSelected([])
    setSavedIds([])
    setNotice(`Сформировано ${generated.length} карточек. Просмотрите их и добавьте в занятие.`)
  })

  const replaceBatch = () => {
    if (!confirmOverwrite() || !window.confirm('Пересоздать весь набор карточек?')) return
    perform(async () => {
      const generated = await api(`/api/scenario-templates/${chosen.id}/batch`, options('POST', {
        count: Number(count),
        seed: Math.floor(Math.random() * 2147483647),
        distinct_objects: distinctObjects,
        training_session_id: Number(selectedSessionId),
        training_group_id: groupId || null,
      }))
      for (const card of cards) await api(`/api/scenario-instances/${card.id}`, { method: 'DELETE' })
      setCards(generated)
      setSelectedId(generated[0]?.id)
      setSaveSelected([])
      setSavedIds([])
    })
  }

  const changeCard = (path, init) => perform(async () => updateCard(await api(path, init)))

  const saveVariantFacts = () => {
    if (selected.initial_state_snapshot.render?.render_origin === 'MANUAL'
      && !window.confirm('Изменение условий заменит вручную исправленный текст этой карточки. Продолжить?')) return
    changeCard(`/api/scenario-instances/${selected.id}/variant-facts`, options('PATCH', {
      ...variantDraft,
      ...(Object.hasOwn(variantDraft, 'floor') ? { floor: Number(variantDraft.floor) } : {}),
    }))
  }

  const rerenderAll = () => {
    if (!confirmOverwrite()) return
    perform(async () => {
      for (const card of cards) {
        updateCard(await api(`/api/scenario-instances/${card.id}/rerender-initial-message`, { method: 'POST' }))
      }
      setNotice('Тексты карточек обновлены; факты и объекты сохранены.')
    })
  }

  const exclude = () => perform(async () => {
    await api(`/api/scenario-instances/${selected.id}`, { method: 'DELETE' })
    const remaining = cards.filter((item) => item.id !== selected.id)
    setCards(remaining)
    setSelectedId(remaining[0]?.id || null)
    setSaveSelected((current) => current.filter((id) => id !== selected.id))
  })

  const approve = () => perform(async () => {
    if (picker) {
      await api(`/api/training/sessions/${selectedSessionId}/groups/${groupId}/cards/approve`, { method: 'POST' })
      onCompleted?.()
      return
    }
    const [kind, id] = target.split(':')
    await api(`/api/training/sessions/${selectedSessionId}/scenario-instances/confirm-batch`, options('POST', {
      instance_ids: cards.map((card) => card.id),
      [kind === 'group' ? 'training_group_id' : 'training_run_id']: Number(id),
    }))
    setCards([])
    setChosen(null)
    setNotice('Набор утверждён и добавлен в занятие.')
    onCompleted?.()
  })

  const saveCards = (ids) => perform(async () => {
    if (selected && ids.includes(selected.id) && editedText !== selected.initial_state_snapshot.render?.rendered_text) {
      if (!editedText.trim()) throw new Error('Заполните текст карточки перед сохранением')
      updateCard(await api(`/api/scenario-instances/${selected.id}/initial-message`, options('PATCH', { text: editedText })))
    }
    for (const id of ids) await api(`/api/incident-cards/from-instance/${id}`, { method: 'POST' })
    setSavedIds((current) => [...new Set([...current, ...ids])])
    setSaveSelected([])
    setNotice(`Сохранено в библиотеку: ${ids.length}`)
  })

  const serviceName = (id) => catalog.services.find((service) => service.id === id)?.name || 'Служба'
  const objectTypeName = (id) => catalog.object_types.find((item) => item.id === id)?.name || 'Подходящий объект'

  if (editorOpen) return <IncidentTemplates startCreate user={user} requestJson={requestJson} onSaved={(saved) => {
    setEditorOpen(false)
    setTemplates((current) => [saved, ...current])
    setChosen(saved)
    setCards([])
  }} />

  return <main className={`${styles.shell} ${embedded ? styles.embedded : ''}`}>
    {!embedded && <header className={styles.header}><div><small>Кабинет преподавателя</small><h1>Шаблоны инцидентов</h1></div><button type="button" onClick={onBack}>← К занятиям</button></header>}
    {error && <p className={styles.error} role="alert">{error}</p>}
    {notice && <p className={styles.notice} role="status">{notice}</p>}
    <div className={styles.content}>
      {!chosen && <>
        <div className={styles.topline}><div><h2>Выберите шаблон инцидента</h2><p>Карточки для занятия формируются из шаблона.</p></div></div>
        <label className={styles.search}>Поиск<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Название или тип происшествия" /></label>
        <div className={styles.cards}>{templates.filter((item) => `${item.name} ${item.incident_type || ''}`.toLocaleLowerCase().includes(search.toLocaleLowerCase())).map((item) => <button key={item.id} type="button" className={styles.card} onClick={() => { setCards([]); setChosen(item) }}>
          <h3>{item.name}</h3>
          <p>{item.incident_type}</p>
          <dl><div><dt>Сложность</dt><dd>{difficultyLabels[item.difficulty]}</dd></div><div><dt>Объекты</dt><dd>{objectTypeName(item.object_rule?.object_type_id)}</dd></div></dl>
          <small>Службы: {item.services.map((service) => serviceName(service.service_id)).join(', ') || 'По классификатору'}</small>
          <strong>Сформировать карточки →</strong>
        </button>)}</div>
        {!templates.length && <p>Шаблонов пока нет.</p>}
        <div className={styles.actions}><button type="button" onClick={() => setEditorOpen(true)}>+ Создать шаблон</button></div>
      </>}

      {chosen && <>
        <button type="button" className={styles.link} onClick={() => { setChosen(null); setCards([]) }}>← Библиотека</button>
        <h2>{chosen.name}</h2>
        {!cards.length && <section className={styles.panel}>
          <p>{chosen.description}</p>
          <div className={styles.batchForm}>
            {!picker && <label>Занятие<select value={selectedSessionId} onChange={(event) => { setSelectedSessionId(event.target.value); setTarget('') }}><option value="">Выберите занятие</option>{sessions.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>}
            <label>Количество карточек<input type="number" min="1" max="50" value={count} onChange={(event) => setCount(event.target.value)} /></label>
            {picker && groupDifficulty && <p>Сложность группы: {groupDifficulty}</p>}
            <label className={styles.inlineCheck}><input type="checkbox" checked={distinctObjects} onChange={(event) => setDistinctObjects(event.target.checked)} /> Использовать разные объекты</label>
          </div>
          {!picker && session && !targets.length && <p>Сначала создайте общую группу или назначьте АРМ в занятии.</p>}
          <button type="button" disabled={busy || (!picker && (!session || !targets.length)) || Number(count) < 1 || Number(count) > 50} onClick={createBatch}>Сформировать</button>
        </section>}

        {!!cards.length && <>
          <div className={styles.topline}><div><h3>Сформировано {cards.length} карточек</h3><p>Просмотрите весь набор перед запуском занятия.</p></div></div>
          <div className={styles.reviewLayout}>
            <nav className={styles.cardList} aria-label="Карточки набора">{cards.map((card, index) => <div key={card.id}>
              <label><input type="checkbox" checked={saveSelected.includes(card.id)} disabled={savedIds.includes(card.id)} onChange={(event) => setSaveSelected((current) => event.target.checked ? [...current, card.id] : current.filter((id) => id !== card.id))} /> Сохранить</label>
              <button type="button" className={card.id === selected?.id ? styles.selectedCard : ''} onClick={() => setSelectedId(card.id)}><b>{String(index + 1).padStart(2, '0')}</b><span>{card.object_snapshot.name}</span><small>{card.initial_state_snapshot.render?.render_origin === 'MANUAL' ? 'Изменена' : 'Готова'}</small></button>
            </div>)}</nav>

            {selected && <section className={styles.panel}>
              <h3>Карточка {cards.findIndex((item) => item.id === selected.id) + 1} из {cards.length}</h3>
              <p><b>Объект:</b> {selected.object_snapshot.name}</p>
              <p><b>Адрес:</b> {selected.object_snapshot.address}</p>
              <p><b>Район:</b> {selected.object_snapshot.district || '—'}</p>
              {!!Object.keys(selected.initial_state_snapshot.variant_facts || {}).length && <p><b>Условия:</b> {Object.values(selected.initial_state_snapshot.variant_facts).join(' · ')}</p>}
              {!!Object.keys(selected.template_snapshot.variant_options || {}).length && <details>
                <summary>Изменить условия карточки</summary>
                <div className={styles.batchForm}>{Object.entries(selected.template_snapshot.variant_options).map(([key, values]) => <label key={key}>{variantFactLabels[key] || key}<select aria-label={variantFactLabels[key] || key} value={variantDraft[key] ?? ''} onChange={(event) => setVariantDraft((current) => ({ ...current, [key]: key === 'floor' ? Number(event.target.value) : event.target.value }))}>{values.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>)}</div>
                <button type="button" disabled={busy || Object.keys(selected.template_snapshot.variant_options).every((key) => variantDraft[key] === selected.initial_state_snapshot.variant_facts[key])} onClick={saveVariantFacts}>Сохранить условия</button>
              </details>}
              <label>Карточка ДДС<textarea value={editedText} onChange={(event) => setEditedText(event.target.value)} /></label>
              <small>{renderOriginLabels[selected.initial_state_snapshot.render?.render_origin] || 'Текст подготовлен'}</small>
              <div className={styles.actions}>
                <button type="button" disabled={busy || !editedText.trim() || editedText === selected.initial_state_snapshot.render?.rendered_text} onClick={() => changeCard(`/api/scenario-instances/${selected.id}/initial-message`, options('PATCH', { text: editedText }))}>Сохранить текст</button>
                <button type="button" disabled={busy} onClick={() => changeCard(`/api/scenario-instances/${selected.id}/rerender-initial-message`, { method: 'POST' })}>Перегенерировать текст</button>
                <button type="button" disabled={busy} onClick={() => changeCard(`/api/scenario-instances/${selected.id}/regenerate-card`, { method: 'POST' })}>Перегенерировать карточку</button>
                <button type="button" disabled={busy || savedIds.includes(selected.id)} onClick={() => saveCards([selected.id])}>Сохранить в библиотеку</button>
                <button type="button" disabled={busy} onClick={exclude}>Удалить неудачную</button>
              </div>
              <p>Работа служб формируется автоматически во время занятия и не настраивается в карточке.</p>
            </section>}
          </div>

          <section className={styles.panel}>
            <h3>Подготовленные карточки</h3>
            {!picker && <label>Распределение<select value={target} onChange={(event) => setTarget(event.target.value)}><option value="">Выберите общий пул или АРМ</option>{targets.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>}
            <div className={styles.actions}>
              <button type="button" disabled={busy || !saveSelected.length} onClick={() => saveCards(saveSelected)}>Сохранить выбранные</button>
              <button type="button" disabled={busy} onClick={rerenderAll}>Перегенерировать тексты всех карточек</button>
              <button type="button" disabled={busy} onClick={replaceBatch}>Пересоздать весь набор</button>
              <button type="button" disabled={busy || !target} onClick={approve}>Добавить в занятие</button>
            </div>
          </section>
        </>}
      </>}
    </div>
  </main>
}
