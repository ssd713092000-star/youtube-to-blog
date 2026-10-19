from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from langgraph.types import RetryPolicy

from app.core.errors import BudgetExceeded, NonRetryableError
from app.graph.context import JobContext
from app.graph.nodes.ingest import ingest_video, route_after_ingest
from app.graph.nodes.publish import publish, route_after_publish, social_and_store
from app.graph.nodes.quality import fact_check, revise_draft, route_after_fact_check
from app.graph.nodes.review import human_review, prepare_metadata, route_after_review
from app.graph.nodes.writing import assemble_post, clean_transcript, fan_out_sections, plan_outline, write_section
from app.graph.state import BlogState

STEPS = [
    "ingest_video", "clean_transcript", "plan_outline", "write_section", "assemble_post", "fact_check",
    "revise_draft", "prepare_metadata", "human_review", "publish", "social_and_store",
]


def _retryable(e: Exception) -> bool:
    if isinstance(e, (BudgetExceeded, NonRetryableError, KeyError, ValueError, TypeError)):
        return False
    return True


LLM_RETRY = RetryPolicy(max_attempts=3, initial_interval=2.0, backoff_factor=3.0, retry_on=_retryable)
FETCH_RETRY = RetryPolicy(max_attempts=4, initial_interval=5.0, backoff_factor=3.0, retry_on=_retryable)


def build_graph(checkpointer: BaseCheckpointSaver | None, store: BaseStore | None) -> CompiledStateGraph:
    b = StateGraph(BlogState, context_schema=JobContext)

    b.add_node("ingest_video", ingest_video, retry_policy=FETCH_RETRY)
    b.add_node("clean_transcript", clean_transcript, retry_policy=LLM_RETRY)
    b.add_node("plan_outline", plan_outline, retry_policy=LLM_RETRY)
    b.add_node("write_section", write_section, retry_policy=LLM_RETRY)
    b.add_node("assemble_post", assemble_post, retry_policy=LLM_RETRY)
    b.add_node("fact_check", fact_check, retry_policy=LLM_RETRY)
    b.add_node("revise_draft", revise_draft, retry_policy=LLM_RETRY)
    b.add_node("prepare_metadata", prepare_metadata, retry_policy=LLM_RETRY)
    b.add_node("human_review", human_review)
    b.add_node("publish", publish)  # never auto-retried: a human resumes it, and the ledger makes it idempotent
    b.add_node("social_and_store", social_and_store, retry_policy=LLM_RETRY)

    b.add_edge(START, "ingest_video")
    b.add_conditional_edges("ingest_video", route_after_ingest, ["clean_transcript", END])
    b.add_edge("clean_transcript", "plan_outline")
    b.add_conditional_edges("plan_outline", fan_out_sections, ["write_section"])
    b.add_edge("write_section", "assemble_post")
    b.add_edge("assemble_post", "fact_check")
    b.add_conditional_edges("fact_check", route_after_fact_check, ["revise_draft", "prepare_metadata"])
    b.add_edge("revise_draft", "fact_check")
    b.add_edge("prepare_metadata", "human_review")
    b.add_conditional_edges("human_review", route_after_review, ["publish", "revise_draft", END])
    b.add_conditional_edges("publish", route_after_publish, ["social_and_store", END])
    b.add_edge("social_and_store", END)

    return b.compile(checkpointer=checkpointer, store=store)
