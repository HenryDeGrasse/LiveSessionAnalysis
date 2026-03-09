import pytest
from app.video_processor.expression_analyzer import analyze_expression, ExpressionResult


def _make_landmarks(count=478, default=(0.5, 0.5, 0.0)):
    return [default] * count


def _set_smile(landmarks, mouth_width_factor=1.0):
    """Set mouth landmarks to simulate different expressions.

    mouth_width_factor > 1 = wider mouth (smile)
    mouth_width_factor < 1 = narrower mouth (neutral/frown)
    """
    # Mouth corners
    center_x = 0.5
    half_width = 0.05 * mouth_width_factor
    landmarks[61] = (center_x - half_width, 0.7, 0.0)   # MOUTH_LEFT
    landmarks[291] = (center_x + half_width, 0.7, 0.0)  # MOUTH_RIGHT
    # Upper/lower lip
    landmarks[13] = (0.5, 0.68, 0.0)  # UPPER_LIP
    landmarks[14] = (0.5, 0.72, 0.0)  # LOWER_LIP

    # Eyebrow and eye references
    landmarks[107] = (0.4, 0.35, 0.0)  # LEFT_EYEBROW_INNER
    landmarks[336] = (0.6, 0.35, 0.0)  # RIGHT_EYEBROW_INNER
    landmarks[159] = (0.4, 0.40, 0.0)  # LEFT_EYE_TOP
    landmarks[386] = (0.6, 0.40, 0.0)  # RIGHT_EYE_TOP

    # Face height references
    landmarks[10] = (0.5, 0.2, 0.0)   # FOREHEAD
    landmarks[1] = (0.5, 0.6, 0.0)    # NOSE_TIP

    return landmarks


def test_smile_has_higher_valence():
    """A wider mouth (smile) should produce higher valence than neutral."""
    neutral = _make_landmarks()
    neutral = _set_smile(neutral, mouth_width_factor=1.0)

    smiling = _make_landmarks()
    smiling = _set_smile(smiling, mouth_width_factor=2.5)

    neutral_result = analyze_expression(neutral)
    smile_result = analyze_expression(smiling)

    assert smile_result.valence > neutral_result.valence


def test_valence_in_range():
    """Valence should be between 0 and 1."""
    landmarks = _make_landmarks()
    landmarks = _set_smile(landmarks, mouth_width_factor=1.0)
    result = analyze_expression(landmarks)
    assert 0.0 <= result.valence <= 1.0


def test_insufficient_landmarks():
    """With fewer than 468 landmarks, should return neutral valence."""
    landmarks = _make_landmarks(count=100)
    result = analyze_expression(landmarks)
    assert result.valence == 0.5


def test_smile_ratio_increases_with_width():
    """Smile ratio should increase with mouth width."""
    narrow = _make_landmarks()
    narrow = _set_smile(narrow, mouth_width_factor=0.5)

    wide = _make_landmarks()
    wide = _set_smile(wide, mouth_width_factor=3.0)

    narrow_result = analyze_expression(narrow)
    wide_result = analyze_expression(wide)

    assert wide_result.smile_ratio > narrow_result.smile_ratio
