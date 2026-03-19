import structlog
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.agents.state import AgentState
from app.agents.nodes.screener import screener_node
from app.agents.nodes.sector_rotation import sector_rotation_node
from app.agents.nodes.technical import technical_node
from app.agents.nodes.fundamental import fundamental_node
from app.agents.nodes.sentiment import sentiment_node
from app.agents.nodes.catalyst import catalyst_node
from app.agents.nodes.risk_manager import risk_manager_node
from app.agents.nodes.synthesizer import synthesizer_node

logger = structlog.get_logger()


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # Add all nodes
    graph.add_node("screener", screener_node)
    graph.add_node("sector_rotation", sector_rotation_node)
    graph.add_node("technical", technical_node)
    graph.add_node("fundamental", fundamental_node)
    graph.add_node("sentiment", sentiment_node)
    graph.add_node("catalyst", catalyst_node)
    graph.add_node("risk_manager", risk_manager_node)
    graph.add_node("synthesizer", synthesizer_node)

    # Entry point
    graph.set_entry_point("screener")

    # Screener → sector rotation (filters candidates to favored sectors)
    graph.add_edge("screener", "sector_rotation")

    # Sector rotation → 4 parallel analysis nodes
    graph.add_edge("sector_rotation", "technical")
    graph.add_edge("sector_rotation", "fundamental")
    graph.add_edge("sector_rotation", "sentiment")
    graph.add_edge("sector_rotation", "catalyst")

    # All 4 parallel nodes → risk manager
    graph.add_edge("technical", "risk_manager")
    graph.add_edge("fundamental", "risk_manager")
    graph.add_edge("sentiment", "risk_manager")
    graph.add_edge("catalyst", "risk_manager")

    # Risk manager → synthesizer → end
    graph.add_edge("risk_manager", "synthesizer")
    graph.add_edge("synthesizer", END)

    # MemorySaver checkpoints state at each node boundary within a run.
    # Each run uses a unique thread_id so states never cross-contaminate.
    # (Upgrade to PostgresSaver in Phase 3 for cross-restart persistence.)
    return graph.compile(checkpointer=MemorySaver())


# Singleton compiled graph
trading_graph = build_graph()
