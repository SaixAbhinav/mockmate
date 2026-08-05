import { useRef, useState } from 'react'
import { api } from '../api'

// Deliberately does NOT reset resumeId/resumeName/resumeStatus: the uploaded
// resume stays valid for a second interview without re-uploading.
export function useResumeUpload({ onError }) {
  const [resumeId, setResumeId] = useState(null)
  const [resumeName, setResumeName] = useState('')
  const [resumeStatus, setResumeStatus] = useState('none') // none | uploading | ready | failed
  const resumeUploadTokenRef = useRef(0)

  async function handleResumeChange(e) {
    const file = e.target.files[0]
    if (!file) return
    const token = ++resumeUploadTokenRef.current
    setResumeStatus('uploading')
    onError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const resp = await fetch(api('/api/resume'), { method: 'POST', body: form })
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        throw new Error(body.detail || `resume upload failed (${resp.status})`)
      }
      const data = await resp.json()
      if (token !== resumeUploadTokenRef.current) return // a newer upload superseded this one
      setResumeId(data.resume_id)
      setResumeName(file.name)
      setResumeStatus('ready')
    } catch (err) {
      if (token !== resumeUploadTokenRef.current) return // a newer upload superseded this one
      setResumeId(null)
      setResumeName('')
      setResumeStatus('failed')
      onError(String(err))
    }
  }

  return { resumeId, resumeName, resumeStatus, handleResumeChange }
}
