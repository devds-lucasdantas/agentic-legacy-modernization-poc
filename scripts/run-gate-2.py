#!/usr/bin/env python3
"""Gate 2 — COBOL Reader Runner

Executes the single-file COBOL analysis on BANK-MAIN.CBL using gpt-5-mini
via Azure AI Foundry Responses API Structured Outputs.

Saves raw execution artifacts locally to artifacts/gate-2/baseline-v1/
and runs deterministic evaluation against evals/expected/bank-main-single.json.

Exit codes:
    0 = PASS
    1 = FAIL (or scope violation / pre-check failure)
"""

import json
import subprocess
import sys
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from agents.legacy_analyzer.agent import LegacyAnalyzerAgent  # noqa: E402
from agents.legacy_analyzer.config import load_config  # noqa: E402
from agents.legacy_analyzer.schemas.export import export_schema_to_file  # noqa: E402
from src.cobol.source_reader import EXPECTED_BANK_MAIN_SHA256, prepare_source  # noqa: E402
from src.cobol.static_extractor import extract_static_facts  # noqa: E402
from src.validation.evaluator import evaluate_assessment, load_golden_dataset  # noqa: E402


def check_git_branch() -> str:
    """Verify current git branch is feat/gate-2-cobol-reader."""
    try:
        res = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception as e:
        print(f"WARNING: Could not check git branch via CLI: {e}")
        return "UNKNOWN"


def get_git_commit_sha() -> str:
    """Get HEAD commit SHA for baseline execution provenance."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception as e:
        print(f"WARNING: Could not check git commit SHA: {e}")
        return "UNKNOWN"


def main() -> int:
    print("======================================================================")
    print(" GATE 2 — COBOL READER RUNNER")
    print("======================================================================")
    print()

    # 1. Branch verification
    branch = check_git_branch()
    print(f"Current branch: {branch}")
    if branch != "feat/gate-2-cobol-reader":
        print(f"ERROR: Expected branch 'feat/gate-2-cobol-reader', but found '{branch}'")
        print("Aborting to prevent accidental execution on wrong branch.")
        return 1

    # 2. Source verification & scope check
    target_rel_path = "legacy/core-banking-system/BANK-MAIN.CBL"
    prep = prepare_source(target_rel_path, repo_root=REPO_ROOT)
    print(f"Target file:    {prep.relative_path}")
    print(f"Source SHA256:  {prep.sha256}")
    print(f"Source lines:   {prep.line_count}")

    if prep.sha256.lower() != EXPECTED_BANK_MAIN_SHA256.lower():
        print(f"ERROR: Source SHA256 mismatch! Expected {EXPECTED_BANK_MAIN_SHA256}")
        return 1
    print("[OK] Source immutability and scope verified")
    print()

    # 3. Static ground truth extraction
    print("--- Running Deterministic Static Extraction ---")
    static_facts = extract_static_facts(prep.raw_content)
    print(f"Static Program ID:       {static_facts.program_id}")
    print(f"Static Call Targets:     {static_facts.call_targets}")
    copy_count = len(static_facts.copy_statements)
    print(f"Static Copy Statements:  {static_facts.copy_statements} (count: {copy_count})")
    print(f"Static Stop Run Lines:   {static_facts.stop_run_lines}")
    print(f"Static WS Fields:        {[f['name'] for f in static_facts.working_storage_fields]}")
    print()

    commit_sha = get_git_commit_sha()
    print(f"Git commit SHA:  {commit_sha}")
    print()

    # 4. Initialize agent and Azure connection
    print("--- Initializing Agent & Azure Foundry Connection ---")
    try:
        config = load_config()
        print(f"Endpoint: {config.foundry_project_endpoint}")
        print(f"Model:    {config.foundry_model}")
    except Exception as e:
        print(f"ERROR: Failed to load Foundry configuration: {e}")
        return 1

    agent = LegacyAnalyzerAgent(config=config, reasoning_effort="low")

    # 5. Execute live model call
    print()
    print("--- Executing Live Responses API Call (gpt-5-mini) ---")
    print("Calling Responses API with native Structured Outputs (text_format=LegacyAssessment)...")

    try:
        assessment, metadata = agent.analyze_source(
            source_path=target_rel_path,
            run_label="baseline-v1",
            repo_root=REPO_ROOT,
            git_commit_sha=commit_sha,
        )
        print(f"[OK] Response received in {metadata.elapsed_seconds:.2f}s")
        print(f"Input tokens:  {metadata.input_tokens}")
        print(f"Output tokens: {metadata.output_tokens}")
        print(f"Total tokens:  {metadata.total_tokens}")
    except Exception as e:
        print(f"[FAIL] Live agent execution failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # 6. Save raw local artifacts
    artifact_dir = REPO_ROOT / "artifacts" / "gate-2" / "baseline-v1"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    assessment_file = artifact_dir / "bank-main-assessment.json"
    metadata_file = artifact_dir / "run-metadata.json"
    schema_file = artifact_dir / "assessment-schema.json"
    eval_file = artifact_dir / "evaluation.json"

    assessment_json = assessment.model_dump_json(indent=2)
    assessment_file.write_text(assessment_json, encoding="utf-8")
    metadata_file.write_text(json.dumps(metadata.to_dict(), indent=2), encoding="utf-8")
    export_schema_to_file(schema_file)

    print(f"[OK] Saved raw assessment to: {assessment_file}")
    print(f"[OK] Saved run metadata to:   {metadata_file}")
    print(f"[OK] Saved schema to:         {schema_file}")
    print()

    # 7. Evaluate assessment deterministically
    print("--- Running Deterministic Evaluation ---")
    golden = load_golden_dataset(REPO_ROOT / "evals" / "expected" / "bank-main-single.json")
    report = evaluate_assessment(assessment, golden_data=golden)

    eval_file.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    print(f"[OK] Saved evaluation report to: {eval_file}")
    print()

    # 8. Report results
    print("======================================================================")
    print(" GATE 2 EVALUATION SUMMARY")
    print("======================================================================")
    print(f"Schema Valid:            {report.schema_valid}")
    print(f"Scope Valid:             {report.scope_valid}")
    print(f"Source SHA256 Match:     {report.source_sha256_match}")
    print(f"Evidence Valid:          {report.evidence_valid}")
    print(f"Invalid Evidence Count:  {report.invalid_evidence_count}")
    print(f"Expected Facts:          {report.expected_fact_count}")
    print(f"Matched Facts (TP):      {report.matched_fact_count}")
    print(f"Missing Facts (FN):      {report.missing_fact_count}")
    print(f"False Positives (FP):    {report.false_positive_count}")
    print(f"Recall:                  {report.recall:.2%}")
    print(f"Precision:               {report.precision:.2%}")
    print("----------------------------------------------------------------------")
    print(f"GATE 2 RESULT:           {'PASS' if report.gate_2_pass else 'FAIL'}")
    print("======================================================================")

    if report.missing_facts:
        print("\nMissing Facts:")
        for mf in report.missing_facts:
            print(f"  - [{mf.fact_id}] {mf.description}")

    if report.invalid_evidences:
        print("\nInvalid Evidence Details:")
        for ie in report.invalid_evidences:
            print(f"  - {ie['field_context']}: {ie['error_message']}")

    if report.unsupported_facts:
        print("\nFalse Positives / Unsupported Claims:")
        for uf in report.unsupported_facts:
            print(f"  - {uf}")

    return 0 if report.gate_2_pass else 1


if __name__ == "__main__":
    sys.exit(main())
