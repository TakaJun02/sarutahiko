export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function getStoredToken() {
  return localStorage.getItem('campus-guide-token')
}

export function storeToken(token) {
  localStorage.setItem('campus-guide-token', token)
}

export function removeStoredToken() {
  localStorage.removeItem('campus-guide-token')
}

export async function apiFetch(path, options = {}) {
  const token = getStoredToken()
  const headers = new Headers(options.headers || {})
  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json')
  }
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(path, {
    ...options,
    headers,
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail || body.message || detail
    } catch {
      // Keep the HTTP status text when the response body is not JSON.
    }
    throw new ApiError(detail, response.status)
  }
  return response
}

export async function fetchThreads() {
  const response = await apiFetch('/api/threads')
  const payload = await response.json()
  return payload.threads
}

export async function fetchThread(threadId) {
  const response = await apiFetch(`/api/threads/${threadId}`)
  return response.json()
}

export async function renameThreadRequest(threadId, title) {
  const response = await apiFetch(`/api/threads/${threadId}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  })
  const payload = await response.json()
  return payload.thread
}

export async function deleteThreadRequest(threadId) {
  await apiFetch(`/api/threads/${threadId}`, { method: 'DELETE' })
}
