import styles from './App.module.css'

function App() {
  return (
    <main className={styles.page}>
      <section className={styles.hero}>
        <div className={styles.badge} aria-hidden="true">
          112
        </div>
        <p className={styles.eyebrow}>Подготовка диспетчеров ДДС</p>
        <h1>Учебный тренажёр 112</h1>
        <p className={styles.description}>
          Безопасная среда для отработки приёма карточек и решений по реагированию.
        </p>
        <div className={styles.status} role="status">
          <span className={styles.statusDot} />
          Каркас приложения готов к разработке
        </div>
      </section>
    </main>
  )
}

export default App
