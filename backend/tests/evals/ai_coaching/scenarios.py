"""Realistic tutoring session scenarios for AI coaching suggestion evals.

Each scenario is a frozen AICoachingContext snapshot representing a specific
moment in a tutoring session.  Scenarios cover every coaching rule, common
ambient situations, and edge cases.

The ``SCENARIOS`` list is the canonical set of eval inputs.  Both the
deterministic checks and the LLM-as-judge grading run against every scenario.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from app.ai_coaching.context import AICoachingContext, AISuggestion
from app.transcription.models import FinalUtterance


@dataclass(frozen=True)
class EvalScenario:
    """A named scenario with context, grading criteria, and metadata."""

    id: str
    name: str
    description: str
    context: AICoachingContext
    # Which coaching rule triggered this, if any
    triggered_rule: str = ""
    # Tags for filtering / grouping
    tags: tuple = ()
    # Hard requirements the suggestion MUST satisfy (deterministic checks)
    must_reference_topic: bool = True
    must_have_suggested_prompt: bool = True
    must_not_contain_answer: bool = True
    # What the suggested_prompt should address (for LLM judge)
    ideal_prompt_intent: str = ""


def _utt(role: str, text: str, start: float, end: float, **kw) -> FinalUtterance:
    return FinalUtterance(role=role, text=text, start_time=start, end_time=end, **kw)


# ---------------------------------------------------------------------------
# Rule-triggered scenarios
# ---------------------------------------------------------------------------

SCENARIO_CHECK_UNDERSTANDING_MATH = EvalScenario(
    id="rule-check-understanding-math",
    name="Tutor monologue about fractions",
    description=(
        "Tutor has been explaining fraction simplification for 2+ minutes. "
        "Student said they didn't understand but tutor kept going."
    ),
    triggered_rule="check_for_understanding",
    tags=("rule", "math", "overtalk"),
    ideal_prompt_intent=(
        "Ask the student a specific question about fraction simplification "
        "that checks whether they understood why both numerator and denominator "
        "get divided. Reference what the student said."
    ),
    context=AICoachingContext(
        session_type="math",
        elapsed_seconds=480,
        recent_utterances=[
            _utt("tutor", "So when we simplify fractions, we need to find the greatest common factor of the numerator and denominator.", 420, 428),
            _utt("tutor", "For example, with six eighths, both six and eight are divisible by two.", 429, 435),
            _utt("student", "I dont really get why we divide both of them though", 437, 441),
            _utt("tutor", "Well because if you divide both the top and bottom by the same number, the fraction stays equivalent. Its like cutting a pizza into fewer but bigger slices.", 443, 455),
            _utt("tutor", "So six divided by two is three, and eight divided by two is four, giving us three fourths.", 456, 463),
        ],
        uncertainty_score=0.72,
        uncertainty_topic="fraction simplification",
        tutor_talk_ratio=0.78,
        student_talk_ratio=0.22,
        student_engagement_score=0.45,
        student_attention_state="SCREEN_ENGAGED",
        student_time_in_attention_state=12,
        time_since_student_spoke=22,
        tutor_monologue_seconds=135,
        tutor_turn_count=14,
        student_turn_count=6,
        student_energy_score=0.35,
        student_energy_drop=0.28,
        engagement_trend="declining",
        active_rule_nudge="check_for_understanding",
        active_rule_message="You've been talking for a while and the student has been quiet. Consider asking a question to check understanding.",
        topic_keywords=["fractions", "denominator", "simplify", "divide", "equivalent"],
    ),
)

SCENARIO_CHECK_UNDERSTANDING_SCIENCE = EvalScenario(
    id="rule-check-understanding-science",
    name="Tutor lecturing about photosynthesis",
    description="Tutor explaining photosynthesis for too long without checking in.",
    triggered_rule="check_for_understanding",
    tags=("rule", "science", "overtalk"),
    ideal_prompt_intent=(
        "Ask the student to explain back one part of what the tutor said "
        "about photosynthesis. Should reference light reactions or chlorophyll."
    ),
    context=AICoachingContext(
        session_type="science",
        elapsed_seconds=600,
        recent_utterances=[
            _utt("tutor", "So the chloroplasts are where photosynthesis actually happens inside the cell.", 540, 547),
            _utt("tutor", "Light energy hits the chlorophyll molecules and that kicks off the light reactions.", 548, 556),
            _utt("tutor", "The light reactions split water molecules and produce ATP and NADPH.", 557, 564),
            _utt("student", "Okay", 565, 566),
            _utt("tutor", "Then the Calvin cycle uses that ATP and NADPH to fix carbon dioxide into glucose.", 567, 575),
        ],
        tutor_talk_ratio=0.85,
        student_talk_ratio=0.15,
        time_since_student_spoke=10,
        tutor_monologue_seconds=35,
        tutor_turn_count=18,
        student_turn_count=4,
        engagement_trend="declining",
        active_rule_nudge="check_for_understanding",
        active_rule_message="You've been talking for a while and the student has been quiet.",
        topic_keywords=["photosynthesis", "chloroplast", "calvin", "ATP", "light"],
    ),
)

SCENARIO_STUDENT_OFF_TASK = EvalScenario(
    id="rule-student-off-task",
    name="Student looking away for 50 seconds",
    description="Student has been off-camera/looking away while tutor explains algebra.",
    triggered_rule="student_off_task",
    tags=("rule", "math", "disengagement"),
    ideal_prompt_intent=(
        "Gently re-engage the student by asking a direct question about the "
        "algebra problem. Should sound warm, not accusatory."
    ),
    context=AICoachingContext(
        session_type="math",
        elapsed_seconds=360,
        recent_utterances=[
            _utt("tutor", "So for this equation we need to isolate x on one side.", 300, 306),
            _utt("tutor", "First subtract three from both sides.", 307, 311),
            _utt("student", "Uh huh", 312, 313),
            _utt("tutor", "Then divide both sides by two to get x equals four.", 315, 320),
        ],
        tutor_talk_ratio=0.70,
        student_talk_ratio=0.30,
        student_attention_state="OFF_TASK_AWAY",
        student_time_in_attention_state=50,
        time_since_student_spoke=47,
        active_rule_nudge="student_off_task",
        active_rule_message="Student appears to have been away from the screen for a while.",
        topic_keywords=["equation", "isolate", "variable", "subtract"],
    ),
)

SCENARIO_INTERRUPTION_BURST = EvalScenario(
    id="rule-interruption-burst",
    name="Tutor cutting off student repeatedly",
    description="Tutor has interrupted student 3 times in quick succession during essay discussion.",
    triggered_rule="interruption_burst",
    tags=("rule", "writing", "interruptions"),
    ideal_prompt_intent=(
        "Invite the student to finish their thought. Should feel like a natural "
        "pause, not an apology."
    ),
    context=AICoachingContext(
        session_type="writing",
        elapsed_seconds=420,
        recent_utterances=[
            _utt("student", "So I was thinking for the conclusion maybe we could", 390, 395),
            _utt("tutor", "Right but you really need to tie it back to the thesis", 394, 399),
            _utt("student", "Oh okay well I thought that if we", 400, 403),
            _utt("tutor", "No the key thing is restating your main argument", 402, 407),
            _utt("student", "Yeah but", 408, 409),
            _utt("tutor", "Let me show you what I mean", 409, 412),
        ],
        tutor_talk_ratio=0.62,
        student_talk_ratio=0.38,
        recent_hard_interruptions=3,
        tutor_cutoffs=2,
        active_overlap_state="hard",
        active_rule_nudge="interruption_burst",
        active_rule_message="You've interrupted the student several times in quick succession.",
        topic_keywords=["conclusion", "thesis", "essay", "argument"],
    ),
)

SCENARIO_RE_ENGAGE_SILENCE = EvalScenario(
    id="rule-re-engage-silence",
    name="Dead air — both quiet for 45 seconds",
    description="Both tutor and student silent for 45 seconds while discussing a reading passage.",
    triggered_rule="re_engage_silence",
    tags=("rule", "reading", "silence"),
    ideal_prompt_intent=(
        "Break the silence with a low-pressure question about the reading. "
        "Should be easy to answer — not a pop quiz."
    ),
    context=AICoachingContext(
        session_type="reading",
        elapsed_seconds=540,
        recent_utterances=[
            _utt("tutor", "So what did you think about what happened in chapter three", 480, 486),
            _utt("student", "It was interesting I guess", 488, 490),
        ],
        tutor_talk_ratio=0.50,
        student_talk_ratio=0.50,
        mutual_silence_seconds=50,
        student_attention_state="CAMERA_FACING",
        student_time_in_attention_state=50,
        active_rule_nudge="re_engage_silence",
        active_rule_message="Both you and the student have been quiet for a while.",
        topic_keywords=["chapter", "three", "character", "story"],
    ),
)

SCENARIO_TECH_CHECK = EvalScenario(
    id="rule-tech-check",
    name="Extended silence + face missing",
    description="Mutual silence for 30 seconds and student's face is not visible.",
    triggered_rule="tech_check",
    tags=("rule", "tech"),
    ideal_prompt_intent=(
        "Quick check-in asking if the student can hear/see the tutor. "
        "Should not sound panicked."
    ),
    context=AICoachingContext(
        session_type="general",
        elapsed_seconds=300,
        recent_utterances=[
            _utt("tutor", "Can you see my screen okay", 260, 263),
            _utt("student", "Yeah I can see it", 265, 267),
        ],
        tutor_talk_ratio=0.55,
        student_talk_ratio=0.45,
        mutual_silence_seconds=33,
        student_attention_state="FACE_MISSING",
        student_time_in_attention_state=30,
        active_rule_nudge="tech_check",
        active_rule_message="Extended silence and a participant may be off-camera.",
        topic_keywords=["screen", "share"],
    ),
)

SCENARIO_ENCOURAGE_RESPONSE = EvalScenario(
    id="rule-encourage-student-response",
    name="Student quiet but present",
    description="Student is on camera but hasn't spoken in 70 seconds. Tutor isn't dominating.",
    triggered_rule="encourage_student_response",
    tags=("rule", "general", "silence"),
    ideal_prompt_intent=(
        "Ask the student a direct but warm question to draw them in. "
        "Reference the topic. Should not feel like a demand."
    ),
    context=AICoachingContext(
        session_type="general",
        elapsed_seconds=400,
        recent_utterances=[
            _utt("tutor", "So thats basically how the water cycle works", 310, 316),
            _utt("student", "Oh okay", 318, 319),
            _utt("tutor", "Does that part make sense", 320, 322),
        ],
        tutor_talk_ratio=0.50,
        student_talk_ratio=0.50,
        time_since_student_spoke=78,
        student_attention_state="CAMERA_FACING",
        student_time_in_attention_state=60,
        active_rule_nudge="encourage_student_response",
        active_rule_message="The student has been quiet for a while despite being present.",
        topic_keywords=["water", "cycle", "evaporation", "condensation"],
    ),
)

SCENARIO_MOMENTUM_LOSS = EvalScenario(
    id="rule-session-momentum-loss",
    name="Session energy fading at 12 minutes",
    description="Engagement declining, interaction slowed, both present but low energy.",
    triggered_rule="session_momentum_loss",
    tags=("rule", "general", "momentum"),
    ideal_prompt_intent=(
        "Suggest shifting approach, trying a different angle, or offering a break. "
        "Should inject energy without pressure."
    ),
    context=AICoachingContext(
        session_type="math",
        elapsed_seconds=720,
        recent_utterances=[
            _utt("tutor", "Okay lets try another one", 690, 693),
            _utt("student", "Okay", 695, 696),
            _utt("tutor", "So what is fifteen percent of eighty", 698, 702),
        ],
        tutor_talk_ratio=0.60,
        student_talk_ratio=0.40,
        student_engagement_score=0.35,
        engagement_trend="declining",
        student_energy_score=0.25,
        student_energy_drop=0.40,
        tutor_turn_count=22,
        student_turn_count=18,
        mutual_silence_seconds=18,
        active_rule_nudge="session_momentum_loss",
        active_rule_message="Session momentum appears to be fading.",
        topic_keywords=["percent", "percentage", "calculate"],
    ),
)

# ---------------------------------------------------------------------------
# Ambient scenarios (no rule fired)
# ---------------------------------------------------------------------------

SCENARIO_AMBIENT_UNCERTAINTY = EvalScenario(
    id="ambient-high-uncertainty",
    name="Student confused about photosynthesis role of sunlight",
    description="High uncertainty detected but no coaching rule fired.",
    triggered_rule="",
    tags=("ambient", "science", "uncertainty"),
    ideal_prompt_intent=(
        "Probe the student's mental model of sunlight in photosynthesis. "
        "Don't re-explain — find what they think 'eating sunlight' means."
    ),
    context=AICoachingContext(
        session_type="science",
        elapsed_seconds=300,
        recent_utterances=[
            _utt("tutor", "So photosynthesis converts carbon dioxide and water into glucose and oxygen", 280, 288),
            _utt("student", "Wait so the plant is like eating the sunlight", 290, 294),
            _utt("tutor", "Not exactly the sunlight is the energy source that drives the chemical reaction", 295, 300),
        ],
        uncertainty_score=0.68,
        uncertainty_topic="role of sunlight in photosynthesis",
        tutor_talk_ratio=0.60,
        student_talk_ratio=0.40,
        student_energy_score=0.55,
        topic_keywords=["photosynthesis", "sunlight", "glucose", "carbon"],
    ),
)

SCENARIO_AMBIENT_ENERGY_DROP = EvalScenario(
    id="ambient-energy-drop",
    name="Student energy dropped noticeably",
    description="Student's vocal energy fell 35% from baseline. Session going okay otherwise.",
    triggered_rule="",
    tags=("ambient", "math", "energy"),
    ideal_prompt_intent=(
        "Acknowledge student effort, offer to change pace, or check how they're feeling. "
        "Should be encouraging, not diagnostic."
    ),
    context=AICoachingContext(
        session_type="math",
        elapsed_seconds=900,
        recent_utterances=[
            _utt("tutor", "Great now try this next one", 880, 883),
            _utt("student", "Um okay so I multiply both sides by x", 885, 890),
            _utt("tutor", "Good and then what", 892, 894),
            _utt("student", "Then... I dont know divide maybe", 896, 900),
        ],
        tutor_talk_ratio=0.45,
        student_talk_ratio=0.55,
        student_energy_score=0.28,
        student_energy_drop=0.35,
        engagement_trend="declining",
        tutor_turn_count=24,
        student_turn_count=22,
        topic_keywords=["multiply", "divide", "equation", "solve"],
    ),
)

SCENARIO_AMBIENT_SESSION_GOING_WELL = EvalScenario(
    id="ambient-session-going-well",
    name="Good session, balanced turns, student engaged",
    description="Everything is fine. LLM should have low confidence or skip.",
    triggered_rule="",
    tags=("ambient", "math", "positive"),
    ideal_prompt_intent=(
        "Either a low-confidence suggestion to probe deeper, or the LLM should "
        "indicate there's nothing urgent."
    ),
    must_reference_topic=False,
    context=AICoachingContext(
        session_type="math",
        elapsed_seconds=200,
        recent_utterances=[
            _utt("tutor", "Great so what would you do next", 190, 193),
            _utt("student", "I would multiply both sides by three", 194, 197),
            _utt("tutor", "Perfect and then what", 198, 200),
        ],
        tutor_talk_ratio=0.45,
        student_talk_ratio=0.55,
        student_engagement_score=0.75,
        engagement_trend="stable",
        tutor_turn_count=8,
        student_turn_count=7,
        topic_keywords=["multiply", "equation", "solve"],
    ),
)

SCENARIO_AMBIENT_TURN_IMBALANCE = EvalScenario(
    id="ambient-turn-imbalance",
    name="Tutor dominating turns but no rule fired yet",
    description="Tutor has 18 turns to student's 5. Not quite at rule threshold.",
    triggered_rule="",
    tags=("ambient", "general", "overtalk"),
    ideal_prompt_intent=(
        "Ask an open-ended question that gives the student more room. "
        "Reference the history topic being discussed."
    ),
    context=AICoachingContext(
        session_type="general",
        elapsed_seconds=500,
        recent_utterances=[
            _utt("tutor", "And then after the revolution the government was restructured", 470, 478),
            _utt("tutor", "They created a new constitution based on democratic principles", 479, 486),
            _utt("student", "Yeah", 487, 488),
            _utt("tutor", "And the first elections were held in seventeen ninety two", 489, 496),
        ],
        tutor_talk_ratio=0.72,
        student_talk_ratio=0.28,
        tutor_turn_count=18,
        student_turn_count=5,
        tutor_monologue_seconds=26,
        topic_keywords=["revolution", "constitution", "democracy", "elections"],
    ),
)


# ---------------------------------------------------------------------------
# Complete scenario list
# ---------------------------------------------------------------------------

SCENARIOS: list[EvalScenario] = [
    # Rule-triggered
    SCENARIO_CHECK_UNDERSTANDING_MATH,
    SCENARIO_CHECK_UNDERSTANDING_SCIENCE,
    SCENARIO_STUDENT_OFF_TASK,
    SCENARIO_INTERRUPTION_BURST,
    SCENARIO_RE_ENGAGE_SILENCE,
    SCENARIO_TECH_CHECK,
    SCENARIO_ENCOURAGE_RESPONSE,
    SCENARIO_MOMENTUM_LOSS,
    # Ambient
    SCENARIO_AMBIENT_UNCERTAINTY,
    SCENARIO_AMBIENT_ENERGY_DROP,
    SCENARIO_AMBIENT_SESSION_GOING_WELL,
    SCENARIO_AMBIENT_TURN_IMBALANCE,
]
