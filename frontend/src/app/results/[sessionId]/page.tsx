"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { analyze, fetchAudit, AnalyzeResponse, AuditResponse, Claim, MandateForm } from "@/lib/api";

// Results are stored in sessionStorage by the upload page so we don't re-fetch.
// Key: session_id → AnalyzeResponse JSON

export default function ResultsPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;

  const [data, setData] = useState<AnalyzeResponse | null>(null);
  const [activeClaim, setActiveClaim] = useState<Claim | null>(null);
  const [auditResults, setAuditResults] = useState<AuditResponse[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);

  // Load from sessionStorage (set by upload page before redirect)
  useEffect(() => {
    const stored = sessionStorage.getItem(`result:${sessionId}`);
    if (stored) {
      setData(JSON.parse(stored));
    }
  }, [sessionId]);

  async function handleClaimClick(claim: Claim) {
    setActiveClaim(claim);
    setAuditLoading(true);
    try {
      const results = await Promise.all(
        claim.source_ids.map((sid) => fetchAudit(sessionId, sid))
      );
      setAuditResults(results);
    } catch {
      setAuditResults([]);
    } finally {
      setAuditLoading(false);
    }
  }

  if (!data) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-gray-500 text-sm">Loading results…</p>
      </div>
    );
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="max-w-6xl mx-auto px-4 py-10">
        {/* Header */}
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900 tracking-tight">
              Investment Committee Memo
            </h1>
            <p className="text-xs text-gray-400 mt-1">
              Session {sessionId.slice(0, 8)}… · Click any highlighted claim to see
              its data source
            </p>
          </div>
          <a
            href="/"
            className="text-sm text-gray-500 hover:text-gray-700 underline underline-offset-2"
          >
            ← New analysis
          </a>
        </div>

        <div className="flex gap-6">
          {/* Main column */}
          <div className="flex-1 min-w-0 space-y-6">
            {/* Shortlist */}
            <Section title="Ranked Shortlist">
              <div className="space-y-3">
                {data.ranked_shortlist.map((fund) => (
                  <div
                    key={fund.fund_id}
                    className={`flex items-start gap-3 p-4 rounded-lg border ${
                      fund.mandate_pass
                        ? "border-green-200 bg-green-50"
                        : "border-gray-200 bg-white opacity-70"
                    }`}
                  >
                    <span className="text-lg font-bold text-gray-400 w-6 shrink-0">
                      {fund.rank}
                    </span>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-semibold text-gray-900 text-sm">
                          {fund.fund_id}
                        </span>
                        <Badge pass={fund.mandate_pass} />
                      </div>
                      <p className="text-sm text-gray-600">{fund.one_line_rationale}</p>
                    </div>
                  </div>
                ))}
              </div>
            </Section>

            {/* Executive Summary */}
            <Section title="Executive Summary">
              <ClaimableText
                text={data.memo.executive_summary}
                claims={data.claims}
                activeClaim={activeClaim}
                onClaimClick={handleClaimClick}
              />
            </Section>

            {/* Recommendation */}
            <Section title="Recommendation">
              <ClaimableText
                text={data.memo.recommendation}
                claims={data.claims}
                activeClaim={activeClaim}
                onClaimClick={handleClaimClick}
              />
            </Section>

            {/* Key Risks */}
            <Section title="Key Risks">
              <div className="space-y-3">
                {data.memo.key_risks.map((risk, i) => (
                  <div key={i} className="border border-gray-200 rounded-lg p-4 bg-white">
                    <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                      {risk.subject}
                    </span>
                    <ClaimableText
                      text={risk.risk_description}
                      claims={data.claims}
                      activeClaim={activeClaim}
                      onClaimClick={handleClaimClick}
                      className="mt-1"
                    />
                  </div>
                ))}
              </div>
            </Section>

            {/* Data Appendix */}
            <Section title="Data Appendix">
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-gray-700">
                  <thead>
                    <tr className="border-b border-gray-200">
                      {["Fund", "Strategy", "Mandate", "Ann Ret%", "Vol%", "Sharpe", "MaxDD%", "FY2022%", "Beta", "Fees"].map(
                        (h) => (
                          <th key={h} className="text-left py-2 pr-4 font-semibold text-gray-500">
                            {h}
                          </th>
                        )
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {data.memo.data_appendix.map((row) => (
                      <tr key={row.fund_id} className="border-b border-gray-100">
                        <td className="py-2 pr-4 font-medium">{row.fund_id}</td>
                        <td className="py-2 pr-4 text-gray-500">{row.strategy}</td>
                        <td className="py-2 pr-4">
                          <Badge pass={row.mandate_pass} />
                        </td>
                        <td className="py-2 pr-4">{fmt(row.annualized_return_net_pct, 1)}</td>
                        <td className="py-2 pr-4">{fmt(row.annualized_vol_net_pct, 1)}</td>
                        <td className="py-2 pr-4">{fmt(row.sharpe_net, 2)}</td>
                        <td className="py-2 pr-4">{fmt(row.max_drawdown_pct, 1)}</td>
                        <td className="py-2 pr-4">{fmt(row.return_fy2022_pct, 1)}</td>
                        <td className="py-2 pr-4">{fmt(row.beta_spy, 2)}</td>
                        <td className="py-2 pr-4">
                          {row.mgmt_fee_pct}/{row.perf_fee_pct}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          </div>

          {/* Audit panel */}
          <aside className="w-80 shrink-0">
            <div className="sticky top-10">
              <Section title="Audit Trail">
                {activeClaim ? (
                  <div>
                    <p className="text-xs text-gray-500 mb-3 italic">
                      &ldquo;{activeClaim.claim_text}&rdquo;
                    </p>
                    {auditLoading ? (
                      <p className="text-xs text-gray-400">Loading sources…</p>
                    ) : (
                      <div className="space-y-3">
                        {auditResults.map((r) => (
                          <AuditCard key={r.source_id} result={r} />
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-xs text-gray-400">
                    Click a highlighted claim in the memo to see its data source.
                  </p>
                )}
              </Section>
            </div>
          </aside>
        </div>
      </div>
    </main>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-4">
        {title}
      </h2>
      {children}
    </div>
  );
}

function Badge({ pass }: { pass: boolean }) {
  return (
    <span
      className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
        pass
          ? "bg-green-100 text-green-700"
          : "bg-red-100 text-red-600"
      }`}
    >
      {pass ? "PASS" : "FAIL"}
    </span>
  );
}

/**
 * Renders text with claim substrings highlighted as clickable spans.
 * Finds each claim whose claim_text appears verbatim in the text and wraps
 * that substring in a highlighted button.
 */
function ClaimableText({
  text,
  claims,
  activeClaim,
  onClaimClick,
  className = "",
}: {
  text: string;
  claims: Claim[];
  activeClaim: Claim | null;
  onClaimClick: (c: Claim) => void;
  className?: string;
}) {
  // Build a list of {start, end, claim} sorted by position
  type Span = { start: number; end: number; claim: Claim };
  const spans: Span[] = [];

  for (const claim of claims) {
    const idx = text.indexOf(claim.claim_text);
    if (idx !== -1) {
      spans.push({ start: idx, end: idx + claim.claim_text.length, claim });
    }
  }

  // Sort and deduplicate (keep first match per position)
  spans.sort((a, b) => a.start - b.start);

  // Build segments
  const segments: React.ReactNode[] = [];
  let cursor = 0;
  for (const span of spans) {
    if (span.start < cursor) continue; // overlapping — skip
    if (span.start > cursor) {
      segments.push(text.slice(cursor, span.start));
    }
    const isActive = activeClaim?.claim_text === span.claim.claim_text;
    segments.push(
      <button
        key={span.start}
        onClick={() => onClaimClick(span.claim)}
        className={`rounded px-0.5 transition-colors cursor-pointer ${
          isActive
            ? "bg-blue-200 text-blue-900"
            : "bg-yellow-100 hover:bg-yellow-200 text-gray-900"
        }`}
      >
        {span.claim.claim_text}
      </button>
    );
    cursor = span.end;
  }
  if (cursor < text.length) {
    segments.push(text.slice(cursor));
  }

  return (
    <p className={`text-sm text-gray-700 leading-relaxed ${className}`}>
      {segments.length > 0 ? segments : text}
    </p>
  );
}

function AuditCard({ result }: { result: AuditResponse }) {
  const displayValue =
    result.value === null || result.value === undefined
      ? "—"
      : typeof result.value === "boolean"
      ? result.value ? "Yes" : "No"
      : String(result.value);

  const typeColors: Record<string, string> = {
    metric: "bg-blue-50 border-blue-200 text-blue-700",
    source_field: "bg-purple-50 border-purple-200 text-purple-700",
    mandate_check: "bg-orange-50 border-orange-200 text-orange-700",
    mandate_pass: "bg-gray-50 border-gray-200 text-gray-600",
  };

  return (
    <div className={`rounded-lg border p-3 ${typeColors[result.source_type] ?? "bg-gray-50 border-gray-200"}`}>
      <p className="text-xs font-mono font-medium mb-1">{result.source_id}</p>
      <p className="text-xs text-gray-500 mb-2">{result.label}</p>
      <p className="text-sm font-semibold">
        {displayValue}
        {result.unit ? <span className="text-xs font-normal ml-1">{result.unit}</span> : null}
      </p>
    </div>
  );
}

function fmt(v: number | null, decimals: number): string {
  return v == null ? "—" : v.toFixed(decimals);
}
