import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { signOut } from '../api/auth'
import { scanEmails } from '../api/emails'
import { getApplications, getAnalytics, type Application, type AnalyticsSummary } from '../api/applications'
import { EditModal } from './EditModal'

const LIGHT = {
  pageBg:    '#f8fafc', surface:  '#ffffff', border:   '#e2e8f0',
  headerBg:  '#ffffff', theadBg:  '#f8fafc', rowBorder:'#f1f5f9',
  text:      '#1e293b', textMuted:'#64748b', textFaint:'#94a3b8',
  statBorder:'#e2e8f0', btnBorder:'#e2e8f0', btnText:  '#64748b',
  barTrack:  '#f1f5f9',
}
const DARK = {
  pageBg:    '#0f172a', surface:  '#1e293b', border:   '#334155',
  headerBg:  '#1e293b', theadBg:  '#162032', rowBorder:'#1e2d42',
  text:      '#f1f5f9', textMuted:'#94a3b8', textFaint:'#64748b',
  statBorder:'#334155', btnBorder:'#334155', btnText:  '#94a3b8',
  barTrack:  '#0f172a',
}

const STATUS_LABEL: Record<string, string> = { applied:'Applied', interview:'Interview', offer:'Offer', rejected:'Rejected' }
const STATUS_COLOR: Record<string, string> = { applied:'#3b82f6', interview:'#f59e0b', offer:'#10b981', rejected:'#ef4444' }

function StatusBadge({ status }: { status: string }) {
  return (
    <span style={{ background: STATUS_COLOR[status] ?? '#6b7280', color:'#fff', borderRadius:'9999px', padding:'2px 10px', fontSize:12, fontWeight:600, whiteSpace:'nowrap' }}>
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}

function formatDate(d: string | null) {
  return d ? new Date(d).toLocaleDateString('en-CA') : '—'
}

function MetricCard({ label, value, color, t }: { label: string; value: string | number; color: string; t: typeof LIGHT }) {
  return (
    <div style={{ background: t.surface, border: `1px solid ${t.statBorder}`, borderRadius: 12, padding: '16px 24px', flex: '1 1 160px', minWidth: 140 }}>
      <div style={{ fontSize: 28, fontWeight: 700, color }}>{value}</div>
      <div style={{ fontSize: 12, color: t.textFaint, marginTop: 4 }}>{label}</div>
    </div>
  )
}

function AnalyticsView({ analytics, t }: { analytics: AnalyticsSummary; t: typeof LIGHT }) {
  const { total, status_counts, weekly_applications, avg_days_to_interview } = analytics
  const applied   = status_counts.applied   ?? 0
  const interview = status_counts.interview ?? 0
  const offer     = status_counts.offer     ?? 0
  const rejected  = status_counts.rejected  ?? 0

  const interviewRate = total > 0 ? Math.round((interview + offer) / total * 100) : 0
  const offerRate     = total > 0 ? Math.round(offer / total * 100) : 0
  const responseRate  = total > 0 ? Math.round((total - applied) / total * 100) : 0

  const maxWeekly = Math.max(...weekly_applications.map(w => w.total), 1)

  const card = { background: t.surface, border: `1px solid ${t.border}`, borderRadius: 12, padding: 24, marginBottom: 20 }

  return (
    <div>
      {/* Metric cards */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 20 }}>
        <MetricCard label="Total Applications" value={total}                                         color={t.text}   t={t} />
        <MetricCard label="Response Rate"       value={`${responseRate}%`}                           color="#3b82f6"  t={t} />
        <MetricCard label="Interview Rate"      value={`${interviewRate}%`}                          color="#f59e0b"  t={t} />
        <MetricCard label="Offer Rate"          value={`${offerRate}%`}                              color="#10b981"  t={t} />
        <MetricCard label="Avg Days to Interview" value={avg_days_to_interview != null ? `${avg_days_to_interview}d` : '—'} color="#a855f7" t={t} />
      </div>

      {/* Status breakdown */}
      <div style={card}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 600, color: t.text }}>Status Breakdown</h3>
        {[
          { label: 'Applied',   count: applied,   color: '#3b82f6' },
          { label: 'Interview', count: interview, color: '#f59e0b' },
          { label: 'Offer',     count: offer,     color: '#10b981' },
          { label: 'Rejected',  count: rejected,  color: '#ef4444' },
        ].map(s => {
          const pct = total > 0 ? Math.round(s.count / total * 100) : 0
          return (
            <div key={s.label} style={{ marginBottom: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 13 }}>
                <span style={{ color: t.textMuted, fontWeight: 500 }}>{s.label}</span>
                <span style={{ color: t.textFaint }}>{s.count} &nbsp;·&nbsp; {pct}%</span>
              </div>
              <div style={{ height: 8, borderRadius: 4, background: t.barTrack, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${pct}%`, background: s.color, borderRadius: 4, transition: 'width 0.4s ease' }} />
              </div>
            </div>
          )
        })}
      </div>

      {/* Weekly activity */}
      <div style={card}>
        <h3 style={{ margin: '0 0 20px', fontSize: 15, fontWeight: 600, color: t.text }}>Weekly Applications (Last 12 Weeks)</h3>
        {weekly_applications.length === 0 ? (
          <p style={{ color: t.textFaint, fontSize: 13 }}>No data yet.</p>
        ) : (
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, height: 140 }}>
            {weekly_applications.map(w => {
              const height = Math.max(Math.round((w.total / maxWeekly) * 120), 4)
              const weekLabel = new Date(w.week).toLocaleDateString('en-CA', { month: 'short', day: 'numeric' })
              return (
                <div key={w.week} title={`${weekLabel}: ${w.total}`} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                  <span style={{ fontSize: 10, color: t.textFaint }}>{w.total}</span>
                  <div style={{ width: '100%', height, background: '#3b82f6', borderRadius: '4px 4px 0 0', minHeight: 4 }} />
                  <span style={{ fontSize: 9, color: t.textFaint, textAlign: 'center', lineHeight: 1.2 }}>{weekLabel}</span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export function Dashboard() {
  const { user, token, logout } = useAuth()
  const [tab, setTab]           = useState<'applications' | 'analytics'>('applications')
  const [applications, setApplications] = useState<Application[]>([])
  const [analytics, setAnalytics]       = useState<AnalyticsSummary | null>(null)
  const [scanning, setScanning]         = useState(false)
  const [refreshing, setRefreshing]     = useState(false)
  const [loading, setLoading]           = useState(true)
  const [analyticsLoading, setAnalyticsLoading] = useState(false)
  const [error, setError]               = useState<string | null>(null)
  const [newCount, setNewCount]         = useState<number | null>(null)
  const [darkMode, setDarkMode]         = useState(() => localStorage.getItem('darkMode') === 'true')
  const [editingApp, setEditingApp] = useState<Application | null>(null)
  const [filterStatus, setFilterStatus] = useState('')
  const [filterSource, setFilterSource] = useState('')
  const [filterFrom, setFilterFrom]     = useState('')
  const [filterTo, setFilterTo]         = useState('')

  const t = darkMode ? DARK : LIGHT

  const toggleDark = () => setDarkMode(d => { localStorage.setItem('darkMode', String(!d)); return !d })

  const loadApplications = async (showRefresh = false) => {
    if (!token) return
    if (showRefresh) setRefreshing(true)
    try { setApplications(await getApplications(token)) }
    catch { setError('Failed to load applications.') }
    finally { setLoading(false); setRefreshing(false) }
  }

  const loadAnalytics = async () => {
    if (!token) return
    setAnalyticsLoading(true)
    try { setAnalytics(await getAnalytics(token)) }
    catch { setError('Failed to load analytics.') }
    finally { setAnalyticsLoading(false) }
  }

  useEffect(() => { loadApplications() }, [token])
  useEffect(() => { if (tab === 'analytics') loadAnalytics() }, [tab])

  const handleLogout = async () => { if (token) await signOut(token).catch(() => {}); logout() }

  const handleScan = async () => {
    if (!token) return
    setScanning(true)
    setError(null)
    setNewCount(null)

    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 5 * 60 * 1000) // 5 min max

    try {
      const result = await scanEmails(token, controller.signal)
      clearTimeout(timeout)
      setScanning(false)
      setNewCount(result.emails.length)
      await loadApplications(true)
      if (tab === 'analytics') await loadAnalytics()
    } catch (err) {
      clearTimeout(timeout)
      setScanning(false)
      const isTimeout = err instanceof Error && err.name === 'AbortError'
      setError(isTimeout ? 'Scan timed out — the Databricks warehouse may be waking up. Try again in a minute.' : 'Scan failed. Please try again.')
    }
  }

  const uniqueSources = Array.from(new Set(applications.map(a => a.source).filter(Boolean))).sort() as string[]

  const filtered = applications.filter(a => {
    if (filterStatus && a.current_status !== filterStatus) return false
    if (filterSource && a.source !== filterSource) return false
    if (filterFrom && a.applied_at && a.applied_at < filterFrom) return false
    if (filterTo && a.applied_at && a.applied_at > filterTo + 'T23:59:59') return false
    return true
  })

  const counts = {
    total:     applications.length,
    interview: applications.filter(a => a.current_status === 'interview').length,
    offer:     applications.filter(a => a.current_status === 'offer').length,
    rejected:  applications.filter(a => a.current_status === 'rejected').length,
  }

  const inputStyle = { padding: '7px 10px', borderRadius: 6, border: `1px solid ${t.border}`, background: t.surface, color: t.text, fontSize: 13, outline: 'none' }

  const exportCSV = () => {
    const headers = ['Company', 'Position', 'Status', 'Source', 'Applied']
    const rows = filtered.map(app => [
      app.company,
      app.position ?? '',
      STATUS_LABEL[app.current_status] ?? app.current_status,
      app.source ?? '',
      formatDate(app.applied_at),
    ])
    const csv = [headers, ...rows]
      .map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
      .join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `job_applications_${new Date().toISOString().split('T')[0]}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const tabBtn = (id: 'applications' | 'analytics', label: string) => (
    <button onClick={() => setTab(id)} style={{ padding: '8px 20px', borderRadius: 8, border: 'none', cursor: 'pointer', fontWeight: 600, fontSize: 14, background: tab === id ? '#3b82f6' : 'transparent', color: tab === id ? '#fff' : t.textMuted, transition: 'all 0.15s' }}>
      {label}
    </button>
  )

  return (
    <div style={{ minHeight: '100vh', background: t.pageBg, fontFamily: 'system-ui, sans-serif', transition: 'background 0.2s' }}>

      {/* Header */}
      <header style={{ background: t.headerBg, borderBottom: `1px solid ${t.border}`, padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', height: 60 }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: t.text }}>JobTracker</h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {user?.picture && <img src={user.picture} alt={user.name} style={{ width: 32, height: 32, borderRadius: '50%' }} referrerPolicy="no-referrer" />}
          <span style={{ fontSize: 14, color: t.textMuted }}>{user?.name}</span>
          <button onClick={toggleDark} title={darkMode ? 'Light mode' : 'Dark mode'} style={{ fontSize: 16, padding: '6px 10px', borderRadius: 6, border: `1px solid ${t.btnBorder}`, background: t.surface, cursor: 'pointer', lineHeight: 1 }}>
            {darkMode ? '☀️' : '🌙'}
          </button>
          <button onClick={handleLogout} style={{ fontSize: 13, padding: '6px 14px', borderRadius: 6, border: `1px solid ${t.btnBorder}`, background: t.surface, cursor: 'pointer', color: t.btnText }}>
            Sign out
          </button>
        </div>
      </header>

      <main style={{ maxWidth: '95vw', margin: '0 auto', padding: '24px 32px' }}>

        {/* Stats + Scan */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20, flexWrap: 'wrap', gap: 16 }}>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            {[{ label:'Total', value: counts.total, color: t.text }, { label:'Interview', value: counts.interview, color:'#f59e0b' }, { label:'Offer', value: counts.offer, color:'#10b981' }, { label:'Rejected', value: counts.rejected, color:'#ef4444' }].map(s => (
              <div key={s.label} style={{ background: t.surface, border: `1px solid ${t.statBorder}`, borderRadius: 10, padding: '12px 20px', minWidth: 90, textAlign: 'center' }}>
                <div style={{ fontSize: 24, fontWeight: 700, color: s.color }}>{s.value}</div>
                <div style={{ fontSize: 12, color: t.textFaint, marginTop: 2 }}>{s.label}</div>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
            <button onClick={handleScan} disabled={scanning} style={{ padding: '10px 22px', background: scanning ? '#94a3b8' : '#3b82f6', color: '#fff', border: 'none', borderRadius: 8, fontWeight: 600, fontSize: 14, cursor: scanning ? 'default' : 'pointer' }}>
              {scanning ? 'Scanning...' : 'Scan Emails'}
            </button>
            {newCount !== null && !scanning && <span style={{ fontSize: 13, color: t.textMuted }}>{newCount === 0 ? 'No new emails found' : `${newCount} new email${newCount !== 1 ? 's' : ''} ingested`}</span>}
            {error && <span style={{ fontSize: 13, color: '#ef4444' }}>{error}</span>}
          </div>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 20, background: t.surface, border: `1px solid ${t.border}`, borderRadius: 10, padding: 4, width: 'fit-content' }}>
          {tabBtn('applications', 'Applications')}
          {tabBtn('analytics', 'Analytics')}
        </div>

        {/* Applications tab */}
        {tab === 'applications' && (
          <>
            {/* Filters */}
            <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
              <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)} style={inputStyle}>
                <option value="">All Statuses</option>
                <option value="applied">Applied</option>
                <option value="interview">Interview</option>
                <option value="offer">Offer</option>
                <option value="rejected">Rejected</option>
              </select>
              <select value={filterSource} onChange={e => setFilterSource(e.target.value)} style={inputStyle}>
                <option value="">All Sources</option>
                {uniqueSources.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <label style={{ fontSize: 12, color: t.textMuted }}>From</label>
                <input type="date" value={filterFrom} onChange={e => setFilterFrom(e.target.value)} style={inputStyle} />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <label style={{ fontSize: 12, color: t.textMuted }}>To</label>
                <input type="date" value={filterTo} onChange={e => setFilterTo(e.target.value)} style={inputStyle} />
              </div>
              {(filterStatus || filterSource || filterFrom || filterTo) && (
                <button onClick={() => { setFilterStatus(''); setFilterSource(''); setFilterFrom(''); setFilterTo('') }} style={{ ...inputStyle, cursor: 'pointer', color: '#ef4444', borderColor: '#ef4444' }}>Clear</button>
              )}
              <span style={{ fontSize: 13, color: t.textFaint, marginLeft: 'auto' }}>{filtered.length} of {applications.length} application{applications.length !== 1 ? 's' : ''}</span>
              <button onClick={exportCSV} disabled={filtered.length === 0} style={{ ...inputStyle, cursor: filtered.length === 0 ? 'default' : 'pointer', color: '#10b981', borderColor: '#10b981', opacity: filtered.length === 0 ? 0.4 : 1, whiteSpace: 'nowrap' }}>
                ⬇ Export CSV
              </button>
            </div>

            {/* Table */}
            <div style={{ background: t.surface, border: `1px solid ${t.border}`, borderRadius: 12, overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14, tableLayout: 'fixed' }}>
                <colgroup>
                  <col style={{ width: '20%' }} /><col style={{ width: '24%' }} /><col style={{ width: '11%' }} />
                  <col style={{ width: '16%' }} /><col style={{ width: '11%' }} /><col style={{ width: '8%' }} />
                </colgroup>
                <thead>
                  <tr style={{ background: t.theadBg, borderBottom: `1px solid ${t.border}` }}>
                    {['Company','Position','Status','Source','Applied',''].map(h => (
                      <th key={h} style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: t.textMuted, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.05em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {loading || refreshing ? (
                    <tr><td colSpan={6} style={{ padding: 40, textAlign: 'center', color: t.textFaint }}>{refreshing ? 'Refreshing...' : 'Loading...'}</td></tr>
                  ) : filtered.length === 0 ? (
                    <tr><td colSpan={6} style={{ padding: 40, textAlign: 'center', color: t.textFaint }}>{applications.length === 0 ? 'No applications yet — click Scan Emails to get started.' : 'No applications match the current filters.'}</td></tr>
                  ) : filtered.map(app => (
                    <tr key={app.application_id} style={{ borderBottom: `1px solid ${t.rowBorder}` }}>
                      <td style={{ padding: '12px 16px', fontWeight: 600, color: t.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{app.company}</td>
                      <td style={{ padding: '12px 16px', color: t.textMuted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{app.position ?? <span style={{ color: t.textFaint }}>—</span>}</td>
                      <td style={{ padding: '12px 16px', textAlign: 'center' }}><StatusBadge status={app.current_status} /></td>
                      <td style={{ padding: '12px 16px', color: t.textMuted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{app.source ?? '—'}</td>
                      <td style={{ padding: '12px 16px', color: t.textFaint, whiteSpace: 'nowrap', textAlign: 'center' }}>{formatDate(app.applied_at)}</td>
                      <td style={{ padding: '8px 12px', textAlign: 'center' }}>
                        <button onClick={() => setEditingApp(app)} title="Edit" style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 15, color: t.textFaint, padding: '4px 6px', borderRadius: 4 }}>✏️</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {/* Analytics tab */}
        {tab === 'analytics' && (
          analyticsLoading ? (
            <div style={{ padding: 60, textAlign: 'center', color: t.textFaint }}>Loading analytics...</div>
          ) : analytics ? (
            <AnalyticsView analytics={analytics} t={t} />
          ) : (
            <div style={{ padding: 60, textAlign: 'center', color: t.textFaint }}>No data yet — scan your emails first.</div>
          )
        )}
      </main>

      {editingApp && (
        <EditModal
          app={editingApp}
          token={token!}
          darkMode={darkMode}
          onSaved={() => loadApplications(true)}
          onDeleted={() => loadApplications(true)}
          onClose={() => setEditingApp(null)}
        />
      )}
    </div>
  )
}
