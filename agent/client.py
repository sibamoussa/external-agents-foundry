"""
agent/client.py
---------------
HTTP client that calls the Foundry agent endpoint and records a
structured OTel trace for every request.

Span hierarchy produced per call:
  agent.call
    └── apim.gateway          (HTTP span — latency, status code)
          ├── tool_call.*     (one per tool the agent invoked)
          └── tool_result.*   (one per tool result returned)
"""

from __future__ import annotations

import json
import time
import urllib.request
import urllib.error

from opentelemetry import trace
from opentelemetry.semconv.trace import SpanAttributes

# ── FIXED: use relative config import, not the full package path ──────────────
from config.settings import ASSISTANT_ID, PROMPT_ASSET_NAME, get_prompt
from tracing.spans import extract_tool_spans

_tracer = trace.get_tracer(__name__)


def call_agent(
    base_url: str,
    question: str,
    headers: dict,
    prompt_version: str,
    debug: bool = False,
) -> str:
    """
    Send a single question to the Foundry agent and return the text answer.

    Parameters
    ----------
    base_url       : Gateway or local dev server base URL.
    question       : User question string.
    headers        : Auth headers (empty dict for local mode).
    prompt_version : Key from the PROMPTS registry in config/settings.py.
    debug          : When True, dumps raw message payloads to stdout.

    Returns
    -------
    The agent's text response, or ``"(no response)"`` if no AI message found.

    Raises
    ------
    urllib.error.HTTPError  : On non-2xx HTTP responses.
    Exception               : Any other network / JSON error.
    """
    prompt = get_prompt(prompt_version)

    with _tracer.start_as_current_span("agent.call") as agent_span:
        # GenAI semantic conventions — recognised by Foundry's trace viewer
        agent_span.set_attribute("gen_ai.system", "azure-ai-foundry")
        agent_span.set_attribute("gen_ai.operation.name", "agent.call")
        agent_span.set_attribute("gen_ai.request.model", ASSISTANT_ID)
        agent_span.set_attribute("agent.prompt_asset", PROMPT_ASSET_NAME)
        agent_span.set_attribute("agent.prompt_version", prompt_version)
        agent_span.set_attribute("agent.question", question)

        body = json.dumps(
            {
                "assistant_id": ASSISTANT_ID,
                "input": {
                    "messages": [
                        {"role": "system", "content": prompt["system"]},
                        {"role": "user", "content": question},
                    ],
                    "metadata": {
                        "prompt_asset": PROMPT_ASSET_NAME,
                        "prompt_version": prompt_version,
                        "environment": "local" if not headers else "gateway",
                        "release_stage": "prod",
                        "owner": "ml-platform",
                    },
                },
            }
        ).encode()

        req = urllib.request.Request(
            f"{base_url}/runs/wait",
            data=body,
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )

        # ── APIM gateway span ──────────────────────────────────────────────
        with _tracer.start_as_current_span("apim.gateway") as apim_span:
            apim_span.set_attribute(SpanAttributes.HTTP_METHOD, "POST")
            apim_span.set_attribute(SpanAttributes.HTTP_URL, f"{base_url}/runs/wait")
            apim_span.set_attribute("apim.agent_id", ASSISTANT_ID)
            apim_span.set_attribute("apim.base_url", base_url)

            start = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    status_code = resp.status
                    result = json.loads(resp.read())

                duration_ms = round((time.perf_counter() - start) * 1000, 2)
                apim_span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, status_code)
                apim_span.set_attribute("apim.latency_ms", duration_ms)

            except urllib.error.HTTPError as e:
                error_body = e.read().decode("utf-8", errors="replace")
                print(f"\n❌ HTTP {e.code} {e.reason} — {error_body[:300]}")
                apim_span.record_exception(e)
                apim_span.set_status(trace.StatusCode.ERROR, str(e))
                agent_span.record_exception(e)
                agent_span.set_status(trace.StatusCode.ERROR, str(e))
                raise

            except Exception as e:
                apim_span.record_exception(e)
                apim_span.set_status(trace.StatusCode.ERROR, str(e))
                agent_span.record_exception(e)
                agent_span.set_status(trace.StatusCode.ERROR, str(e))
                raise

        # ── Post-request processing ────────────────────────────────────────

        # ── FIXED: handle different response structures ────────────────────
        messages = (
            result.get("messages")
            or result.get("output", {}).get("messages")
            or result.get("data", {}).get("messages")
            or []
        )

        agent_span.set_attribute("agent.response_time_ms", duration_ms)
        agent_span.set_attribute("agent.message_count", len(messages))

        if debug:
            agent_span.add_event(
                "agent.raw_messages",
                {"messages": json.dumps(messages)[:2000]},
            )
            print("\n[DEBUG] Full raw response:")
            print(json.dumps(result, indent=2)[:3000])
            print("\n[DEBUG] Messages found:")
            for i, msg in enumerate(messages):
                print(
                    f"  msg[{i}] type={msg.get('type') or msg.get('role', 'unknown')!r} "
                    f"content={str(msg.get('content', ''))[:100]!r}"
                )

        parent_ctx = trace.set_span_in_context(agent_span)
        extract_tool_spans(messages, parent_ctx, debug=debug)

        tool_call_count = sum(
            1
            for m in messages
            if isinstance(m, dict)
            and (m.get("type") == "tool" or m.get("role") == "tool")
        )
        agent_span.set_attribute("agent.tool_call_count", tool_call_count)

        # ── FIXED: robust response extraction ─────────────────────────────
        # Pass 1 — look for ai/assistant messages
        for msg in reversed(messages):
            if not isinstance(msg, dict):
                continue
            msg_type = msg.get("type") or msg.get("role", "")
            content  = msg.get("content")

            if msg_type in ("ai", "assistant") and content:
                # Handle plain string
                if isinstance(content, str) and content.strip():
                    answer = content
                    agent_span.set_attribute("agent.response_length", len(answer))
                    agent_span.add_event("agent.response_received", {"preview": answer[:200]})
                    return answer
                # Handle list of content blocks e.g. [{"type": "text", "text": "..."}]
                if isinstance(content, list):
                    text = " ".join(
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict)
                    ).strip()
                    if text:
                        agent_span.set_attribute("agent.response_length", len(text))
                        agent_span.add_event("agent.response_received", {"preview": text[:200]})
                        return text

        # Pass 2 — last resort, return any message with non-empty string content
        for msg in reversed(messages):
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()

        agent_span.add_event("agent.no_response")
        return "(no response)"