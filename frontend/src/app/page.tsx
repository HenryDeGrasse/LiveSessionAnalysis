'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { API_URL } from '@/lib/constants'

export default function Home() {
  const router = useRouter()
  const [tutorName, setTutorName] = useState('')
  const [sessionType, setSessionType] = useState('general')
  const [mediaProvider, setMediaProvider] = useState<'custom_webrtc' | 'livekit'>(
    'custom_webrtc'
  )
  const [joinToken, setJoinToken] = useState('')
  const [joinSessionId, setJoinSessionId] = useState('')
  const [creating, setCreating] = useState(false)
  const [copiedStudentLink, setCopiedStudentLink] = useState(false)
  const [error, setError] = useState('')
  const [sessionInfo, setSessionInfo] = useState<{
    session_id: string
    tutor_token: string
    student_token: string
    media_provider?: 'custom_webrtc' | 'livekit'
    livekit_room_name?: string | null
  } | null>(null)

  const createSession = async () => {
    setCreating(true)
    setError('')
    try {
      const res = await fetch(`${API_URL}/api/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tutor_id: tutorName.trim() || undefined,
          session_type: sessionType,
          media_provider: mediaProvider,
        }),
      })
      if (!res.ok) throw new Error('Failed to create session')
      const data = await res.json()
      setSessionInfo(data)
      setCopiedStudentLink(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create session')
    } finally {
      setCreating(false)
    }
  }

  const joinAstutor = () => {
    if (sessionInfo) {
      router.push(
        `/session/${sessionInfo.session_id}?token=${sessionInfo.tutor_token}`
      )
    }
  }

  const joinAsStudent = () => {
    if (joinSessionId && joinToken) {
      router.push(`/session/${joinSessionId}?token=${joinToken}`)
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <div className="max-w-2xl w-full space-y-8">
        <div className="text-center">
          <h1 className="text-4xl font-bold mb-2">Live Session Analysis</h1>
          <p className="text-gray-600">
            AI-powered engagement analysis for video tutoring sessions
          </p>
        </div>

        {/* Create Session */}
        <div className="bg-white rounded-lg shadow p-6 space-y-4">
          <h2 className="text-xl font-semibold">Start a New Session</h2>
          <p className="text-sm text-gray-600">
            Create a session and share the student link with your student.
          </p>

          {!sessionInfo ? (
            <div className="space-y-3">
              <input
                data-testid="tutor-name-input"
                type="text"
                placeholder="Your name (optional, for tracking trends)"
                value={tutorName}
                onChange={(e) => setTutorName(e.target.value)}
                className="w-full border rounded-lg px-4 py-2 text-sm"
              />
              <select
                data-testid="session-type-select"
                value={sessionType}
                onChange={(e) => setSessionType(e.target.value)}
                className="w-full border rounded-lg px-4 py-2 text-sm bg-white"
              >
                <option value="general">General tutoring</option>
                <option value="lecture">Lecture / explanation</option>
                <option value="practice">Practice / problem solving</option>
                <option value="discussion">Discussion / Socratic</option>
              </select>
              <select
                data-testid="media-provider-select"
                value={mediaProvider}
                onChange={(e) =>
                  setMediaProvider(e.target.value as 'custom_webrtc' | 'livekit')
                }
                className="w-full border rounded-lg px-4 py-2 text-sm bg-white"
              >
                <option value="custom_webrtc">Built-in WebRTC transport</option>
                <option value="livekit">LiveKit transport</option>
              </select>
              <button
                data-testid="create-session-button"
                onClick={createSession}
                disabled={creating}
                className="w-full bg-blue-600 text-white py-3 px-4 rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {creating ? 'Creating...' : 'Create Session'}
              </button>
            </div>
          ) : (
            <div data-testid="session-created-card" className="space-y-3">
              <div className="bg-green-50 border border-green-200 rounded p-3">
                <p className="text-sm font-medium text-green-800">
                  Session created!
                </p>
                <p data-testid="created-session-id" className="text-xs text-green-600 mt-1">
                  Session ID: {sessionInfo.session_id}
                </p>
                <p className="mt-2 text-xs text-green-700">
                  You are the tutor for this session. Share the student link below — students get a clean call view and do not see tutor coaching overlays.
                </p>
              </div>

              <div className="bg-gray-50 rounded p-3">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <p className="text-sm font-medium">Student Join Link:</p>
                  <button
                    type="button"
                    onClick={async () => {
                      const joinLink =
                        typeof window !== 'undefined'
                          ? `${window.location.origin}/session/${sessionInfo.session_id}?token=${sessionInfo.student_token}`
                          : ''
                      if (!joinLink) return
                      await navigator.clipboard.writeText(joinLink)
                      setCopiedStudentLink(true)
                    }}
                    className="rounded-full border border-gray-300 bg-white px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100"
                  >
                    {copiedStudentLink ? 'Copied' : 'Copy link'}
                  </button>
                </div>
                <code data-testid="student-join-link" className="text-xs bg-gray-100 p-2 rounded block break-all">
                  {typeof window !== 'undefined'
                    ? `${window.location.origin}/session/${sessionInfo.session_id}?token=${sessionInfo.student_token}`
                    : ''}
                </code>
              </div>

              <button
                data-testid="join-as-tutor-button"
                onClick={joinAstutor}
                className="w-full bg-blue-600 text-white py-3 px-4 rounded-lg font-medium hover:bg-blue-700 transition-colors"
              >
                Join as Tutor
              </button>
            </div>
          )}

          {error && (
            <p className="text-sm text-red-600">{error}</p>
          )}
        </div>

        {/* Join Session */}
        <div className="bg-white rounded-lg shadow p-6 space-y-4">
          <h2 className="text-xl font-semibold">Join Existing Session</h2>
          <p className="text-sm text-gray-600">
            Enter the session ID and token from your invite link.
          </p>
          <div className="space-y-3">
            <input
              type="text"
              placeholder="Session ID"
              value={joinSessionId}
              onChange={(e) => setJoinSessionId(e.target.value)}
              className="w-full border rounded-lg px-4 py-2 text-sm"
            />
            <input
              type="text"
              placeholder="Join Token"
              value={joinToken}
              onChange={(e) => setJoinToken(e.target.value)}
              className="w-full border rounded-lg px-4 py-2 text-sm"
            />
            <button
              onClick={joinAsStudent}
              disabled={!joinSessionId || !joinToken}
              className="w-full bg-gray-800 text-white py-3 px-4 rounded-lg font-medium hover:bg-gray-900 disabled:opacity-50 transition-colors"
            >
              Join Session
            </button>
          </div>
        </div>

        {/* Analytics Link */}
        <div className="text-center">
          <a
            href="/analytics"
            className="text-blue-600 hover:underline text-sm"
          >
            View Past Session Analytics
          </a>
        </div>
      </div>
    </main>
  )
}
