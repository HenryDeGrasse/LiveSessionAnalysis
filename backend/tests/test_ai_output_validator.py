"""Tests for AIOutputValidator: answer leakage prevention."""
from __future__ import annotations

import pytest

from app.ai_coaching.output_validator import AIOutputValidator, CoachingSuggestion


class TestAnswerPatternRejection:
    """Suggestions containing direct answers should be rejected."""

    def test_the_answer_is_rejected(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(suggestion="The answer is 42")
        assert validator.validate(s) is None

    def test_the_solution_is_rejected(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(suggestion="The solution is to add 3 and 5")
        assert validator.validate(s) is None

    def test_it_equals_rejected(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(suggestion="It equals seven")
        assert validator.validate(s) is None

    def test_the_correct_answer_rejected(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(suggestion="The correct answer would be 10")
        assert validator.validate(s) is None

    def test_you_should_tell_them_rejected(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(suggestion="You should tell them the value")
        assert validator.validate(s) is None

    def test_answer_pattern_in_prompt_rejected(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(
            suggestion="Ask a guiding question",
            suggested_prompt="The answer is 5, so ask about it",
        )
        assert validator.validate(s) is None

    def test_case_insensitive(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(suggestion="THE ANSWER IS forty-two")
        assert validator.validate(s) is None


class TestPromptOnlyPatternRejection:
    """Prompt-only patterns should reject only when in suggested_prompt."""

    def test_equals_number_in_prompt_rejected(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(
            suggestion="Guide them to the answer",
            suggested_prompt="What if x = 5?",
        )
        assert validator.validate(s) is None

    def test_equals_negative_number_in_prompt_rejected(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(
            suggestion="Try a different approach",
            suggested_prompt="The result = -3 so ask why",
        )
        assert validator.validate(s) is None

    def test_tell_them_that_in_prompt_rejected(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(
            suggestion="Explain the concept",
            suggested_prompt="Tell them that the derivative is 2x",
        )
        assert validator.validate(s) is None

    def test_equals_number_in_suggestion_not_rejected(self):
        """Prompt-only patterns should NOT trigger on suggestion text."""
        validator = AIOutputValidator()
        s = CoachingSuggestion(suggestion="Ask: what if x = 5?")
        # = 5 is a prompt-only pattern, should only reject in suggested_prompt
        assert validator.validate(s) is not None


class TestTeachingQuestionsAllowed:
    """Pedagogical/teaching questions should NOT be rejected."""

    def test_guiding_question(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(
            suggestion="Ask the student what they think the derivative is",
        )
        assert validator.validate(s) is not None

    def test_what_do_you_think_derivative_is(self):
        """'what do you think the derivative is?' must NOT be rejected."""
        validator = AIOutputValidator()
        s = CoachingSuggestion(
            suggestion="What do you think the derivative is?",
        )
        assert validator.validate(s) is not None

    def test_socratic_approach(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(
            suggestion="Try asking: can you walk me through step 2?",
            suggested_prompt="Can you walk me through step 2?",
        )
        assert validator.validate(s) is not None

    def test_encourage_exploration(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(
            suggestion="Encourage them to try a different approach",
            suggested_prompt="What would happen if you tried using substitution?",
        )
        assert validator.validate(s) is not None

    def test_no_prompt(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(
            suggestion="The student seems confused about integration by parts",
        )
        assert validator.validate(s) is not None


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_suggestion(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(suggestion="")
        assert validator.validate(s) is not None

    def test_empty_prompt(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(suggestion="Guide them", suggested_prompt="")
        assert validator.validate(s) is not None

    def test_equals_in_text_no_number(self):
        """'= x' without a digit should not trigger prompt-only pattern."""
        validator = AIOutputValidator()
        s = CoachingSuggestion(
            suggestion="Good approach",
            suggested_prompt="What does f(x) = g(x) mean?",
        )
        assert validator.validate(s) is not None

    def test_decimal_number_rejected(self):
        validator = AIOutputValidator()
        s = CoachingSuggestion(
            suggestion="Ask about the result",
            suggested_prompt="Since y = 3.14 we know",
        )
        assert validator.validate(s) is None
