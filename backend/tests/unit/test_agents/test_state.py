import operator
from app.agents.state import AgentState


def test_errors_reducer_accumulates():
    """Verify the errors field uses operator.add for parallel-safe accumulation."""
    import typing
    hints = typing.get_type_hints(AgentState, include_extras=True)
    errors_hint = hints["errors"]
    # Should be Annotated[list[str], operator.add]
    assert hasattr(errors_hint, "__metadata__")
    assert operator.add in errors_hint.__metadata__


def test_agent_state_has_required_keys():
    """Verify all required keys are present in AgentState."""
    required = [
        "mode", "top_n", "run_id", "candidate_tickers",
        "technical_scores", "fundamental_scores", "sentiment_scores",
        "catalyst_scores", "risk_metrics", "trade_signals", "errors",
    ]
    hints = AgentState.__annotations__
    for key in required:
        assert key in hints, f"Missing key: {key}"
