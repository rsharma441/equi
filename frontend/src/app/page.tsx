"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { uploadCSVs, analyze, MandateForm } from "@/lib/api";

const STRATEGIES = ["equity_ls", "macro", "credit", "multi_strat", "quant"];

const DEFAULT_MANDATE: MandateForm = {
  liquidity_requirement: "quarterly",
  target_vol_max: null,
  max_drawdown_tolerance: -25,
  strategy_include: [],
  strategy_exclude: [],
};

export default function UploadPage() {
  const router = useRouter();
  const [universeFile, setUniverseFile] = useState<File | null>(null);
  const [returnsFile, setReturnsFile] = useState<File | null>(null);
  const [mandate, setMandate] = useState<MandateForm>(DEFAULT_MANDATE);
  const [step, setStep] = useState<"upload" | "mandate" | "analyzing">("upload");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  function handleFilesReady() {
    if (universeFile && returnsFile) setStep("mandate");
  }

  async function handleAnalyze() {
    if (!universeFile || !returnsFile) return;
    setError(null);
    setStep("analyzing");

    try {
      const uploadRes = await uploadCSVs(universeFile, returnsFile);
      setWarnings(uploadRes.warnings);
      const result = await analyze(uploadRes.session_id, mandate);
      sessionStorage.setItem(`result:${result.session_id}`, JSON.stringify(result));
      router.push(`/results/${result.session_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setStep("mandate");
    }
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="max-w-2xl mx-auto px-4 py-16">
        <div className="mb-10">
          <h1 className="text-3xl font-semibold text-gray-900 tracking-tight">
            Allocator Memo Builder
          </h1>
          <p className="mt-2 text-gray-500 text-sm">
            Upload your fund universe, define your mandate, and get a verifiable
            IC memo with a full audit trail.
          </p>
        </div>

        {/* Step 1: Upload */}
        <section className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-4">
            1 — Upload CSVs
          </h2>
          <div className="space-y-3">
            <FileInput
              label="fund_universe.csv"
              file={universeFile}
              onChange={(f) => {
                setUniverseFile(f);
                if (f && returnsFile) setStep("mandate");
              }}
            />
            <FileInput
              label="fund_returns.csv"
              file={returnsFile}
              onChange={(f) => {
                setReturnsFile(f);
                if (f && universeFile) setStep("mandate");
              }}
            />
          </div>
        </section>

        {/* Step 2: Mandate */}
        {step !== "upload" && (
          <section className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
            <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-4">
              2 — Define Mandate
            </h2>
            <div className="space-y-4">
              <Field label="Liquidity requirement">
                <select
                  value={mandate.liquidity_requirement}
                  onChange={(e) =>
                    setMandate({
                      ...mandate,
                      liquidity_requirement: e.target.value as MandateForm["liquidity_requirement"],
                    })
                  }
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
                >
                  <option value="monthly">Monthly or better</option>
                  <option value="quarterly">Quarterly or better</option>
                  <option value="annual">Annual or better</option>
                </select>
              </Field>

              <Field label="Max drawdown tolerance (%)">
                <input
                  type="number"
                  value={mandate.max_drawdown_tolerance}
                  max={0}
                  step={1}
                  onChange={(e) =>
                    setMandate({
                      ...mandate,
                      max_drawdown_tolerance: parseFloat(e.target.value),
                    })
                  }
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
                />
              </Field>

              <Field label="Volatility ceiling (%, leave blank for none)">
                <input
                  type="number"
                  placeholder="e.g. 20"
                  min={0}
                  step={1}
                  value={mandate.target_vol_max ?? ""}
                  onChange={(e) =>
                    setMandate({
                      ...mandate,
                      target_vol_max: e.target.value ? parseFloat(e.target.value) : null,
                    })
                  }
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
                />
              </Field>

              <Field label="Exclude strategies">
                <div className="flex flex-wrap gap-2">
                  {STRATEGIES.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() =>
                        setMandate({
                          ...mandate,
                          strategy_exclude: mandate.strategy_exclude.includes(s)
                            ? mandate.strategy_exclude.filter((x) => x !== s)
                            : [...mandate.strategy_exclude, s],
                        })
                      }
                      className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                        mandate.strategy_exclude.includes(s)
                          ? "bg-red-100 border-red-300 text-red-700"
                          : "bg-gray-100 border-gray-200 text-gray-600 hover:bg-gray-200"
                      }`}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </Field>
            </div>

            {warnings.length > 0 && (
              <div className="mt-4 bg-amber-50 border border-amber-200 rounded-lg p-3">
                <p className="text-xs font-semibold text-amber-700 mb-1">Data warnings</p>
                {warnings.map((w, i) => (
                  <p key={i} className="text-xs text-amber-600">· {w}</p>
                ))}
              </div>
            )}

            {error && (
              <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-3">
                <p className="text-xs text-red-600">{error}</p>
              </div>
            )}

            <button
              onClick={handleAnalyze}
              disabled={step === "analyzing"}
              className="mt-5 w-full bg-gray-900 text-white text-sm font-medium py-2.5 rounded-lg hover:bg-gray-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {step === "analyzing" ? "Analysing — this takes ~30s…" : "Generate IC Memo"}
            </button>
          </section>
        )}
      </div>
    </main>
  );
}

function FileInput({
  label,
  file,
  onChange,
}: {
  label: string;
  file: File | null;
  onChange: (f: File) => void;
}) {
  return (
    <label className="flex items-center justify-between border border-dashed border-gray-300 rounded-lg px-4 py-3 cursor-pointer hover:bg-gray-50 transition-colors">
      <span className="text-sm text-gray-500">{label}</span>
      <span className={`text-sm font-medium ${file ? "text-green-700" : "text-gray-400"}`}>
        {file ? `✓ ${file.name}` : "Choose file"}
      </span>
      <input
        type="file"
        accept=".csv"
        className="hidden"
        onChange={(e) => e.target.files?.[0] && onChange(e.target.files[0])}
      />
    </label>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-sm text-gray-600 mb-1">{label}</label>
      {children}
    </div>
  );
}
