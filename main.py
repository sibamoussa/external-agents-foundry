"""
main.py
-------
Entry point for the weather agent.

Usage
-----
  python main.py                          # gateway mode, prompt v1
  python main.py --local                  # local langgraph dev server
  python main.py --prompt-version v2      # use a different prompt
  python main.py --debug                  # dump raw agent messages
  python main.py --skip-eval              # skip all evaluation steps
  python main.py --url https://...        # override the gateway URL

Trace hierarchy in Foundry > Observability > Tracing
-----------------------------------------------------
  weather-agent.test-run
    ├── agent.call
    │     └── apim.gateway
    │           ├── tool_call.*
    │           └── tool_result.*
    ├── eval.run
    │     ├── eval.row.1
    │     └── eval.row.N
    └── custom_eval.run
          ├── custom_eval.row.1
          └── custom_eval.row.N
"""

from __future__ import annotations

import argparse
import os

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from opentelemetry import trace

from config import settings as cfg
from tracing.setup import init_tracing
from agent.client import call_agent
from evaluators.sdk_eval import run_sdk_evaluation
from evaluators.custom_eval import run_custom_evaluation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test the External Weather Agent imported into Foundry with OTel tracing and evaluation."
    )
    parser.add_argument("--url", default=None, help="Override the gateway base URL.")
    parser.add_argument(
        "--local", action="store_true", help="Use the local langgraph dev server."
    )
    parser.add_argument(
        "--prompt-version",
        default=cfg.DEFAULT_PROMPT_VERSION,
        help=f"Prompt version to use. Available: {', '.join(cfg.PROMPTS.keys())}",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Print raw agent messages to stdout."
    )
    parser.add_argument(
        "--skip-eval", action="store_true", help="Skip all evaluation steps."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prompt_version = args.prompt_version

    # ── Apply debug flag ───────────────────────────────────────────────────────
    if args.debug:
        os.environ["DEBUG_RAW_MESSAGES"] = "true"
        cfg.DEBUG_RAW_MESSAGES = True  # type: ignore[attr-defined]

    # ── Initialise tracing (must happen before any span is created) ────────────
    tracer, otel_provider = init_tracing()

    # ── Resolve base URL and auth headers ─────────────────────────────────────

    if args.local:
        base_url = cfg.LOCAL_URL
        auth_headers = {}
        print(f"Mode   : LOCAL  ({base_url})")
    else:
        base_url = args.url or cfg.FOUNDRY_GATEWAY_URL
        token = get_bearer_token_provider(
            DefaultAzureCredential(), "https://ai.azure.com/.default"
        )()
        auth_headers = {"Authorization": f"Bearer {token}"}
        print(f"Mode   : GATEWAY  ({base_url})")


    # ── Print run summary ──────────────────────────────────────────────────────
    print(f"Agent          : {cfg.ASSISTANT_ID}")
    print(f"Prompt asset   : {cfg.PROMPT_ASSET_NAME}")
    print(f"Prompt version : {prompt_version}")
    print(f"System prompt  : {cfg.PROMPTS[prompt_version]['system']}")
    print(f"Debug messages : {cfg.DEBUG_RAW_MESSAGES}")
    print(f"Run evaluation : {not args.skip_eval}")
    print(f"Results path   : {cfg.RESULTS_PATH}")
    print("=" * 70)

    eval_rows: list[dict] = []
    passed = 0
    failed = 0

    # ── Root span — all child spans nest inside this ───────────────────────────
    with tracer.start_as_current_span("weather-agent.test-run") as root_span:
        root_span.set_attribute("run.prompt_version", prompt_version)
        root_span.set_attribute("run.question_count", len(cfg.QUESTIONS))
        root_span.set_attribute("run.agent_id",       cfg.ASSISTANT_ID)
        root_span.set_attribute("run.prompt_asset",   cfg.PROMPT_ASSET_NAME)

        # ── Agent calls ────────────────────────────────────────────────────────
        for item in cfg.QUESTIONS:
            question     = item["query"]
            ground_truth = item.get("ground_truth", "")
            print(f"\nQ: {question}")

            try:
                answer = call_agent(
                    base_url=base_url,
                    question=question,
                    headers=auth_headers,
                    prompt_version=prompt_version,
                    debug=args.debug,
                )
                print(f"A: {answer}")
                passed += 1
                eval_rows.append(
                    {
                        "query":        question,
                        "response":     answer,
                        "ground_truth": ground_truth,
                    }
                )
            except Exception as e:
                print(f"ERROR: {e}")
                failed += 1

        root_span.set_attribute("run.passed", passed)
        root_span.set_attribute("run.failed", failed)
        root_span.add_event("run.complete", {"passed": str(passed), "failed": str(failed)})

        if failed > 0:
            root_span.set_status(
                trace.StatusCode.ERROR,
                f"{failed} of {len(cfg.QUESTIONS)} questions failed",
            )

        # ── Evaluation — spans are children of root_span ───────────────────────
        if not args.skip_eval and eval_rows:
            run_sdk_evaluation(eval_rows, prompt_version)      # F1 / BLEU / ROUGE
            run_custom_evaluation(eval_rows, prompt_version)   # WeatherCompleteness
        elif args.skip_eval:
            print("\n[Evaluation skipped via --skip-eval]")
        else:
            print("\n[No responses collected — evaluation skipped]")

    # ── Force-flush AFTER the root span closes so nothing is dropped ───────────
    print("\nFlushing all spans to Azure Monitor...")
    otel_provider.force_flush(timeout_millis=10000)

    print("\n" + "=" * 70)
    print(f"Done.  ✅ {passed} passed    ❌ {failed} failed")
    print("Traces → Foundry > Observability > Tracing  (allow ~2 min to appear)")
    print("         weather-agent.test-run")
    print("           ├── agent.call > apim.gateway > tool_result.*")
    print("           ├── eval.run > eval.row.1/2/3")
    print("           └── custom_eval.run > custom_eval.row.1/2/3")


if __name__ == "__main__":
    main()