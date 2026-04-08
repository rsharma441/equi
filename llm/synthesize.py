"""
LLM Synthesis Layer — Phase 5

Approach B: structured JSON via instructor + anthropic SDK.

Public API:
    synthesize(fact_sheet, mandate)  → MemoOutput
    evaluate(fact_sheet, mandate, n_runs=3)  → EvaluationReport
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import anthropic
import instructor

from llm.schema import MemoOutput, Claim
from llm.prompts import SYSTEM_PROMPT, build_user_message


_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 8192


def _make_client() -> instructor.Instructor:
    return instructor.from_anthropic(anthropic.Anthropic())


def synthesize(fact_sheet: dict[str, Any], mandate: dict[str, Any]) -> MemoOutput:
    """
    Single LLM call → structured MemoOutput.

    Raises instructor validation errors if the model produces invalid output.
    """
    client = _make_client()
    user_msg = build_user_message(fact_sheet, mandate)

    result: MemoOutput = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        response_model=MemoOutput,
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _collect_valid_ids(fact_sheet: dict[str, Any]) -> set[str]:
    """Return all metric IDs, source field IDs, and mandate-derived IDs in the fact sheet."""
    ids: set[str] = set()
    for fund_id, fund in fact_sheet.get("funds", {}).items():
        ids.update(fund.get("metrics", {}).keys())
        ids.update(fund.get("source_fields", {}).keys())
        # Mandate pass/fail flags are also citable sources
        ids.add(f"{fund_id}.mandate_pass")
        for check_name in fund.get("mandate_checks", {}).keys():
            ids.add(f"{fund_id}.mandate_checks.{check_name}")
    return ids


def _check_source_ids(claims: list[Claim], valid_ids: set[str]) -> dict:
    """
    For each claim, check whether all source_ids resolve to real IDs.
    Returns a summary dict.
    """
    total_claims = len(claims)
    total_source_refs = sum(len(c.source_ids) for c in claims)
    invalid_refs: list[dict] = []

    for claim in claims:
        for sid in claim.source_ids:
            if sid not in valid_ids:
                invalid_refs.append({"claim_text": claim.claim_text[:80], "bad_id": sid})

    return {
        "total_claims": total_claims,
        "total_source_refs": total_source_refs,
        "invalid_refs_count": len(invalid_refs),
        "invalid_refs": invalid_refs,
        "resolution_rate": (
            1.0 - len(invalid_refs) / total_source_refs
            if total_source_refs > 0 else 0.0
        ),
    }


def _check_rankings(output: MemoOutput, fact_sheet: dict[str, Any]) -> dict:
    """
    Verify planted fund stories surface correctly:
      - FundA fails mandate (annual liquidity)
      - FundB flagged for 2022 rate sensitivity
      - FundD ranked #1 among mandate-passing funds
      - FundC recognised as downside protection / hidden gem
      - FundE caveated for short track record
    """
    shortlist_map = {e.fund_id: e for e in output.ranked_shortlist}
    issues: list[str] = []

    # FundA must not be mandate-passing in shortlist
    if "FundA" in shortlist_map and shortlist_map["FundA"].mandate_pass:
        issues.append("FundA marked mandate_pass=True but should fail on liquidity")

    # FundD should be rank 1 among mandate-passing funds
    passing = [e for e in output.ranked_shortlist if e.mandate_pass]
    if passing and passing[0].fund_id != "FundD":
        issues.append(
            f"Expected FundD as top mandate-passing fund, got {passing[0].fund_id}"
        )

    # FundE (short track) should be ranked below all full-track mandate-passing funds
    if "FundE" not in shortlist_map:
        issues.append("FundE missing from ranked_shortlist")
    else:
        e_rank = shortlist_map["FundE"].rank
        full_track_passing_ranks = [
            e.rank for e in output.ranked_shortlist
            if e.mandate_pass and e.fund_id != "FundE"
        ]
        if full_track_passing_ranks and e_rank <= min(full_track_passing_ranks):
            issues.append(
                f"FundE (short track) ranked #{e_rank} but full-track mandate-passing "
                f"funds have ranks {sorted(full_track_passing_ranks)} — FundE should rank lower"
            )

    # FundB should have a risk entry about 2022 / rate sensitivity
    fund_b_risk = any(
        "FundB" in r.subject and (
            "2022" in r.risk_description or
            "rate" in r.risk_description.lower() or
            "credit" in r.risk_description.lower()
        )
        for r in output.memo.key_risks
    )
    if not fund_b_risk:
        issues.append(
            "No key_risk entry for FundB mentioning 2022 / rate sensitivity"
        )

    return {
        "issues": issues,
        "mandate_passing_count": len(passing),
        "top_recommendation": passing[0].fund_id if passing else None,
        "all_funds_ranked": len(shortlist_map),
    }


@dataclass
class RunResult:
    run_index: int
    output: MemoOutput | None
    source_id_check: dict = field(default_factory=dict)
    ranking_check: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def valid(self) -> bool:
        return (
            self.output is not None
            and self.source_id_check.get("resolution_rate", 0) == 1.0
            and not self.ranking_check.get("issues")
        )


@dataclass
class EvaluationReport:
    runs: list[RunResult]
    valid_ids: set[str]

    @property
    def pass_rate(self) -> float:
        return sum(1 for r in self.runs if r.valid) / len(self.runs) if self.runs else 0.0

    def summary(self) -> str:
        lines = [
            f"Runs: {len(self.runs)}",
            f"Pass rate: {self.pass_rate:.0%}",
            "",
        ]
        for r in self.runs:
            status = "PASS" if r.valid else "FAIL"
            lines.append(f"Run {r.run_index}: {status}")
            if r.error:
                lines.append(f"  Error: {r.error}")
            if r.source_id_check:
                res = r.source_id_check
                lines.append(
                    f"  Claims: {res['total_claims']} total, "
                    f"{res['invalid_refs_count']} bad source refs "
                    f"(resolution {res['resolution_rate']:.0%})"
                )
                for bad in res["invalid_refs"][:3]:
                    lines.append(f"    BAD ID: '{bad['bad_id']}' in claim: \"{bad['claim_text']}\"")
            if r.ranking_check:
                rc = r.ranking_check
                lines.append(
                    f"  Rankings: top={rc.get('top_recommendation')}, "
                    f"mandate_passing={rc.get('mandate_passing_count')}"
                )
                for issue in rc.get("issues", []):
                    lines.append(f"    ISSUE: {issue}")
        return "\n".join(lines)

    def best_output(self) -> MemoOutput | None:
        """Return the output from the first passing run, or the first run if none pass."""
        for r in self.runs:
            if r.valid and r.output is not None:
                return r.output
        for r in self.runs:
            if r.output is not None:
                return r.output
        return None


def evaluate(
    fact_sheet: dict[str, Any],
    mandate: dict[str, Any],
    n_runs: int = 3,
) -> EvaluationReport:
    """
    Run synthesize() n_runs times, evaluate each output, return report.
    """
    valid_ids = _collect_valid_ids(fact_sheet)
    results: list[RunResult] = []

    for i in range(1, n_runs + 1):
        print(f"  Run {i}/{n_runs}...", end=" ", flush=True)
        try:
            output = synthesize(fact_sheet, mandate)
            sid_check = _check_source_ids(output.claims, valid_ids)
            rank_check = _check_rankings(output, fact_sheet)
            run = RunResult(
                run_index=i,
                output=output,
                source_id_check=sid_check,
                ranking_check=rank_check,
            )
            status = "ok" if run.valid else "issues"
            print(status)
        except Exception as exc:
            run = RunResult(run_index=i, output=None, error=str(exc))
            print(f"ERROR: {exc}")
        results.append(run)

    return EvaluationReport(runs=results, valid_ids=valid_ids)


# ─────────────────────────────────────────────────────────────────────────────
# CLI runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")

    from engine.normalize import normalize
    from engine.quant import run_quant_engine, Mandate

    universe  = "data/fund_universe.csv"
    returns   = "data/fund_returns.csv"
    db        = "data/market_data.db"

    mandate = Mandate(
        liquidity_requirement="quarterly",
        target_vol_max=20.0,
        max_drawdown_tolerance=-30.0,
    )

    print("Normalising fund data...")
    records, report = normalize(universe, returns)

    print("Running quant engine...")
    fact_sheet, san_warnings = run_quant_engine(records, returns, mandate, db_path=db)
    if san_warnings:
        for w in san_warnings:
            print(f"  WARN: {w}")

    print(f"\nRunning LLM evaluation (3 runs)...")
    eval_report = evaluate(fact_sheet, mandate.model_dump(), n_runs=3)

    print("\n=== EVALUATION REPORT ===")
    print(eval_report.summary())

    best = eval_report.best_output()
    if best:
        print("\n=== BEST OUTPUT — RANKED SHORTLIST ===")
        for e in best.ranked_shortlist:
            badge = "PASS" if e.mandate_pass else "FAIL"
            print(f"  #{e.rank} [{badge}] {e.fund_id}: {e.one_line_rationale}")

        print("\n=== BEST OUTPUT — MEMO EXECUTIVE SUMMARY ===")
        print(best.memo.executive_summary)

        print("\n=== BEST OUTPUT — RECOMMENDATION ===")
        print(best.memo.recommendation)

        print("\n=== BEST OUTPUT — KEY RISKS ===")
        for risk in best.memo.key_risks:
            print(f"  [{risk.subject}] {risk.risk_description}")

        print(f"\n=== AUDIT TRAIL ({len(best.claims)} claims) ===")
        for claim in best.claims[:10]:
            print(f"  Claim: \"{claim.claim_text[:80]}\"")
            print(f"  Sources: {claim.source_ids}")
            print()

        if "--json" in sys.argv:
            print("\n=== FULL JSON OUTPUT ===")
            print(json.dumps(best.model_dump(), indent=2))
