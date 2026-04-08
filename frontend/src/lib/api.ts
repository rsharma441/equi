const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface UploadResponse {
  session_id: string;
  fund_count: number;
  warnings: string[];
}

export interface MandateForm {
  liquidity_requirement: "monthly" | "quarterly" | "annual";
  target_vol_max: number | null;
  max_drawdown_tolerance: number;
  strategy_include: string[];
  strategy_exclude: string[];
}

export interface ShortlistEntry {
  fund_id: string;
  rank: number;
  mandate_pass: boolean;
  one_line_rationale: string;
}

export interface RiskEntry {
  subject: string;
  risk_description: string;
}

export interface DataAppendixRow {
  fund_id: string;
  fund_name: string;
  strategy: string;
  mandate_pass: boolean;
  annualized_return_net_pct: number | null;
  annualized_vol_net_pct: number | null;
  sharpe_net: number | null;
  max_drawdown_pct: number | null;
  return_fy2022_pct: number | null;
  return_covid_crash_pct: number | null;
  beta_spy: number | null;
  mgmt_fee_pct: number | null;
  perf_fee_pct: number | null;
  liquidity_freq: string | null;
}

export interface Memo {
  executive_summary: string;
  recommendation: string;
  key_risks: RiskEntry[];
  data_appendix: DataAppendixRow[];
}

export interface Claim {
  claim_text: string;
  source_ids: string[];
}

export interface AnalyzeResponse {
  session_id: string;
  ranked_shortlist: ShortlistEntry[];
  memo: Memo;
  claims: Claim[];
}

export interface AuditResponse {
  source_id: string;
  source_type: "metric" | "source_field" | "mandate_check" | "mandate_pass";
  value: unknown;
  label: string;
  unit?: string;
}

// ── API calls ─────────────────────────────────────────────────────────────────

export async function uploadCSVs(
  universeFile: File,
  returnsFile: File
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("universe", universeFile);
  form.append("returns", returnsFile);

  const res = await fetch(`${API_BASE}/upload`, { method: "POST", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Upload failed");
  }
  return res.json();
}

export async function analyze(
  sessionId: string,
  mandate: MandateForm
): Promise<AnalyzeResponse> {
  const res = await fetch(`${API_BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, mandate }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Analysis failed");
  }
  return res.json();
}

export async function fetchAudit(
  sessionId: string,
  sourceId: string
): Promise<AuditResponse> {
  const res = await fetch(`${API_BASE}/audit/${sessionId}/${sourceId}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Audit lookup failed");
  }
  return res.json();
}
