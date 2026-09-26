import { useCallback, useEffect, useMemo, useState } from 'react'
import PropTypes from 'prop-types'

import styles from './InstructorWorkspace.module.css'

const emptyDraft = { name: '', code: '', member_ids: [] }

export default function InstructorGroups({ api, compact = false, onCreated, onChanged }) {
  const [groups, setGroups] = useState([])
  const [trainees, setTrainees] = useState([])
  const [search, setSearch] = useState('')
  const [memberSearch, setMemberSearch] = useState('')
  const [memberSearchOpen, setMemberSearchOpen] = useState(false)
  const [archiveOpen, setArchiveOpen] = useState(false)
  const [draft, setDraft] = useState(null)
  const [editingId, setEditingId] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const closeDraft = useCallback(() => {
    setDraft(null)
    setEditingId(null)
    setMemberSearch('')
    setMemberSearchOpen(false)
  }, [])

  const reload = useCallback(async () => {
    const [saved, users] = await Promise.all([
      api('/api/training/user-groups'), api('/api/training/user-groups/trainees'),
    ])
    setGroups(saved)
    setTrainees(users)
    onChanged?.(saved)
  }, [api, onChanged])

  useEffect(() => { reload().catch((cause) => setError(cause.message)) }, [reload])

  useEffect(() => {
    if (!draft) return undefined

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') closeDraft()
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [closeDraft, draft])

  const visible = useMemo(() => groups.filter((group) =>
    group.is_archived === archiveOpen &&
    `${group.name} ${group.code || ''}`.toLocaleLowerCase('ru').includes(search.toLocaleLowerCase('ru')),
  ), [groups, archiveOpen, search])

  const startCreate = () => { setEditingId(null); setDraft(emptyDraft); setMemberSearch(''); setMemberSearchOpen(false); setError('') }
  const startEdit = (group) => {
    setEditingId(group.id)
    setDraft({ name: group.name, code: group.code || '', member_ids: group.members.map((member) => member.id) })
    setMemberSearch('')
    setMemberSearchOpen(false)
    setError('')
  }
  const save = async () => {
    setBusy(true)
    setError('')
    try {
      const saved = await api(`/api/training/user-groups${editingId ? `/${editingId}` : ''}`, {
        method: editingId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(draft),
      })
      await reload()
      closeDraft()
      if (!editingId) onCreated?.(saved)
    } catch (cause) { setError(cause.message) } finally { setBusy(false) }
  }
  const archive = async (group) => {
    setBusy(true)
    setError('')
    try {
      await api(`/api/training/user-groups/${group.id}/archive`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_archived: !group.is_archived }),
      })
      await reload()
    } catch (cause) { setError(cause.message) } finally { setBusy(false) }
  }
  const toggleMember = (id) => setDraft((current) => ({
    ...current,
    member_ids: current.member_ids.includes(id)
      ? current.member_ids.filter((memberId) => memberId !== id)
      : [...current.member_ids, id],
  }))

  const normalizedMemberSearch = memberSearch.trim().toLocaleLowerCase('ru')
  const memberSuggestions = draft && normalizedMemberSearch
    ? trainees.filter((trainee) => trainee.full_name.toLocaleLowerCase('ru').includes(normalizedMemberSearch)).slice(0, 8)
    : []

  return <section className={styles.section}>
    <div className={styles.topline}><div><h2>{compact ? 'Новая постоянная группа' : 'Группы обучающихся'}</h2><p>Постоянный состав доступен для будущих занятий.</p></div>
      <button type="button" onClick={startCreate}>{compact ? '+ Создать новую группу' : '+ Создать группу'}</button></div>
    {error && <p className={styles.error} role="alert">{error}</p>}
    {!compact && <div className={styles.groupFilters}>
      <input aria-label="Поиск группы" placeholder="Поиск по названию или коду" value={search} onChange={(event) => setSearch(event.target.value)} />
      <label><input type="checkbox" checked={archiveOpen} onChange={(event) => setArchiveOpen(event.target.checked)} /> Показать архив</label>
    </div>}
    {!compact && <div className={styles.itemList}>{visible.map((group) => <article key={group.id} className={`${styles.itemRow} ${styles.groupRow}`}>
      <strong>{group.code || group.name}</strong><span>{group.name}</span><small>{group.member_count} человек</small>
      <div>{group.members.map((member) => member.full_name).join(', ') || 'Участники не выбраны'}</div>
      <div className={styles.actions}><button type="button" onClick={() => startEdit(group)} disabled={busy || group.is_archived}>Открыть</button>
        <button type="button" onClick={() => archive(group)} disabled={busy}>{group.is_archived ? 'Восстановить' : 'Архивировать'}</button></div>
    </article>)}</div>}
    {!compact && !visible.length && <p>Групп пока нет.</p>}
    {draft && <div className={styles.groupOverlay} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeDraft() }}>
      <div className={styles.groupDialog} role="dialog" aria-modal="true" aria-label={editingId ? 'Изменить группу' : 'Создать группу'}>
        <h3>{editingId ? 'Изменить группу' : 'Новая группа'}</h3>
        <label>Название<input value={draft.name} maxLength={160} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} /></label>
        <label>Короткий код<input value={draft.code} maxLength={40} onChange={(event) => setDraft((current) => ({ ...current, code: event.target.value }))} /></label>
        <div className={styles.memberSearch}>
          <label>Участники<input placeholder="Поиск по ФИО" value={memberSearch} role="combobox" aria-autocomplete="list" aria-controls="member-suggestions" aria-expanded={memberSearchOpen && !!normalizedMemberSearch} onFocus={() => setMemberSearchOpen(true)} onBlur={() => setMemberSearchOpen(false)} onChange={(event) => { setMemberSearch(event.target.value); setMemberSearchOpen(true) }} /></label>
          {memberSearchOpen && normalizedMemberSearch && <div className={styles.memberSuggestions} id="member-suggestions" role="listbox">
            {memberSuggestions.map((trainee) => {
              const selected = draft.member_ids.includes(trainee.id)
              const unavailable = selected || (!!trainee.group_id && trainee.group_id !== editingId)
              return <button key={trainee.id} type="button" role="option" aria-selected="false" disabled={unavailable} onMouseDown={(event) => event.preventDefault()} onClick={() => { toggleMember(trainee.id); setMemberSearch(''); setMemberSearchOpen(false) }}>
                <span>{trainee.full_name}</span>{selected ? <small>Уже выбран</small> : unavailable && <small>Уже в другой группе</small>}
              </button>
            })}
            {!memberSuggestions.length && <span className={styles.noSuggestions}>Совпадений не найдено</span>}
          </div>}
        </div>
        <div className={styles.memberList}>{trainees.filter((trainee) => draft.member_ids.includes(trainee.id)).map((trainee) => <label key={trainee.id}>
          <input type="checkbox" checked onChange={() => toggleMember(trainee.id)} /> {trainee.full_name}
        </label>)}
          {!draft.member_ids.length && <p>Участники не выбраны.</p>}
        </div>
        <div className={styles.actions}><button type="button" disabled={busy || !draft.name.trim() || !draft.code.trim()} onClick={save}>{compact ? 'Создать и добавить в занятие' : editingId ? 'Сохранить' : 'Создать'}</button>
          <button type="button" onClick={closeDraft}>Отмена</button></div>
      </div>
    </div>}
  </section>
}

InstructorGroups.propTypes = {
  api: PropTypes.func.isRequired,
  compact: PropTypes.bool,
  onCreated: PropTypes.func,
  onChanged: PropTypes.func,
}
