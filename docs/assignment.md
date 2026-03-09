# AI-Powered Live Session Analysis

Real-time engagement analysis and coaching for video tutoring sessions

## Background

Live tutoring sessions are the core value proposition of the platform, yet tutors often lack real-time
feedback on their teaching effectiveness. Engagement metrics like eye contact, speaking time balance,
and interaction patterns are strong predictors of session quality but are invisible during the session itself.

**Your challenge:** Create a live, AI-powered system that analyzes active video calls to measure
engagement metrics and provides real-time suggestions or flags to help tutors improve session quality.

## Project Overview

Individual or team project focused on real-time video analysis, computer vision, and coaching systems.

### Deliverables

```
Real-time video stream analysis pipeline
Engagement metric calculation (eye contact, speaking time, etc.)
Non-intrusive tutor notification system
Post-session analytics dashboard
Tutor coaching recommendations engine
```
## Core Objectives

```
Analyze video streams in real-time with minimal latency
Calculate meaningful engagement metrics accurately
Deliver actionable suggestions without disrupting the session
Help tutors improve their teaching effectiveness over time
```

## Users

```
Primary: Tutors conducting live sessions
Secondary: Students (indirect beneficiaries), Quality assurance team
```
## Core Requirements

### 1. Real-Time Video Analysis

Process video streams with low latency for live feedback.

**Specifications:**

```
Face detection and tracking for tutor and student
Eye gaze estimation and attention detection
Latency under 500 ms for real-time feedback
Handle variable video quality gracefully
```
### 2. Engagement Metrics

Calculate actionable engagement indicators.

**Specifications:**

```
Eye Contact: Percentage of time participants look at camera/screen
Speaking Time: Balance between tutor and student talk time
Interruptions: Detection and counting of speaking overlaps
Energy Level: Voice tone and facial expression analysis
Attention Drift: Detection of distraction or disengagement
```
### 3. Real-Time Coaching

Provide non-intrusive suggestions during sessions.

**Specifications:**

```
Subtle visual indicators (not disruptive to session flow)
Contextually appropriate timing for suggestions
Configurable sensitivity and notification frequency
Examples: "Student hasn't spoken in 5 minutes", "Try making more eye contact"
```
### 4. Post-Session Analytics


Comprehensive session review and improvement tracking.

**Specifications:**

```
Session summary with key metrics
Trend analysis across multiple sessions
Specific moments flagged for review
Personalized improvement recommendations
```
## Inputs & Outputs

### Inputs

```
Video Streams: Live video feeds from tutor and student
Audio Streams: Session audio for speaking analysis
Session Context: Subject, duration, student level
```
### Outputs

```
Live Metrics: Real-time engagement scores
Coaching Nudges: Contextual suggestions during session
Session Report: Post-session analytics summary
Improvement Plan: Personalized tutor development recommendations
```
## Technical Architecture

### Modular Structure

```
video-processor/ - Real-time video analysis pipeline
metrics-engine/ - Engagement metric calculations
coaching-system/ - Real-time suggestion generation
analytics-dashboard/ - Post-session reporting
docs/ - Decision log and API documentation
```
### Performance Requirements

```
Video processing latency: <500ms
Metric update frequency: 1-2 Hz
System resource usage: Reasonable for typical hardware
```

## Success Criteria

```
Category Metric Target
```
```
Performance Analysis latency <500ms
```
```
Accuracy Eye contact detection accuracy 85 %+
```
```
Accuracy Speaking time measurement 95 %+
```
```
UX Tutor satisfaction with coaching 4/5+ rating
```
```
Impact Session quality improvement Measurable increase
```
```
Reliability System uptime during sessions 99.5%+
```
## Ambiguous Elements (You Must Decide)

```
How intrusive should real-time coaching be? (Subtle vs. explicit)
What metrics matter most for different session types?
How to handle poor video quality or connectivity issues?
Privacy considerations for video analysis
```
## Technical Contact

For questions or clarifications:

[TBD] - [TBD]


# Evaluation Criteria: AI-Powered Live Session

# Analysis

This document outlines how submissions will be evaluated.

## Assessment Overview

Submissions are evaluated across five areas, with emphasis on real-time performance and practical
coaching value.

```
Area Weight Focus
```
```
Real-Time Performance 25 % Latency, reliability, resource efficiency
```
```
Metric Accuracy 25 % Precision of engagement measurements
```
```
Coaching Value 20 % Usefulness and timing of nudges/feedback
```
```
Technical Implementation 15 % Architecture, code quality, scalability
```
```
Documentation 15 % Decision log, limitations, privacy analysis
```
## 1. Real-Time Performance (25%)

### Excellent (23-25 points)

```
Analysis latency consistently <300ms
Smooth metric updates (1-2 Hz minimum)
Handles video quality variations gracefully
CPU usage reasonable for typical hardware
No dropped frames or audio gaps
```
### Good (18-22 points)

```
Analysis latency <500ms
```

```
Metric updates at 1 Hz
Handles most video conditions
Acceptable resource usage
Minimal dropped data
```
### Acceptable (13-17 points)

```
Analysis latency <1 second
Metric updates every 2-3 seconds
Some issues with poor video
Higher resource usage
Occasional dropped data
```
### Needs Improvement (0-12 points)

```
Latency >1 second or highly variable
Infrequent metric updates
Fails with video quality issues
Excessive resource usage
Unreliable data capture
```
## 2. Metric Accuracy (25%)

### Excellent (23-25 points)

```
Eye contact detection accuracy ≥85%
Speaking time measurement ≥95% accurate
Reliable speaker diarization
Interruption detection with low false positives
Metrics validated against ground truth
```
### Good (18-22 points)

```
Eye contact detection accuracy ≥75%
Speaking time measurement ≥90% accurate
Good speaker diarization
Reasonable interruption detection
Some validation performed
```
### Acceptable (13-17 points)

```
Eye contact detection accuracy ≥65%
```

```
Speaking time measurement ≥85% accurate
Basic speaker separation
Interruption detection works
Limited validation
```
### Needs Improvement (0-12 points)

```
Eye contact detection unreliable
Speaking time inaccurate
Speaker diarization fails
Interruption detection broken
No validation
```
## 3. Coaching Value (20%)

### Excellent (18-20 points)

```
Nudges are actionable and specific
Timing is appropriate (not disruptive)
Configurable sensitivity levels
Post-session insights are valuable
Tutors would find system helpful
```
### Good (14-17 points)

```
Nudges provide useful guidance
Generally good timing
Some configurability
Post-session summary useful
Positive tutor value
```
### Acceptable (10-13 points)

```
Basic nudge functionality
Sometimes mistimed
Limited configuration
Basic post-session summary
Some tutor value
```
### Needs Improvement (0-9 points)

```
Nudges not useful or absent
```

```
Disruptive or poorly timed
No configuration
No post-session insights
Would not help tutors
```
## 4. Technical Implementation (15%)

### Excellent (14-15 points)

```
Clean, modular architecture
One-command setup
15+ tests with good coverage
Handles edge cases gracefully
Well-documented API/interfaces
```
### Good (11-13 points)

```
Reasonable architecture
Setup works with minimal friction
10+ tests covering core functionality
Most edge cases handled
Adequate documentation
```
### Acceptable (8-10 points)

```
Basic structure that works
Setup requires some manual steps
Minimal tests (5-10)
Some edge case issues
Basic documentation
```
### Needs Improvement (0-7 points)

```
Disorganized code
Difficult to set up
Few or no tests
Many edge case failures
Poor documentation
```

## 5. Documentation (15%)

### Excellent (14-15 points)

```
Comprehensive decision log
Privacy analysis and recommendations
Clear limitations documented
Calibration methodology explained
Easy for others to extend
```
### Good (11-13 points)

```
Decision log covers main choices
Privacy considered
Key limitations noted
Some calibration documented
Understandable by others
```
### Acceptable (8-10 points)

```
Basic documentation
Limited privacy analysis
Few limitations mentioned
Minimal calibration info
Some gaps
```
### Needs Improvement (0-7 points)

```
Missing documentation
Privacy not addressed
No limitations acknowledged
No calibration info
Hard to understand
```
## Scoring Rubric Summary

```
Score Range Grade Description
```
```
90-100 Excellent Exceptional work, exceeds expectations
```
```
80-89 Good Strong work, meets all core requirements well
```

```
Score Range Grade Description
```
```
70-79 Acceptable Satisfactory work, meets basic requirements
```
```
60-69 Needs Work Partially complete, missing key elements
```
```
<60 Incomplete Does not meet minimum requirements
```
## Automatic Deductions

```
No working demo: -10 points
Cannot run with provided instructions: -10 points
Latency >2 seconds: -10 points
No real-time component: -15 points
No coaching nudges: -10 points
```
## Bonus Points (up to 10)

```
Browser-based implementation (no install required): +
Multi-participant support (group sessions): +
Exceptional visualization of real-time metrics: +
Novel engagement metrics beyond specified: +
```
## Test Scenarios

Your submission will be evaluated against:

```
Normal quality webcam video (720p, 30 fps)
Poor quality video (low light, compression artifacts)
Variable audio quality
Sessions with different talk time ratios
Sessions with engagement changes over time
```
You should create your own test videos for development.


## Submission Checklist

Before submitting, verify:

```
Code runs with one command (or clear, minimal setup)
README explains setup and usage
Real-time latency measured and reported
Metric accuracy validated and documented
Coaching nudges functional and configurable
Post-session analytics available
Privacy considerations documented
Decision log documents major choices
Limitations are explicitly stated
Demo video or live walkthrough included
```

# Starter Kit: AI-Powered Live Session Analysis

This document provides resources, examples, and guidance to help you get started.

## Problem Context

Live tutoring sessions are high-value interactions, but tutors often lack real-time feedback on their
teaching effectiveness. Key engagement signals like eye contact, talk time balance, and energy levels are
invisible during the session itself.

Your system should provide actionable insights without disrupting the teaching flow.

## Key Engagement Metrics

### 1. Eye Contact / Attention

**What to measure:**

```
Percentage of time participant looks at camera/screen
Gaze direction (looking away, down at notes, at phone)
Mutual attention (both looking at each other)
```
**Why it matters:**

```
Strong predictor of engagement and connection
Indicates whether explanations are landing
Helps identify distraction or confusion
```
**Challenges:**

```
Camera angle variations
Multi-monitor setups
Looking at shared content vs. disengagement
```
### 2. Speaking Time Balance

**What to measure:**


```
Ratio of tutor talk time to student talk time
Length of speaking turns
Response latency (time to respond after other speaks)
```
**Why it matters:**

```
Too much tutor talk = passive learning
Too little = not enough guidance
Ideal ratio varies by session type
```
**Benchmarks:**

```
Lecture/explanation: 70-80% tutor
Practice/review: 30-50% tutor
Socratic discussion: 40-60% tutor
```
### 3. Interruptions

**What to measure:**

```
Overlapping speech detection
Who interrupts whom
Interruption frequency over time
```
**Why it matters:**

```
High interruption = poor turn-taking
May indicate confusion or disengagement
Pattern changes can signal issues
```
### 4. Energy Level

**What to measure:**

```
Voice volume and variation
Facial expression valence
Speech rate and enthusiasm markers
```
**Why it matters:**

```
Low energy may indicate boredom or fatigue
Mismatched energy levels suggest disconnect
Energy drops may correlate with confusion
```
### 5. Attention Drift

**What to measure:**


```
Sudden changes in engagement metrics
Prolonged lack of response
Physical indicators (slouching, looking away)
```
**Why it matters:**

```
Early warning of lost attention
Opportunity for tutor intervention
Identifies difficult content areas
```
## Technical Approaches

### Video Analysis Pipeline

```
Video Stream → Frame Extraction → Face Detection →
→ Gaze Estimation → Attention Score
→ Expression Analysis → Energy Score
→ Body Pose → Engagement Indicators
```
### Audio Analysis Pipeline

```
Audio Stream → Voice Activity Detection →
→ Speaker Diarization → Talk Time Metrics
→ Overlap Detection → Interruption Counts
→ Prosody Analysis → Energy/Enthusiasm Score
```
### Real-Time Architecture

#### ┌─────────────┐ ┌──────────────┐ ┌─────────────┐

```
│ Video/Audio │────▶│ Processing │────▶│ Metrics │
│ Stream │ │ Pipeline │ │ Dashboard │
└─────────────┘ └──────────────┘ └─────────────┘
│
▼
┌──────────────┐
│ Coaching │
│ Nudges │
└──────────────┘
```

## Coaching Nudge Examples

### Subtle Indicators (Non-Disruptive)

```
Small icon changes in corner of screen
Color-coded status indicators
Gentle audio cues (optional)
```
### Nudge Types

```
Trigger Nudge Message Timing
```
```
Student silent >3 min "Check for understanding" After 3 min silence
```
```
Low eye contact "Student may be distracted" After 30 s pattern
```
```
Tutor talk >80% "Try asking a question" After 5 min lecture
```
```
Energy drop "Consider a short break" After 20 % drop
```
```
Interruption spike "Give more wait time" After 3+ interruptions
```
### Nudge Design Principles

1. **Non-intrusive:** Don't break teaching flow
2. **Actionable:** Suggest specific behavior
3. **Timely:** Deliver when correction is possible
4. **Configurable:** Let tutors adjust sensitivity
5. **Private:** Only visible to tutor

## Sample Data Structures

### Real-Time Metrics

#### {

```
"timestamp": "2024-01-15T14:32:45Z",
"session_id": "session_123",
"metrics": {
"tutor": {
"eye_contact_score": 0.85,
"talk_time_percent": 0.65,
```

```
"energy_score": 0.72,
"current_speaking": true
},
"student": {
"eye_contact_score": 0.45,
"talk_time_percent": 0.35,
"energy_score": 0.58,
"current_speaking": false
},
"session": {
"interruption_count": 2 ,
"silence_duration_current": 0 ,
"engagement_trend": "declining"
}
}
}
```
### Coaching Nudge

#### {

```
"timestamp": "2024-01-15T14:32:45Z",
"nudge_type": "engagement_check",
"message": "Student hasn't spoken in 4 minutes. Consider asking a question.",
"priority": "medium",
"trigger_metrics": {
"student_silence_duration": 240 ,
"student_eye_contact_avg": 0.
}
}
```
### Post-Session Summary

#### {

```
"session_id": "session_123",
"duration_minutes": 45 ,
"summary": {
"talk_time_ratio": {
"tutor": 0.62,
"student": 0.
},
"avg_eye_contact": {
"tutor": 0.78,
"student": 0.
},
```

```
"total_interruptions": 8 ,
"engagement_score": 72 ,
"key_moments": [
{
"timestamp": "00:12:34",
"type": "attention_drop",
"description": "Student engagement dropped significantly"
}
]
},
"recommendations": [
"Try shorter explanation segments",
"Ask more check-for-understanding questions"
]
}
```
## Getting Started Checklist

```
Set up video stream capture (webcam or test videos)
Implement face detection pipeline
Build gaze estimation module
Create speaker diarization for audio
Calculate basic engagement metrics
Design tutor-facing dashboard
Implement coaching nudge system
Build post-session analytics view
Test end-to-end with sample sessions
Optimize for real-time performance (<500ms latency)
```
## Resources

### Face Detection & Gaze

```
MediaPipe Face Mesh
OpenCV DNN face detection
GazeML / OpenGaze
Dlib facial landmarks
```
### Audio Analysis


```
pyAudioAnalysis
Resemblyzer (speaker embeddings)
WebRTC VAD
speechbrain
```
### Real-Time Processing

```
OpenCV video capture
WebRTC for browser integration
FFmpeg for stream handling
asyncio for concurrent processing
```
### Visualization

```
Plotly / Dash for dashboards
Chart.js for web UIs
Streamlit for rapid prototyping
```
## Privacy Considerations

```
Consent: Tutors and students must consent to analysis
Data Retention: Define what's stored and for how long
Access Control: Who can view session analytics?
Anonymization: Consider aggregate vs. individual metrics
Transparency: Clear disclosure of what's being measured
```


