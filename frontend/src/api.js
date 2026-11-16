export const apiBase = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

export async function api(path, { token, ...options } = {}) {
  let response
  try {
    response = await fetch(`${apiBase}/api${path}`, {
      ...options,
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
    })
  } catch {
    throw new Error('서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.')
  }
  const data = response.status === 204 ? {} : await response.json().catch(() => {
    throw new Error('API 응답 형식이 올바르지 않습니다. API 주소를 확인해 주세요.')
  })
  if (!response.ok) throw new Error(data.detail || '요청을 처리하지 못했습니다.')
  return data
}
