"""
Shared LLM call utility with automatic output-size batching.

Haiku max output: 8192 tokens.
Each ticker response line is ~60–120 tokens depending on the node.

Strategy:
  1. Estimate total output tokens needed: len(lines) × tokens_per_line
  2. Set max_tokens dynamically (never hardcode 800 / 1000 / 1024).
  3. If estimated output > HAIKU_MAX_OUTPUT → split into chunks and
     concatenate results. Otherwise a single call is made.
  4. In practice with the current ~15-20 ticker universe this will
     always be a single call. Batching only fires if the universe
     grows very large.
"""

import structlog

logger = structlog.get_logger()

HAIKU_MAX_OUTPUT = 8192   # Haiku's actual output token ceiling
OUTPUT_BUFFER    = 256    # safety headroom to avoid exact-limit truncation


def call_llm_batched(
    client: object,
    lines: list[str],
    system: str,
    prompt_prefix: str,
    model: str = "claude-haiku-4-5-20251001",
    tokens_per_line: int = 80,
) -> str:
    """
    Call the Anthropic API with automatic batching if needed.

    Args:
        client:          Anthropic client instance.
        lines:           One entry per ticker (input data lines OR ticker blocks).
        system:          System prompt.
        prompt_prefix:   Text prepended before the lines in the user message.
        model:           Model ID.
        tokens_per_line: Conservative estimate of output tokens per ticker.
                         Use ~80 for scoring nodes, ~120 for the synthesizer.

    Returns:
        Combined response text (batches joined with newline if multiple calls made).
    """
    if not lines:
        return ""

    # How many tickers fit in one call without risking truncation?
    max_per_batch = max(1, (HAIKU_MAX_OUTPUT - OUTPUT_BUFFER) // tokens_per_line)
    needs_batching = len(lines) > max_per_batch

    if needs_batching:
        logger.info(
            "LLM batching triggered",
            total_lines=len(lines),
            batch_size=max_per_batch,
            batches=-(len(lines) // -max_per_batch),  # ceiling division
        )
    else:
        logger.debug("LLM single call", lines=len(lines), max_tokens=len(lines) * tokens_per_line + OUTPUT_BUFFER)

    chunks = [lines[i:i + max_per_batch] for i in range(0, len(lines), max_per_batch)]
    results: list[str] = []

    for chunk in chunks:
        max_tokens = min(len(chunk) * tokens_per_line + OUTPUT_BUFFER, HAIKU_MAX_OUTPUT)
        prompt = prompt_prefix + "\n".join(chunk)
        response = client.messages.create(  # type: ignore[attr-defined]
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        results.append(response.content[0].text.strip())

    return "\n".join(results)
