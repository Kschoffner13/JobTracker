const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export interface Application {
  application_id: number
  company: string
  position: string | null
  current_status: 'applied' | 'interview' | 'offer' | 'rejected'
  source: string | null
  job_type: string | null
  job_url: string | null
  applied_at: string | null
  last_updated: string | null
  job_id: string
  provider: string
}

export interface AnalyticsSummary {
  status_counts: Record<string, number>
  weekly_applications: { week: string; total: number }[]
  avg_days_to_interview: number | null
  total: number
}


export async function getApplications(token: string): Promise<Application[]> {
  const res = await fetch(`${BASE_URL}/api/applications`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to fetch applications')
  return res.json()
}

export async function updateApplication(token: string, id: number, data: { company_name?: string; position?: string; current_status?: string; job_type?: string | null; job_url?: string | null }): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/applications/${id}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update application')
}

export async function deleteApplication(token: string, id: number): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/applications/${id}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to delete application')
}


export async function getAnalytics(token: string): Promise<AnalyticsSummary> {
  const res = await fetch(`${BASE_URL}/api/applications/analytics/summary`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to fetch analytics')
  return res.json()
}
