#!/usr/bin/env python3
"""Evaluate the six implemented semantic rules on the synthetic regression corpus."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx

from normocontrol.evaluation.semantic import (
    SemanticEvaluationReport,
    evaluate_semantic_corpus,
    load_semantic_corpus,
    mock_provider_factory,
    shared_provider_factory,
)
from normocontrol.llm.config import OLLAMA_BASE_URL, OLLAMA_MODEL, load_llm_config
from normocontrol.llm.ollama import OllamaProvider

DEFAULT_CORPUS = Path("tests/fixtures/semantic/corpus.json")
DEFAULT_OUTPUT = Path("benchmark-results/semantic-evaluation.json")


def _atomic_write(path: Path, report: SemanticEvaluationReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(report.model_dump_json(indent=2))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def evaluate(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str] = os.environ,
) -> SemanticEvaluationReport:
    """Run a deterministic mock or explicitly selected local Ollama evaluation."""
    corpus = load_semantic_corpus(args.corpus)
    if args.provider == "mock":
        return evaluate_semantic_corpus(
            corpus,
            provider_factory=mock_provider_factory,
            provider_name="synthetic-mock",
            model_id="synthetic-mock-v1",
        )

    values = dict(environ)
    values.update(
        {
            "LLM_PROVIDER": "ollama",
            "LLM_BASE_URL": args.base_url,
            "LLM_MODEL": args.model,
            "LLM_TIMEOUT": str(args.timeout),
        }
    )
    config = load_llm_config(values)
    with httpx.Client(trust_env=False) as client:
        provider = OllamaProvider(config, http_client=client)
        return evaluate_semantic_corpus(
            corpus,
            provider_factory=shared_provider_factory(provider),
            provider_name=provider.name,
            model_id=config.model,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("mock", "ollama"), default="mock")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=OLLAMA_MODEL)
    parser.add_argument("--base-url", default=OLLAMA_BASE_URL)
    parser.add_argument("--timeout", type=float, default=90.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout <= 0:
        print("evaluation timeout must be positive", file=sys.stderr)
        return 2
    try:
        report = evaluate(args)
        _atomic_write(args.output, report)
    except (OSError, ValueError, httpx.HTTPError) as error:
        print(f"semantic evaluation error: {type(error).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    print(f"semantic metrics JSON: {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
