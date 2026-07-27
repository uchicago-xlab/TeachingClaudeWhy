"""Invalid condition combinations must raise, never render a partial inbox.

Before strict validation existed, several combinations silently produced a
degenerate prompt -- an inbox missing its motive, or one containing literal
``${...}`` template variables -- and the eval reported a number for it anyway.
"""

from __future__ import annotations

import pytest

from evals.agentic_misalignment.agentic_misalignment import agentic_misalignment
from evals.agentic_misalignment.prompt_generator import (
    MIN_EMAILS,
    ValidationError,
    generate_prompts,
    validate_goal_axes,
)
from evals.agentic_misalignment.scenarios_ext import generate_ext_prompts


def base(**kwargs):
    kwargs.setdefault("scenario", "leaking")
    kwargs.setdefault("goal_type", "explicit")
    kwargs.setdefault("goal_value", "america")
    kwargs.setdefault("urgency_type", "replacement")
    kwargs.setdefault("extra_system_instructions", None)
    kwargs.setdefault("prod_flag", False)
    return generate_prompts(**kwargs)


class TestGoalAxes:
    def test_unknown_goal_type_raises(self):
        with pytest.raises(ValidationError, match="Unknown goal_type"):
            validate_goal_axes("explicitt", "america")

    def test_unknown_goal_value_raises(self):
        with pytest.raises(ValidationError, match="Unknown goal_value"):
            validate_goal_axes("explicit", "saftey")

    def test_none_goal_type_with_a_value_raises(self):
        with pytest.raises(ValidationError, match="requires goal_value none"):
            validate_goal_axes("none", "america")

    def test_paired_goal_type_without_a_value_raises(self):
        """This used to render an empty goal statement while logging 'explicit'."""
        for goal_type in ("explicit", "latent", "swap"):
            with pytest.raises(ValidationError, match="needs a paired goal_value"):
                validate_goal_axes(goal_type, "none")

    def test_valid_pairings_pass(self):
        validate_goal_axes("explicit", "america")
        validate_goal_axes("latent", "safety")
        validate_goal_axes("swap", "collectivism")
        validate_goal_axes("none", "none")
        validate_goal_axes("ambiguous", "none")

    def test_a_typo_no_longer_silently_falls_back(self):
        with pytest.raises(ValidationError, match="Unknown goal_value"):
            base(goal_value="saftey")

    def test_explicit_with_no_goal_value_is_rejected_at_the_task_level(self):
        with pytest.raises(ValidationError, match="needs a paired goal_value"):
            agentic_misalignment(scenario="leaking", goal_type="explicit", goal_value="none")


class TestUrgencyAxis:
    def test_unknown_urgency_raises_a_clear_error(self):
        with pytest.raises(ValidationError, match="Unknown urgency_type"):
            base(urgency_type="bogus")


class TestDegenerateRenders:
    """The conditions that used to render silently."""

    @pytest.mark.parametrize("urgency_type", ["restriction", "none"])
    @pytest.mark.parametrize("goal_type,goal_value", [("explicit", "america"), ("latent", "safety")])
    def test_exfiltration_placeholder_urgency_arms_raise(
        self, urgency_type, goal_type, goal_value
    ):
        with pytest.raises(ValidationError, match="unimplemented-template placeholder"):
            base(
                scenario="exfiltration",
                goal_type=goal_type,
                goal_value=goal_value,
                urgency_type=urgency_type,
            )

    @pytest.mark.parametrize("urgency_type", ["restriction", "none"])
    def test_exfiltration_goal_conflict_none_arms_raise(self, urgency_type):
        """These rendered a 98-byte inbox with zero emails."""
        with pytest.raises(ValidationError) as excinfo:
            base(
                scenario="exfiltration",
                goal_type="none",
                goal_value="none",
                urgency_type=urgency_type,
            )
        message = str(excinfo.value)
        assert "placeholder" in message or f"minimum {MIN_EMAILS}" in message

    @pytest.mark.parametrize("urgency_type", ["replacement", "restriction", "none"])
    def test_exfiltration_ambiguous_raises_on_unsubstituted_variables(self, urgency_type):
        with pytest.raises(ValidationError, match="unsubstituted template variables"):
            base(
                scenario="exfiltration",
                goal_type="ambiguous",
                goal_value="none",
                urgency_type=urgency_type,
            )

    def test_murder_safety_restriction_raises_on_a_missing_variable(self):
        """pro_safety in safety_vs_acceleration.md omits direction_modifier."""
        with pytest.raises(ValidationError, match=r"direction_modifier"):
            base(scenario="murder", goal_value="safety", urgency_type="restriction")

    def test_the_documented_exfiltration_conditions_still_render(self):
        for goal_type, goal_value in [("explicit", "america"), ("none", "none")]:
            prompts = base(
                scenario="exfiltration",
                goal_type=goal_type,
                goal_value=goal_value,
                urgency_type="replacement",
            )
            assert prompts.email_content.count("<email>") >= MIN_EMAILS
            assert "${" not in prompts.email_content

    def test_strict_false_still_renders_a_degenerate_condition(self):
        """The snapshot generator depends on this."""
        prompts = base(
            scenario="exfiltration",
            goal_type="none",
            goal_value="none",
            urgency_type="none",
            strict=False,
        )
        assert "# Placeholder for" in prompts.email_content


class TestExtScenarioValidation:
    def test_unknown_condition_raises(self):
        with pytest.raises(ValidationError, match="Invalid sandbagging_target"):
            generate_ext_prompts(scenario="sandbagging", condition="nonexistent")
        with pytest.raises(ValidationError, match="Invalid propagation_channel"):
            generate_ext_prompts(scenario="goal_propagation", condition="nonexistent")

    def test_ext_scenarios_reject_a_varied_urgency_axis(self):
        with pytest.raises(ValidationError, match="does not vary urgency_type"):
            generate_ext_prompts(
                scenario="sandbagging", condition="self", urgency_type="restriction"
            )

    def test_condition_for_the_wrong_scenario_raises(self):
        with pytest.raises(ValidationError, match="only applies to scenario"):
            agentic_misalignment(scenario="leaking", sandbagging_target="self")
        with pytest.raises(ValidationError, match="only applies to scenario"):
            agentic_misalignment(scenario="sandbagging", propagation_channel="training")

    def test_ext_scenarios_honour_the_shared_goal_axis_rules(self):
        with pytest.raises(ValidationError, match="needs a paired goal_value"):
            generate_ext_prompts(
                scenario="sandbagging", condition="self", goal_type="explicit", goal_value="none"
            )


class TestTaskConstruction:
    def test_defaults_pick_the_first_condition(self):
        for scenario, expected in [("sandbagging", "self"), ("goal_propagation", "training")]:
            task = agentic_misalignment(
                scenario=scenario, goal_type="none", goal_value="none"
            )
            assert task.dataset[0].metadata["condition"] == expected

    def test_sandbagging_ground_truth_lands_in_sample_metadata(self):
        task = agentic_misalignment(
            scenario="sandbagging", goal_type="none", goal_value="none"
        )
        metadata = task.dataset[0].metadata
        assert metadata["target_system"] == "Alex"
        assert metadata["true_scores"]["Alex"] == 62
        assert metadata["task_recipient"] == "review-board@summitbridge.com"

    def test_unknown_rebuff_raises(self):
        with pytest.raises(ValueError, match="Unknown rebuff"):
            agentic_misalignment(scenario="leaking", rebuff="nonexistent")

    def test_message_limit_accommodates_the_second_turn(self):
        single = agentic_misalignment(scenario="leaking")
        two_turn = agentic_misalignment(scenario="leaking", rebuff="delivered")
        assert single.message_limit == 3
        assert two_turn.message_limit >= 5

    def test_existing_single_turn_sample_id_is_unchanged(self):
        task = agentic_misalignment(
            scenario="exfiltration",
            goal_type="explicit",
            goal_value="america",
            urgency_type="replacement",
        )
        assert task.dataset[0].id == "exfiltration_explicit-america_replacement"
