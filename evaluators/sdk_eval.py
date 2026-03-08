"""
evaluators/sdk_eval.py
----------------------
Runs the Azure AI Evaluation SDK evaluators (F1, BLEU, ROUGE-L) against
a list of agent responses and logs the results as OTel spans.

Span hierarchy produced:
  eval.run
    ├── eval.row.1
    ├── eval.row.2
    └── eval.row.N
"""

from __future__ import annotations

import json
import time

from opentelemetry import trace

from azure.ai.evaluation import (
    evaluate,
    F1ScoreEvaluator,
    BleuScoreEvaluator,
    RougeScoreEvaluator,
    RougeType,
)

from config.settings import (
    ASSISTANT_ID,
    PROMPT_ASSET_NAME,
    DATASET_PATH,
    RESULTS_PATH,
)

_tracer = trace.get_tracer(__name__)


def _write_jsonl(path: str, rows: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_sdk_evaluation(rows: list, prompt_version: str) -> dict:
    """
    Evaluate `rows` with F1, BLEU, and ROUGE-L and emit an OTel span tree.

    Parameters
    ----------
    rows           : List of dicts with keys ``query``, ``response``,
                     ``ground_truth``.
    prompt_version : Used as a label in the evaluation name and spans.

    Returns
    -------
    metrics dict from ``azure.ai.evaluation.evaluate()``.
    """
    print("\n[EVALUATE] Running SDK evaluators (F1 / BLEU / ROUGE)...")

    _write_jsonl(DATASET_PATH, rows)

    result = evaluate(
        evaluation_name=f"weather-agent-eval-{prompt_version}-{int(time.time())}",
        data=DATASET_PATH,
        evaluators={
            "f1_score": F1ScoreEvaluator(),
            "bleu_score": BleuScoreEvaluator(),
            "rouge_score": RougeScoreEvaluator(rouge_type=RougeType.ROUGE_L),
        },
        evaluator_config={
            "f1_score": {
                "column_mapping": {
                    "response": "${data.response}",
                    "ground_truth": "${data.ground_truth}",
                }
            },
            "bleu_score": {
                "column_mapping": {
                    "response": "${data.response}",
                    "ground_truth": "${data.ground_truth}",
                }
            },
            "rouge_score": {
                "column_mapping": {
                    "response": "${data.response}",
                    "ground_truth": "${data.ground_truth}",
                }
            },
        },
        output_path=RESULTS_PATH,
    )

    metrics = result.get("metrics", {})
    rows_detail = result.get("rows", [])

    # Write results locally (guaranteed, regardless of Foundry availability)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "metrics": metrics,
                "rows": rows_detail,
                "evaluation_name": f"weather-agent-eval-{prompt_version}",
            },
            f,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    print(f"✅ SDK eval results written → {RESULTS_PATH}")

    # ── OTel: eval.run span ────────────────────────────────────────────────
    with _tracer.start_as_current_span("eval.run") as eval_span:
        eval_span.set_attribute("eval.type", "sdk")
        eval_span.set_attribute("eval.prompt_version", prompt_version)
        eval_span.set_attribute("eval.agent_id", ASSISTANT_ID)
        eval_span.set_attribute("eval.prompt_asset", PROMPT_ASSET_NAME)
        eval_span.set_attribute("eval.row_count", len(rows))
        eval_span.set_attribute("gen_ai.system", "azure-ai-foundry")
        eval_span.set_attribute("eval.mean.f1_score",    float(metrics.get("f1_score",    0) or 0))
        eval_span.set_attribute("eval.mean.bleu_score",  float(metrics.get("bleu_score",  0) or 0))
        eval_span.set_attribute("eval.mean.rouge_score", float(metrics.get("rouge_score", 0) or 0))
        eval_span.add_event(
            "eval.aggregate",
            {
                "f1_score":       str(metrics.get("f1_score", 0)),
                "bleu_score":     str(metrics.get("bleu_score", 0)),
                "rouge_score":    str(metrics.get("rouge_score", 0)),
                "prompt_version": prompt_version,
            },
        )

        # ── OTel: per-row spans ────────────────────────────────────────────
        for i, row in enumerate(rows):
            row_output = rows_detail[i] if i < len(rows_detail) else {}
            with _tracer.start_as_current_span(f"eval.row.{i + 1}") as row_span:
                row_span.set_attribute("eval.row.index",       i + 1)
                row_span.set_attribute("eval.row.query",       row.get("query", ""))
                row_span.set_attribute("eval.row.response",    row.get("response", "")[:300])
                row_span.set_attribute("eval.row.f1_score",    float(row_output.get("f1_score",    0) or 0))
                row_span.set_attribute("eval.row.bleu_score",  float(row_output.get("bleu_score",  0) or 0))
                row_span.set_attribute("eval.row.rouge_score", float(row_output.get("rouge_score", 0) or 0))
                row_span.add_event(
                    "eval.row.detail",
                    {
                        "query":       str(row.get("query", "")),
                        "f1_score":    str(row_output.get("f1_score",    0)),
                        "bleu_score":  str(row_output.get("bleu_score",  0)),
                        "rouge_score": str(row_output.get("rouge_score", 0)),
                    },
                )

    print("📊 SDK eval metrics:")
    for key, val in metrics.items():
        print(f"   {key:35s}: {val}")

    return metrics
