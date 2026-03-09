from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000"]

    # Video processing
    frame_resize_width: int = 320
    frame_resize_height: int = 240
    default_fps: int = 3
    min_fps: int = 1

    # Gaze estimation
    gaze_threshold_degrees: float = 15.0

    # Metrics
    rolling_window_seconds: float = 30.0
    metrics_emit_interval_seconds: float = 1.0
    live_metrics_min_emit_interval_seconds: float = 0.25
    attention_drift_window_seconds: float = 60.0
    attention_drift_slope_threshold: float = -0.2
    attention_state_window_seconds: float = 10.0
    attention_state_min_samples: int = 5
    attention_state_face_missing_ratio_threshold: float = 0.35
    attention_state_min_gaze_samples: int = 3
    attention_state_min_gaze_coverage: float = 0.5
    attention_state_camera_facing_ratio_threshold: float = 0.6
    attention_state_screen_horizontal_max_deg: float = 28.0
    attention_state_screen_vertical_max_deg: float = 18.0
    attention_state_down_vertical_min_deg: float = 12.0
    attention_state_down_vertical_max_deg: float = 32.0
    attention_state_off_task_horizontal_min_deg: float = 35.0
    attention_state_off_task_up_vertical_min_deg: float = 18.0
    attention_state_off_task_down_vertical_min_deg: float = 36.0

    # Energy weights
    energy_weight_rms: float = 0.5
    energy_weight_speech_rate: float = 0.3
    energy_weight_expression: float = 0.2

    # Audio speech gating / interruption filtering
    speech_noise_gate_db: float = 6.0
    speech_zcr_min: float = 0.01
    speech_zcr_max: float = 0.25
    speech_start_min_positive_frames: int = 2
    speech_start_window_frames: int = 3
    speech_end_hangover_frames: int = 5
    overlap_min_duration_seconds: float = 0.25
    hard_interruption_min_duration_seconds: float = 0.60
    interruption_simultaneous_start_margin_seconds: float = 0.12
    interruption_prior_speaker_min_duration_seconds: float = 0.30
    interruption_cutoff_yield_window_seconds: float = 0.30
    interruption_backchannel_quiet_margin_db: float = 6.0
    interruption_hard_quiet_margin_db: float = 3.0
    echo_suspect_quiet_margin_db: float = 10.0
    echo_suspect_repeat_count: int = 3
    echo_suspect_window_seconds: float = 30.0

    # Coaching
    global_nudge_warmup_seconds: int = 120
    global_nudge_min_interval_seconds: int = 300
    global_nudge_max_per_session: int = 3
    min_session_elapsed_for_nudges: int = 60
    student_silence_threshold_seconds: int = 180
    student_silence_talk_percent: float = 0.05
    student_silence_cooldown: int = 120
    low_eye_contact_threshold: float = 0.3
    low_eye_contact_duration: int = 30
    low_eye_contact_cooldown: int = 60
    tutor_overtalk_threshold: float = 0.80
    tutor_overtalk_window: int = 300
    tutor_overtalk_cooldown: int = 180
    energy_drop_threshold: float = 0.20
    energy_drop_from_baseline_threshold: float = 0.25
    energy_drop_cooldown: int = 120
    interruption_spike_count: int = 3
    interruption_spike_window: int = 120
    interruption_spike_cooldown: int = 90

    # Adaptive degradation thresholds (rolling avg of last 5 frames)
    degradation_step1_ms: float = 250.0
    degradation_step2_ms: float = 350.0
    degradation_step3_ms: float = 450.0
    degradation_recovery_frames: int = 10

    # Reconnect
    reconnect_grace_seconds: float = 10.0  # Wait before finalizing session on disconnect

    # Media provider / LiveKit
    default_media_provider: str = "custom_webrtc"
    enable_livekit: bool = False
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_room_prefix: str = "lsa"
    livekit_token_ttl_seconds: int = 3600

    # Analytics
    session_data_dir: str = "data/sessions"
    session_retention_days: int = 90

    # Trace / eval observability
    enable_session_tracing: bool = False
    trace_dir: str = "data/traces"
    trace_write_mode: str = "ndjson"
    trace_max_metrics_snapshots: int = 1800
    trace_max_signal_points_per_role: int = 7200
    trace_downsample_long_sessions: bool = True

    model_config = {"env_prefix": "LSA_"}


settings = Settings()
