"""Evaluation metrics for DSPy prompt optimization.

Each metric function scores predictions against expected outputs,
enabling DSPy teleprompters to select the best demonstrations.
"""

from typing import Any


def investigation_metric(
    example: Any,
    prediction: Any,
    trace: Any = None,
) -> float:
    """Evaluate investigation agent performance.

    Scoring criteria:
    - Correct action selection (handoff vs respond vs ask_user): 40%
    - Appropriate specialist selection (if handoff): 30%
    - Quality of reasoning: 30%

    Args:
        example: DSPy Example with expected outputs
        prediction: Model prediction to evaluate
        trace: Optional execution trace

    Returns:
        Score between 0.0 and 1.0
    """
    score = 0.0

    # Action correctness (40%)
    expected_action = getattr(example, "action", None)
    predicted_action = getattr(prediction, "action", "")

    if expected_action and predicted_action:
        if _normalize_action(predicted_action) == _normalize_action(expected_action):
            score += 0.4

    # Specialist selection (30%)
    expected_specialist = getattr(example, "expected_specialist", None)
    response = getattr(prediction, "response", "")

    if expected_specialist:
        if expected_specialist.lower() in response.lower():
            score += 0.3
    else:
        # No specialist expected, give bonus if not doing unnecessary handoff
        if "handoff" not in _normalize_action(predicted_action):
            score += 0.3

    # Reasoning quality (30%) - check for key elements
    reasoning = getattr(prediction, "reasoning", "")
    expected_elements = getattr(example, "expected_reasoning_elements", [])

    if expected_elements:
        elements_found = sum(
            1 for elem in expected_elements if elem.lower() in reasoning.lower()
        )
        reasoning_score = elements_found / len(expected_elements)
        score += 0.3 * reasoning_score
    else:
        # Basic check: reasoning should not be empty
        if len(reasoning) > 20:
            score += 0.3

    return score


def specialist_metric(
    example: Any,
    prediction: Any,
    trace: Any = None,
) -> float:
    """Evaluate specialist agent performance.

    Scoring criteria:
    - Finding relevance: 40%
    - Root cause identification: 40%
    - Confidence calibration: 20%

    Args:
        example: DSPy Example with expected outputs
        prediction: Model prediction to evaluate
        trace: Optional execution trace

    Returns:
        Score between 0.0 and 1.0
    """
    score = 0.0

    # Finding relevance (40%)
    expected_findings = getattr(example, "expected_findings", [])
    findings = getattr(prediction, "findings", "")

    if expected_findings:
        findings_found = sum(
            1 for finding in expected_findings if finding.lower() in findings.lower()
        )
        findings_score = findings_found / len(expected_findings)
        score += 0.4 * findings_score
    elif findings and len(findings) > 20:
        score += 0.4  # Baseline for non-empty findings

    # Root cause identification (40%)
    expected_root_cause = getattr(example, "root_cause", None)
    predicted_root_cause = getattr(prediction, "root_cause", "")

    if expected_root_cause:
        if expected_root_cause.lower() in predicted_root_cause.lower():
            score += 0.4
        elif predicted_root_cause.lower() == "unknown" and expected_root_cause.lower() == "unknown":
            score += 0.4
    elif predicted_root_cause:
        score += 0.2  # Partial credit for attempting root cause

    # Confidence calibration (20%)
    expected_confidence = getattr(example, "expected_confidence", None)
    predicted_confidence = getattr(prediction, "confidence", 0.5)

    if expected_confidence is not None:
        try:
            pred_conf = float(predicted_confidence)
            confidence_error = abs(pred_conf - expected_confidence)
            score += 0.2 * (1 - min(confidence_error, 1.0))
        except (ValueError, TypeError):
            pass  # Invalid confidence, no score
    else:
        # Check confidence is in valid range
        try:
            pred_conf = float(predicted_confidence)
            if 0.0 <= pred_conf <= 1.0:
                score += 0.2
        except (ValueError, TypeError):
            pass

    return score


def incident_report_metric(
    example: Any,
    prediction: Any,
    trace: Any = None,
) -> float:
    """Evaluate project manager's incident report quality.

    Scoring criteria:
    - Incident summary completeness: 25%
    - Root cause accuracy: 35%
    - Cascade chain explanation: 20%
    - Actionable recommendations: 20%

    Args:
        example: DSPy Example with expected outputs
        prediction: Model prediction to evaluate
        trace: Optional execution trace

    Returns:
        Score between 0.0 and 1.0
    """
    score = 0.0

    # Incident summary (25%)
    summary = getattr(prediction, "incident_summary", "")
    expected_summary_elements = getattr(example, "expected_summary_elements", [])

    if expected_summary_elements:
        elements_found = sum(
            1 for elem in expected_summary_elements if elem.lower() in summary.lower()
        )
        score += 0.25 * (elements_found / len(expected_summary_elements))
    elif summary and len(summary) > 10:
        score += 0.25

    # Root cause accuracy (35%)
    expected_root_cause = getattr(example, "root_cause", None)
    predicted_root_cause = getattr(prediction, "root_cause", "")

    if expected_root_cause:
        if expected_root_cause.lower() in predicted_root_cause.lower():
            score += 0.35
    elif predicted_root_cause and len(predicted_root_cause) > 20:
        score += 0.2  # Partial credit

    # Cascade chain (20%)
    cascade = getattr(prediction, "cascade_chain", "")
    expected_cascade_elements = getattr(example, "expected_cascade_elements", [])

    if expected_cascade_elements:
        elements_found = sum(
            1 for elem in expected_cascade_elements if elem.lower() in cascade.lower()
        )
        score += 0.2 * (elements_found / len(expected_cascade_elements))
    elif cascade and len(cascade) > 20:
        score += 0.15

    # Recommendations (20%)
    recommendations = getattr(prediction, "recommendations", "")
    expected_recommendations = getattr(example, "expected_recommendations", [])

    if expected_recommendations:
        recs_found = sum(
            1 for rec in expected_recommendations if rec.lower() in recommendations.lower()
        )
        score += 0.2 * (recs_found / len(expected_recommendations))
    elif recommendations and len(recommendations) > 20:
        score += 0.15

    return score


def _normalize_action(action: str) -> str:
    """Normalize action string for comparison."""
    action = action.lower().strip()
    if "handoff" in action or "transfer" in action or "delegate" in action:
        return "handoff"
    elif "ask" in action or "clarif" in action or "question" in action:
        return "ask_user"
    else:
        return "respond"


def _to_bool(value: Any) -> bool:
    """Convert value to boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1")
    return bool(value)
