import { promises as fs } from 'fs'
import path from 'path'
import type { SessionSummary } from '../../src/lib/types'

const SESSION_DATA_DIR = path.resolve(
  process.cwd(),
  '../backend/data/playwright-sessions'
)

interface SeedSessionOptions {
  session_id: string
  tutor_id?: string
  session_type?: string
  media_provider?: SessionSummary['media_provider']
  start_time?: string
  duration_seconds?: number
  talk_time_ratio?: Record<string, number>
  avg_eye_contact?: Record<string, number>
  avg_energy?: Record<string, number>
  total_interruptions?: number
  engagement_score?: number
  flagged_moments?: SessionSummary['flagged_moments']
  timeline?: Record<string, number[]>
  nudges_sent?: number
  degradation_events?: number
}

function buildTimeline({
  engagement = 72,
  studentEye = 0.55,
  studentEnergy = 0.5,
  tutorTalk = 0.58,
  studentTalk = 0.42,
}: {
  engagement?: number
  studentEye?: number
  studentEnergy?: number
  tutorTalk?: number
  studentTalk?: number
}) {
  return {
    engagement: [engagement - 8, engagement - 3, engagement, engagement + 2, engagement - 1],
    tutor_eye_contact: [0.7, 0.72, 0.68, 0.73, 0.71],
    student_eye_contact: [studentEye - 0.08, studentEye - 0.02, studentEye, studentEye + 0.03, studentEye - 0.01],
    tutor_talk_time: [tutorTalk - 0.05, tutorTalk - 0.02, tutorTalk, tutorTalk + 0.03, tutorTalk],
    student_talk_time: [studentTalk + 0.05, studentTalk + 0.02, studentTalk, studentTalk - 0.03, studentTalk],
    tutor_energy: [0.62, 0.66, 0.64, 0.69, 0.67],
    student_energy: [studentEnergy - 0.05, studentEnergy - 0.02, studentEnergy, studentEnergy + 0.04, studentEnergy - 0.01],
  }
}

export async function resetAnalyticsStore() {
  await fs.rm(SESSION_DATA_DIR, { recursive: true, force: true })
  await fs.mkdir(SESSION_DATA_DIR, { recursive: true })
}

export async function seedSessionSummary(options: SeedSessionOptions) {
  const startTime = options.start_time || new Date().toISOString()
  const durationSeconds = options.duration_seconds ?? 1800
  const endTime = new Date(
    new Date(startTime).getTime() + durationSeconds * 1000
  ).toISOString()

  const summary: SessionSummary = {
    session_id: options.session_id,
    tutor_id: options.tutor_id || 'Coach Ada',
    start_time: startTime,
    end_time: endTime,
    duration_seconds: durationSeconds,
    session_type: options.session_type || 'general',
    media_provider: options.media_provider || 'custom_webrtc',
    talk_time_ratio: options.talk_time_ratio || { tutor: 0.58, student: 0.42 },
    avg_eye_contact: options.avg_eye_contact || { tutor: 0.72, student: 0.56 },
    avg_energy: options.avg_energy || { tutor: 0.68, student: 0.52 },
    total_interruptions: options.total_interruptions ?? 3,
    engagement_score: options.engagement_score ?? 72,
    flagged_moments: options.flagged_moments || [],
    timeline:
      options.timeline ||
      buildTimeline({
        engagement: options.engagement_score ?? 72,
        studentEye: options.avg_eye_contact?.student ?? 0.56,
        studentEnergy: options.avg_energy?.student ?? 0.52,
        tutorTalk: options.talk_time_ratio?.tutor ?? 0.58,
        studentTalk: options.talk_time_ratio?.student ?? 0.42,
      }),
    recommendations: [],
    nudges_sent: options.nudges_sent ?? 2,
    degradation_events: options.degradation_events ?? 0,
  }

  await fs.writeFile(
    path.join(SESSION_DATA_DIR, `${summary.session_id}.json`),
    JSON.stringify(summary, null, 2)
  )

  return summary
}

export async function seedSessionSummaries(options: SeedSessionOptions[]) {
  await Promise.all(options.map((option) => seedSessionSummary(option)))
}
