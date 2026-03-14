export type MediaProvider = 'custom_webrtc' | 'livekit'

export type AttentionState =
  | 'FACE_MISSING'
  | 'LOW_CONFIDENCE'
  | 'CAMERA_FACING'
  | 'SCREEN_ENGAGED'
  | 'DOWN_ENGAGED'
  | 'OFF_TASK_AWAY'

export type NudgePriority = 'low' | 'medium' | 'high'

export interface ParticipantMetrics {
  eye_contact_score: number
  talk_time_percent: number
  energy_score: number
  energy_drop_from_baseline: number
  is_speaking: boolean
  attention_state: AttentionState
  attention_state_confidence: number
  instant_attention_state: AttentionState
  instant_attention_state_confidence: number
  face_presence_score: number
  visual_attention_score: number
  time_in_attention_state_seconds: number
  talk_time_pct_windowed: number
  time_since_spoke_seconds: number
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
  latency_p50_ms: number
  latency_p95_ms: number
  degradation_reason: string
  target_fps: number
  transcript_available?: boolean
  student_uncertainty_score?: number | null
  student_uncertainty_topic?: string | null
  student_uncertainty_confidence?: number | null
  ai_suggestion?: string | null
  backpressure_level?: number
  coaching_decision?: {
    candidate_nudges: string[]
    candidate_rule_scores?: Record<string, number>
    suppressed_reasons: string[]
    emitted_nudge: string | null
    emitted_priority?: NudgePriority | null
    trigger_features: Record<string, unknown>
    session_type: string
    coaching_intensity?: string
    candidates_evaluated?: string[]
    fired_rule?: string | null
    fired_rule_score?: number | null
  } | null
  coaching_status?: {
    active: boolean
    warmup_remaining_s: number
    next_eligible_s: number
    rules_evaluated: number
    budget_remaining: number
  } | null
}

export interface Nudge {
  id: string
  timestamp: string
  nudge_type: string
  message: string
  priority: NudgePriority
  trigger_metrics: Record<string, unknown>
}

export interface NudgeDetail {
  nudge_type: string
  message: string
  timestamp: string
  priority: NudgePriority
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

export interface TranscriptMessage {
  utterance_id: string
  revision: number
  role: 'tutor' | 'student'
  text: string
  start_time: number
  end_time: number
  is_partial: boolean
  uncertainty_score?: number
  uncertainty_topic?: string
  sentiment?: string
}

export interface AISuggestion {
  id: string
  topic: string
  observation: string
  suggestion: string
  suggested_prompt: string
  priority: 'low' | 'medium' | 'high'
  confidence: number
}

export type TranscriptPartialData = TranscriptMessage & { is_partial: true }
export type TranscriptFinalData = TranscriptMessage & { is_partial: false }

export interface WSMessage {
  type:
    | 'metrics'
    | 'nudge'
    | 'session_end'
    | 'participant_ready'
    | 'participant_disconnected'
    | 'participant_reconnected'
    | 'webrtc_signal'
    | 'transcript_partial'
    | 'transcript_final'
  data:
    | MetricsSnapshot
    | Nudge
    | ParticipantPresenceData
    | WebRTCSignalData
    | TranscriptPartialData
    | TranscriptFinalData
}

export interface SessionInfo {
  session_id: string
  session_title?: string
  session_type?: string
  tutor_connected: boolean
  student_connected: boolean
  started: boolean
  ended: boolean
  elapsed_seconds: number
  role: 'tutor' | 'student' | null
  media_provider: MediaProvider
  analytics_ingest_mode?: 'browser_upload' | 'livekit_worker'
  livekit_room_name?: string | null
  coaching_intensity?: string
  /** Whether real-time transcription is enabled for this session. */
  enable_transcription?: boolean
  /** Whether AI coaching suggestions are enabled for this session. */
  enable_ai_coaching?: boolean
  /** Whether post-session transcript storage is enabled for this session. */
  enable_post_session_storage?: boolean
  /** Student invite tokens — only present when the caller is the tutor. */
  student_tokens?: string[]
}

export interface FlaggedMoment {
  timestamp: number
  metric_name: string
  value: number
  direction: 'above' | 'below'
  description: string
}

export interface KeyMoment {
  time: string
  description: string
  significance: string
}

export interface TranscriptSegment {
  utterance_id: string
  role: 'tutor' | 'student'
  text: string
  start_time: number
  end_time: number
  confidence?: number
  sentiment?: string | null
  student_index?: number
}

export interface SessionSummary {
  session_id: string
  session_title?: string
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
  attention_state_distribution?: Record<string, Record<string, number>>
  nudge_details?: NudgeDetail[]
  turn_counts?: Record<string, number>
  // AI Conversational Intelligence post-session fields
  transcript_available?: boolean
  transcript_word_count?: number
  transcript_segments?: TranscriptSegment[]
  topics_covered?: string[]
  ai_summary?: string | null
  student_understanding_map?: Record<string, number>
  key_moments?: KeyMoment[]
  follow_up_recommendations?: string[]
}

export interface StudentInsights {
  /** Overall engagement score for the student, expressed as a percentage (0–100). */
  engagement_percent: number
  /** Student talk-time share expressed as a percentage (0–100). */
  talk_time_percent: number
  /** Composite attention score (average of eye-contact and energy), 0–100. */
  attention_score: number
  /** Ordered list of student-facing actionable tips. */
  tips: string[]
}

export interface RemoteParticipant {
  /** LiveKit participant identity, e.g. `{sessionId}:tutor` or `{sessionId}:student:{N}`. */
  identity: string
  /** Per-participant MediaStream containing that participant's tracks. */
  stream: MediaStream
  /** True if the participant has at least one live video track. */
  hasVideo: boolean
  /** True if the participant has at least one live audio track. */
  hasAudio: boolean
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
