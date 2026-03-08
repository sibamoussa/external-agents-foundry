"""
tracing/spans.py
----------------
Helpers that create child OTel spans from agent message payloads.

`extract_tool_spans()` walks the raw message list returned by the
Foundry agent and emits one span per tool-call and one per tool-result,
all parented to the supplied context so they nest correctly in Foundry
Tracing.
"""

from __future__ import annotations

import json
from opentelemetry import trace


_tracer = trace.get_tracer(__name__)


def extract_tool_spans(
    messages: list,
    parent_context,
    debug: bool = False,
) -> None:
    """
    Parse `messages` from a Foundry agent response and emit:

      - ``tool_call.<name>``   — one span per tool invocation
      - ``tool_result.<name>`` — one span per tool result

    All spans are attached to `parent_context` so they nest inside the
    caller's ``agent.call`` span.

    Parameters
    ----------
    messages       : Raw list of message dicts from the agent response.
    parent_context : OTel context object (use ``trace.set_span_in_context(span)``).
    debug          : When True, prints tool result content to stdout.
    """
    # First pass: collect tool-call metadata so we can correlate results
    tool_call_args: dict[str, dict] = {}

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        msg_type = msg.get("type") or msg.get("role", "")
        tool_calls = msg.get("tool_calls", [])

        if msg_type in ("ai", "assistant") and tool_calls:
            for tc in tool_calls:
                tc_id = tc.get("id") or tc.get("tool_call_id", "unknown")
                tc_name = tc.get("name") or (tc.get("function") or {}).get("name", "unknown")
                tc_args = tc.get("args") or json.loads(
                    (tc.get("function") or {}).get("arguments", "{}")
                )
                tool_call_args[tc_id] = {"name": tc_name, "args": tc_args}

                span = _tracer.start_span(f"tool_call.{tc_name}", context=parent_context)
                span.set_attribute("tool_call.name", tc_name)
                span.set_attribute("tool_call.id", tc_id)
                span.set_attribute("tool_call.args", json.dumps(tc_args)[:500])
                span.set_attribute("gen_ai.system", "azure-ai-foundry")
                span.end()

    # Second pass: emit tool-result spans
    for msg in messages:
        if not isinstance(msg, dict):
            continue

        msg_type = msg.get("type") or msg.get("role", "")
        if msg_type != "tool":
            continue

        tc_id = msg.get("tool_call_id", "unknown")
        content = str(msg.get("content", ""))
        tc_info = tool_call_args.get(tc_id, {})
        tc_name = tc_info.get("name") or msg.get("name", "unknown_tool")

        span = _tracer.start_span(f"tool_result.{tc_name}", context=parent_context)
        span.set_attribute("tool_result.name", tc_name)
        span.set_attribute("tool_result.tool_call_id", tc_id)
        span.set_attribute("tool_result.content", content[:500])
        span.set_attribute("tool_result.content_len", len(content))
        span.set_attribute("gen_ai.system", "azure-ai-foundry")
        span.end()

        if debug:
            print(f"  [TOOL RESULT] {tc_name}: {content[:200]}")
