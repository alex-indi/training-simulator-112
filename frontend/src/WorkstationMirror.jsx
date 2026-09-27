/* eslint-disable react/prop-types */
import { useState } from 'react'

import styles from './WorkstationMirror.module.css'
import { ddsStatusLabels, incidentHistoryLabels, incidentSourceLabels, responseSenderLabels, responseStateLabels } from './uiLabels.js'

function time(value) {
  return value ? new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'short', timeStyle: 'medium', timeZone: 'Europe/Moscow',
  }).format(new Date(value)) : '—'
}

function valueLabel(value) {
  if (value == null || value === '') return 'Не указано'
  if (typeof value === 'object') return value.name || value.title || value.label || JSON.stringify(value)
  return String(value)
}

function history(incident) {
  return [
    { key: 'delivered', at: incident.delivered_at, title: 'Карточка поступила', body: '' },
    ...(incident.opened_at ? [{ key: 'opened', at: incident.opened_at, title: 'Карточка открыта', body: '' }] : []),
    ...(incident.actions || []).map((item) => ({
      key: `action-${item.id}`, at: item.created_at,
      title: incidentHistoryLabels[item.status] || item.status,
      body: [item.actor_display_name, item.comment].filter(Boolean).join(' · '),
    })),
    ...(incident.scenario_events || []).map((item) => ({
      key: `event-${item.id}`, at: item.created_at,
      title: item.origin === 'INSTRUCTOR' ? 'Вводная преподавателя' : 'Новая информация', body: item.body,
    })),
    ...(incident.activities || []).map((item) => ({
      key: `activity-${item.id}`, at: item.created_at,
      title: item.service_name || 'Учебная бригада', body: item.body,
    })),
    ...(incident.response_assignments || []).flatMap((assignment) => [
      ...assignment.events.map((item, index) => ({
        key: `assignment-${assignment.id}-${index}`, at: item.created_at,
        title: assignment.unit_name, body: responseStateLabels[item.state] || item.state,
      })),
      ...assignment.messages.map((item) => ({
        key: `message-${item.id}`, at: item.created_at,
        title: `${assignment.unit_name} · ${responseSenderLabels[item.sender_type] || item.sender_type}`,
        body: item.body,
      })),
    ]),
  ].filter((item) => item.at).sort((a, b) => new Date(a.at) - new Date(b.at))
}

function WorkstationMirror({ workstation }) {
  const [inspectedId, setInspectedId] = useState(null)
  if (!workstation.incidents) return <p>Загрузка рабочего места…</p>
  const incidents = workstation.incidents
  const openId = workstation.open_incident_id
  const inspected = incidents.find((incident) => incident.id === inspectedId)
  const incident = inspected || incidents.find((item) => item.id === openId)
  const following = !inspected
  const facts = incident?.source_snapshot || {}

  return <section className={styles.mirror} aria-label="Рабочее место обучаемого, только просмотр">
    <div className={styles.toolbar}>
      <span>РЕЖИМ НАБЛЮДЕНИЯ · ТОЛЬКО ПРОСМОТР</span>
      <strong>{openId ? `У обучаемого открыта карточка ${incidents.find((item) => item.id === openId)?.incident_number || openId}` : 'У обучаемого нет открытой карточки'}</strong>
      {!following && <button type="button" onClick={() => setInspectedId(null)}>Вернуться к открытой карточке</button>}
    </div>
    <div className={styles.layout}>
      <nav className={styles.registry} aria-label="Карточки АРМ">
        <h3>Карточки АРМ</h3>
        {incidents.length ? incidents.map((item) => <button
          type="button" key={item.id} onClick={() => setInspectedId(item.id)}
          className={item.id === incident?.id ? styles.selected : ''}
          aria-current={item.id === incident?.id ? 'true' : undefined}
        >
          <span><b>{item.incident_number}</b>{item.id === openId && <em>Открыта сейчас</em>}</span>
          <span>{item.incident_type}</span>
          <small>{item.address}</small>
          <small>{ddsStatusLabels[item.dds_status] || item.dds_status}</small>
        </button>) : <p>Карточек пока нет.</p>}
      </nav>
      <div className={styles.card}>
        {!incident ? <div className={styles.empty}>Обучаемый сейчас просматривает реестр карточек. Выберите карточку слева, чтобы изучить её историю.</div> : <>
          <div className={styles.cardTop}>
            <div><small>{following ? 'КАРТОЧКА НА ЭКРАНЕ ОБУЧАЕМОГО' : 'ПРОСМОТР ИСТОРИИ КАРТОЧКИ'}</small><h3>Происшествие {incident.incident_number}</h3></div>
            <strong>{ddsStatusLabels[incident.dds_status] || incident.dds_status}</strong>
          </div>
          <div className={styles.facts}>
            <div><small>Тип происшествия</small><b>{incident.incident_type}</b></div>
            <div><small>Адрес</small><b>{incident.address}</b></div>
            <div><small>Время сообщения</small><b>{time(incident.reported_at)}</b></div>
            <div><small>Источник</small><b>{incidentSourceLabels[incident.source] || incident.source}</b></div>
            <div><small>Заявитель</small><b>{incident.applicant_name || 'Не указан'}</b></div>
            <div><small>Телефон</small><b>{incident.applicant_phone || 'Не указан'}</b></div>
            {incident.latitude != null && incident.longitude != null && <div><small>Координаты</small><b>{incident.latitude}, {incident.longitude}</b></div>}
            {facts.classifier_code && <div><small>Код классификатора</small><b>{facts.classifier_code}</b></div>}
            {facts.victims != null && <div><small>Пострадавшие</small><b>{valueLabel(facts.victims)}</b></div>}
            {facts.features?.length > 0 && <div><small>Признаки</small><b>{facts.features.map(valueLabel).join(' · ')}</b></div>}
            {(facts.scenario_services?.length > 0 || facts.notified_services?.length > 0) && <div><small>Службы</small><b>{(facts.scenario_services || facts.notified_services).map(valueLabel).join(' · ')}</b></div>}
          </div>
          <section className={styles.description}><h4>Описание</h4><p>{incident.description}</p></section>
          <section className={styles.history}><h4>История карточки</h4>
            {history(incident).map((item) => <article key={item.key}><time>{time(item.at)}</time><div><b>{item.title}</b>{item.body && <p>{item.body}</p>}</div></article>)}
          </section>
          <section className={styles.history}><h4>Группы реагирования и сообщения</h4>
            {incident.response_assignments?.length ? incident.response_assignments.map((assignment) => <div key={assignment.id} className={styles.assignment}>
              <b>{assignment.unit_name} · {responseStateLabels[assignment.state] || assignment.state}</b>
              {assignment.messages.map((message) => <p key={message.id}><time>{time(message.created_at)}</time> {responseSenderLabels[message.sender_type] || message.sender_type}: {message.body}</p>)}
            </div>) : <p>Сообщений пока нет.</p>}
          </section>
        </>}
      </div>
    </div>
  </section>
}

export default WorkstationMirror
