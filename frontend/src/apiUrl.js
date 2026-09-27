const configuredApiUrl = import.meta.env.VITE_API_URL?.trim()

export const apiUrl = configuredApiUrl
  ? configuredApiUrl.replace(/\/$/, '')
  : window.location.origin
