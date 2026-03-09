export type MediaProvider = 'custom_webrtc' | 'livekit'

export interface ParticipantMetrics {
  eye_contact_score: number
  talk_time_percent: number
  energy_score: number
  energy_drop_from_baseline: number
  is_speaking: boolean
  attention_state:
    | 'FACE_MISSING'
    | 'LOW_CONFIDENCE'
    | 'CAMERA_FACING'
    | 'SCREEN_ENGAGED'
    | 'DOWN_ENGAGED'
    | 'OFF_TASK_AWAY'
  attention_state_confidence: number
  face_presence_score: number
  visual_attention_score: number
}

export interface SessionMetrics {
  interruption_count: number
  recent_interruptions: number
  hard_interruption_count: number
  recent_hard_interruptions: number
  backchannel_overlap_count: number
  recent_backchannel_overlaps: number
  echo_suspected: boolean
  active_overlap_duration_current: number
  active_overlap_state:
    | 'none'
    | 'candidate'
    | 'backchannel'
    | 'meaningful'
    | 'hard'
    | 'echo_like'
  tutor_cutoffs: number
  student_cutoffs: number
  silence_duration_current: number
  time_since_student_spoke: number
  mutual_silence_duration_current: number
  tutor_monologue_duration_current: number
  tutor_turn_count: number
  student_turn_count: number
  student_response_latency_last_seconds: number
  tutor_response_latency_last_seconds: number
  recent_tutor_talk_percent: number
  engagement_trend: 'rising' | 'stable' | 'declining'
  engagement_score: number
}

export interface MetricsSnapshot {
  timestamp: string
  session_id: string
  tutor: ParticipantMetrics
  student: ParticipantMetrics
  session: SessionMetrics
  degraded: boolean
  gaze_unavailable: boolean
  server_processing_ms: number
  target_fps: number
}

export interface Nudge {
  id: string
  timestamp: string
  nudge_type: string
  message: string
  priority: 'low' | 'medium' | 'high'
  trigger_metrics: Record<string, number>
}

export interface ParticipantPresenceData {
  session_id: string
  duration_seconds?: number
  role?: 'tutor' | 'student'
  grace_seconds?: number
  reconnected?: boolean
}

export interface WebRTCSignalData {
  session_id: string
  from_role: 'tutor' | 'student'
  signal_type: 'offer' | 'answer' | 'ice_candidate'
  payload: Record<string, unknown>
}

export interface WSMessage {
  type:
    | 'metrics'
    | 'nudge'
    | 'session_end'
    | 'participant_ready'
    | 'participant_disconnected'
    | 'participant_reconnected'
    | 'webrtc_signal'
  data: MetricsSnapshot | Nudge | ParticipantPresenceData | WebRTCSignalData
}

export interface SessionInfo {
  session_id: string
  tutor_connected: boolean
  student_connected: boolean
  started: boolean
  ended: boolean
  elapsed_seconds: number
  role: 'tutor' | 'student' | null
  media_provider: MediaProvider
  analytics_ingest_mode?: 'browser_upload' | 'livekit_worker'
  livekit_room_name?: string | null
}

export interface FlaggedMoment {
  timestamp: number
  metric_name: string
  value: number
  direction: 'above' | 'below'
  description: string
}

export interface SessionSummary {
  session_id: string
  tutor_id: string
  start_time: string
  end_time: string
  duration_seconds: number
  session_type: string
  media_provider: MediaProvider
  talk_time_ratio: Record<string, number>
  avg_eye_contact: Record<string, number>
  avg_energy: Record<string, number>
  total_interruptions: number
  engagement_score: number
  flagged_moments: FlaggedMoment[]
  timeline: Record<string, number[]>
  recommendations: string[]
  nudges_sent: number
  degradation_events: number
}

export interface TrendData {
  tutor_id: string
  sessions: Array<{
    session_id: string
    start_time: string
    duration_seconds: number
    engagement_score: number
    student_eye_contact: number
    tutor_eye_contact: number
    tutor_talk_ratio: number
    interruptions: number
  }>
  trends: Record<string, 'improving' | 'stable' | 'declining'>
}
