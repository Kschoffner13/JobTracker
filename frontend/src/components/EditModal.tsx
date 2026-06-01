import { useState } from 'react'
import { updateApplication, deleteApplication, type Application } from '../api/applications'

const LIGHT = { surface:'#ffffff', border:'#e2e8f0', text:'#1e293b', textMuted:'#64748b', textFaint:'#94a3b8', input:'#f8fafc' }
const DARK  = { surface:'#1e293b', border:'#334155', text:'#f1f5f9', textMuted:'#94a3b8', textFaint:'#64748b', input:'#0f172a' }

interface Props {
  app: Application
  token: string
  darkMode: boolean
  onSaved: () => void
  onDeleted: () => void
  onClose: () => void
}

export function EditModal({ app, token, darkMode, onSaved, onDeleted, onClose }: Props) {
  const t = darkMode ? DARK : LIGHT

  const [company, setCompany]   = useState(app.company)
  const [position, setPosition] = useState(app.position ?? '')
  const [status, setStatus]     = useState(app.current_status)
  const [jobType, setJobType]   = useState(app.job_type ?? '')
  const [jobUrl, setJobUrl]     = useState(app.job_url ?? '')
  const [saving, setSaving]         = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting]     = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      await updateApplication(token, app.application_id, {
        company_name:   company  !== app.company           ? company  || undefined : undefined,
        position:       position !== (app.position ?? '')  ? position || undefined : undefined,
        current_status: status   !== app.current_status    ? status                : undefined,
        job_type:       jobType  !== (app.job_type ?? '')  ? jobType  || null      : undefined,
        job_url:        jobUrl   !== (app.job_url ?? '')   ? jobUrl   || null      : undefined,
      })
      onSaved()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    setDeleting(true)
    try {
      await deleteApplication(token, app.application_id)
      onDeleted()
      onClose()
    } finally {
      setDeleting(false)
    }
  }

  const field = { display: 'flex', flexDirection: 'column' as const, gap: 4, marginBottom: 16 }
  const label = { fontSize: 12, fontWeight: 600, color: t.textMuted, textTransform: 'uppercase' as const, letterSpacing: '0.04em' }
  const input = { padding: '8px 10px', borderRadius: 6, border: `1px solid ${t.border}`, background: t.input, color: t.text, fontSize: 14, outline: 'none' }

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 16 }}>
      <div onClick={e => e.stopPropagation()} style={{ background: t.surface, borderRadius: 14, width: '100%', maxWidth: 480, display: 'flex', flexDirection: 'column', overflow: 'hidden', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>

        {/* Header */}
        <div style={{ padding: '20px 24px 16px', borderBottom: `1px solid ${t.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: t.text }}>{app.company}</h2>
            {app.position && <p style={{ margin: '2px 0 0', fontSize: 13, color: t.textMuted }}>{app.position}</p>}
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: t.textFaint, lineHeight: 1, padding: 4 }}>✕</button>
        </div>

        {/* Body */}
        <div style={{ padding: 24 }}>
          <div style={field}>
            <label style={label}>Company</label>
            <input value={company} onChange={e => setCompany(e.target.value)} style={input} placeholder="Company name" />
          </div>
          <div style={field}>
            <label style={label}>Position</label>
            <input value={position} onChange={e => setPosition(e.target.value)} style={input} placeholder="Job title" />
          </div>
          <div style={field}>
            <label style={label}>Status</label>
            <select value={status} onChange={e => setStatus(e.target.value as Application['current_status'])} style={input}>
              <option value="applied">Applied</option>
              <option value="interview">Interview</option>
              <option value="offer">Offer</option>
              <option value="rejected">Rejected</option>
            </select>
          </div>
          <div style={field}>
            <label style={label}>Job Type</label>
            <select value={jobType} onChange={e => setJobType(e.target.value)} style={input}>
              <option value="">Not specified</option>
              <option value="Remote">Remote</option>
              <option value="Hybrid">Hybrid</option>
              <option value="On-site">On-site</option>
            </select>
          </div>
          <div style={{ ...field, marginBottom: 0 }}>
            <label style={label}>Job URL</label>
            <input value={jobUrl} onChange={e => setJobUrl(e.target.value)} style={input} placeholder="https://..." type="url" />
          </div>
        </div>

        {/* Footer */}
        <div style={{ padding: '16px 24px', borderTop: `1px solid ${t.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          {!confirmDelete ? (
            <button onClick={() => setConfirmDelete(true)} style={{ fontSize: 13, padding: '7px 14px', borderRadius: 6, border: '1px solid #ef4444', background: 'transparent', color: '#ef4444', cursor: 'pointer' }}>
              Delete
            </button>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, color: '#ef4444' }}>Are you sure?</span>
              <button onClick={handleDelete} disabled={deleting} style={{ fontSize: 13, padding: '7px 14px', borderRadius: 6, border: 'none', background: '#ef4444', color: '#fff', cursor: 'pointer' }}>
                {deleting ? 'Deleting...' : 'Yes, delete'}
              </button>
              <button onClick={() => setConfirmDelete(false)} style={{ fontSize: 13, padding: '7px 14px', borderRadius: 6, border: `1px solid ${t.border}`, background: 'transparent', color: t.textMuted, cursor: 'pointer' }}>
                Cancel
              </button>
            </div>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={onClose} style={{ fontSize: 13, padding: '7px 16px', borderRadius: 6, border: `1px solid ${t.border}`, background: 'transparent', color: t.textMuted, cursor: 'pointer' }}>
              Cancel
            </button>
            <button onClick={handleSave} disabled={saving} style={{ fontSize: 13, padding: '7px 16px', borderRadius: 6, border: 'none', background: '#3b82f6', color: '#fff', cursor: 'pointer', fontWeight: 600 }}>
              {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
