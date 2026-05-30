const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export interface Email {
  id: string
  subject: string
  from: string
  date: string
  snippet: string
  body: string
}

export interface ScanResult {
  count: number
  emails: Email[]
}

export async function scanEmails(token: string, signal?: AbortSignal): Promise<ScanResult> {
  const res = await fetch(`${BASE_URL}/api/emails/scan`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    signal,
  })
  if (!res.ok) throw new Error('Scan failed')
  return res.json()
}
