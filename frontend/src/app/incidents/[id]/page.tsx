"use client";

import { useEffect, useState, use } from "react";
import { api } from "../../../lib/api-client";
import { Incident, Evidence, InvestigationJob, InvestigationReport } from "../../../lib/types";

export default function IncidentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = use(params);
  const incidentId = resolvedParams.id;

  const [incident, setIncident] = useState<Incident | null>(null);
  const [evidenceList, setEvidenceList] = useState<Evidence[]>([]);
  const [activeJob, setActiveJob] = useState<InvestigationJob | null>(null);
  const [report, setReport] = useState<InvestigationReport | null>(null);

  const [loading, setLoading] = useState<boolean>(true);
  const [investigating, setInvestigating] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Load Incident and Evidence
  useEffect(() => {
    async function loadData() {
      try {
        setLoading(true);
        setError(null);
        const [incData, evData] = await Promise.all([
          api.getIncident(incidentId),
          api.getIncidentEvidence(incidentId),
        ]);
        setIncident(incData);
        setEvidenceList(evData.items);
      } catch (err: any) {
        setError(err.message || "Failed to load incident details");
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [incidentId]);

  // Polling for Investigation Job Progress
  useEffect(() => {
    if (!activeJob || activeJob.status === "completed" || activeJob.status === "failed") {
      return;
    }

    const interval = setInterval(async () => {
      try {
        const job = await api.getInvestigationJob(activeJob.job_id);
        setActiveJob(job);
        if (job.status === "completed") {
          const rep = await api.getInvestigationReport(job.job_id);
          setReport(rep);
          setInvestigating(false);
        } else if (job.status === "failed") {
          setInvestigating(false);
          setError(job.error || "Investigation job failed");
        }
      } catch (err: any) {
        console.error("Job poll error:", err);
      }
    }, 2500);

    return () => clearInterval(interval);
  }, [activeJob]);

  const handleStartInvestigation = async () => {
    try {
      setInvestigating(true);
      setError(null);
      const res = await api.startInvestigation(incidentId);
      setActiveJob({
        job_id: res.job_id,
        incident_id: res.incident_id,
        status: res.status as any,
        created_at: res.created_at,
      });
    } catch (err: any) {
      setError(err.message || "Failed to initiate investigation");
      setInvestigating(false);
    }
  };

  if (loading) {
    return <div className="py-16 text-center text-slate-500">Loading incident and telemetry...</div>;
  }

  if (error && !incident) {
    return (
      <div className="p-4 rounded-lg bg-red-950/40 border border-red-800 text-red-300">
        {error}
      </div>
    );
  }

  const [filterType, setFilterType] = useState<"all" | "trace" | "log" | "metric">("all");

  const traceCount = evidenceList.filter((e) => e.type === "trace").length;
  const logCount = evidenceList.filter((e) => e.type === "log").length;
  const metricCount = evidenceList.filter((e) => e.type === "metric").length;

  const filteredEvidence = evidenceList.filter((item) => {
    if (filterType === "all") return true;
    return item.type === filterType;
  });

  return (
    <div className="space-y-8">
      {/* Back button and Header */}
      <div>
        <a href="/" className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors">
          ← Back to Incident Dashboard
        </a>
        <div className="mt-3 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center space-x-2">
              <span className="text-xs uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-orange-500/10 text-orange-400 border border-orange-500/20">
                {incident?.severity}
              </span>
              <span className="text-xs font-mono text-indigo-400 bg-indigo-950/50 px-2 py-0.5 rounded">
                svc:{incident?.service}
              </span>
              <span className="text-xs text-slate-400 font-mono">ID: {incident?.id}</span>
            </div>
            <h1 className="text-2xl font-bold text-white mt-1">{incident?.title}</h1>
            {incident?.description && (
              <p className="text-sm text-slate-400 mt-1">{incident.description}</p>
            )}
          </div>

          <div>
            <button
              onClick={handleStartInvestigation}
              disabled={investigating}
              className="px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-900 disabled:text-indigo-400 text-white text-sm font-medium transition-all shadow-lg shadow-indigo-600/20 flex items-center space-x-2"
            >
              {investigating ? (
                <>
                  <span className="w-2 h-2 rounded-full bg-white animate-ping"></span>
                  <span>Investigating...</span>
                </>
              ) : (
                <span>Trigger AI Investigation</span>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Investigation Progress Card */}
      {activeJob && (
        <div className="p-5 rounded-xl bg-slate-900 border border-indigo-900/60 shadow-lg space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <span className="text-sm font-semibold text-white">Investigation Progress</span>
              <span className="text-xs font-mono text-indigo-400">Job: {activeJob.job_id}</span>
            </div>
            <span className="text-xs uppercase px-2 py-0.5 rounded bg-indigo-950 text-indigo-300 font-medium">
              {activeJob.status}
            </span>
          </div>

          {activeJob.stage && (
            <p className="text-xs text-slate-400">
              Current Stage: <span className="font-mono text-slate-200">{activeJob.stage}</span>
            </p>
          )}

          {activeJob.progress !== null && activeJob.progress !== undefined && (
            <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
              <div
                className="bg-indigo-500 h-2 rounded-full transition-all duration-500"
                style={{ width: `${activeJob.progress}%` }}
              ></div>
            </div>
          )}
        </div>
      )}

      {/* AI Investigation Report */}
      {report && (
        <div className="p-6 rounded-xl bg-slate-900/80 border border-slate-700 shadow-xl space-y-6">
          <div className="border-b border-slate-800 pb-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white flex items-center space-x-2">
                <span>🤖 AI Investigation Report</span>
              </h2>
              <span className="text-xs text-slate-400">
                Generated: {new Date(report.created_at).toLocaleString()}
              </span>
            </div>
            <p className="text-sm text-slate-300 mt-2">{report.summary}</p>
          </div>

          <div className="space-y-4">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Root-Cause Hypotheses & Evidence Correlations
            </h3>

            {report.hypotheses.map((hyp) => (
              <div
                key={hyp.id}
                className="p-4 rounded-lg bg-slate-950/60 border border-slate-800 space-y-3"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-mono text-indigo-400">{hyp.id}</span>
                  <span
                    className={`text-xs px-2 py-0.5 rounded font-medium ${
                      hyp.status === "supported"
                        ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                        : hyp.status === "possible"
                        ? "bg-amber-950 text-amber-400 border border-amber-800"
                        : "bg-slate-800 text-slate-400"
                    }`}
                  >
                    {hyp.status.toUpperCase()}
                  </span>
                </div>

                <p className="text-sm font-medium text-white">{hyp.description}</p>

                <div className="space-y-2 text-xs">
                  {hyp.supporting_evidence.length > 0 && (
                    <div className="flex items-center space-x-2 flex-wrap gap-1">
                      <span className="text-emerald-400 font-medium">Supporting Evidence:</span>
                      {hyp.supporting_evidence.map((evId) => (
                        <span key={evId} className="px-2 py-0.5 rounded bg-emerald-950/80 text-emerald-300 font-mono">
                          {evId}
                        </span>
                      ))}
                    </div>
                  )}

                  {hyp.contradicting_evidence && hyp.contradicting_evidence.length > 0 && (
                    <div className="flex items-center space-x-2 flex-wrap gap-1">
                      <span className="text-rose-400 font-medium">Contradicting Evidence:</span>
                      {hyp.contradicting_evidence.map((evId) => (
                        <span key={evId} className="px-2 py-0.5 rounded bg-rose-950/80 text-rose-300 font-mono">
                          {evId}
                        </span>
                      ))}
                    </div>
                  )}

                  {hyp.missing_evidence.length > 0 && (
                    <div className="flex items-center space-x-2 flex-wrap gap-1">
                      <span className="text-amber-400 font-medium">Missing Evidence:</span>
                      {hyp.missing_evidence.map((item, idx) => (
                        <span key={idx} className="px-2 py-0.5 rounded bg-amber-950/80 text-amber-300">
                          {item}
                        </span>
                      ))}
                    </div>
                  )}

                  {hyp.next_step && (
                    <div className="p-2.5 rounded bg-indigo-950/40 border border-indigo-900/40 text-indigo-200 mt-2">
                      <span className="font-semibold text-white">Recommended Next Step: </span>
                      {hyp.next_step}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Telemetry Evidence Timeline */}
      <div className="space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
          <div>
            <h2 className="text-base font-semibold text-white">Telemetry & Evidence Timeline</h2>
            <p className="text-xs text-slate-400">
              Unified traces, structured logs, and operational metrics correlated for this incident.
            </p>
          </div>

          {/* Filter Pills */}
          <div className="flex items-center space-x-1.5 bg-slate-900/80 p-1 rounded-lg border border-slate-800 text-xs">
            <button
              onClick={() => setFilterType("all")}
              className={`px-2.5 py-1 rounded transition-colors ${
                filterType === "all"
                  ? "bg-slate-700 text-white font-medium shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              All ({evidenceList.length})
            </button>
            <button
              onClick={() => setFilterType("trace")}
              className={`px-2.5 py-1 rounded transition-colors ${
                filterType === "trace"
                  ? "bg-indigo-600 text-white font-medium shadow-sm"
                  : "text-slate-400 hover:text-indigo-300"
              }`}
            >
              Traces ({traceCount})
            </button>
            <button
              onClick={() => setFilterType("log")}
              className={`px-2.5 py-1 rounded transition-colors ${
                filterType === "log"
                  ? "bg-cyan-600 text-white font-medium shadow-sm"
                  : "text-slate-400 hover:text-cyan-300"
              }`}
            >
              Logs ({logCount})
            </button>
            <button
              onClick={() => setFilterType("metric")}
              className={`px-2.5 py-1 rounded transition-colors ${
                filterType === "metric"
                  ? "bg-emerald-600 text-white font-medium shadow-sm"
                  : "text-slate-400 hover:text-emerald-300"
              }`}
            >
              Metrics ({metricCount})
            </button>
          </div>
        </div>

        {filteredEvidence.length === 0 ? (
          <div className="p-8 text-center text-slate-500 text-sm border border-dashed border-slate-800 rounded-xl">
            {evidenceList.length === 0
              ? "No telemetry evidence recorded yet."
              : `No evidence found matching type "${filterType}".`}
          </div>
        ) : (
          <div className="space-y-2.5">
            {filteredEvidence.map((item) => {
              // Badge color depending on type
              const typeBadgeClass =
                item.type === "trace"
                  ? "bg-indigo-950/80 text-indigo-300 border border-indigo-800/60"
                  : item.type === "log"
                  ? "bg-cyan-950/80 text-cyan-300 border border-cyan-800/60"
                  : item.type === "metric"
                  ? "bg-emerald-950/80 text-emerald-300 border border-emerald-800/60"
                  : "bg-slate-800 text-slate-300 border border-slate-700";

              // Severity badge color
              const sev = item.severity?.toLowerCase();
              const sevBadgeClass =
                sev === "error" || sev === "critical"
                  ? "bg-rose-950/70 text-rose-300 border border-rose-800/60"
                  : sev === "warn" || sev === "warning"
                  ? "bg-amber-950/70 text-amber-300 border border-amber-800/60"
                  : sev === "info"
                  ? "bg-blue-950/70 text-blue-300 border border-blue-800/60"
                  : "bg-slate-800/80 text-slate-400 border border-slate-700/60";

              const meta = item.metadata || {};

              return (
                <div
                  key={item.id}
                  className="p-3.5 rounded-lg bg-slate-900/50 border border-slate-800/80 hover:border-slate-700 transition-colors flex flex-col md:flex-row md:items-start justify-between gap-3 text-xs"
                >
                  <div className="space-y-1.5 flex-1 min-w-0">
                    <div className="flex items-center space-x-2 flex-wrap gap-y-1">
                      <span className="font-mono text-indigo-400 font-semibold">{item.id}</span>
                      <span className={`uppercase px-1.5 py-0.5 rounded font-semibold text-[10px] tracking-wide ${typeBadgeClass}`}>
                        {item.type}
                      </span>
                      {item.severity && (
                        <span className={`uppercase px-1.5 py-0.5 rounded font-semibold text-[10px] ${sevBadgeClass}`}>
                          {item.severity}
                        </span>
                      )}
                      <span className="text-slate-400 font-mono">svc:{item.service}</span>

                      {/* Specialized Metadata Pill */}
                      {item.type === "trace" && meta.duration_ms !== undefined ? (
                        <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 font-mono text-[10px]">
                          {Number(meta.duration_ms).toFixed(1)}ms
                        </span>
                      ) : null}
                      {item.type === "metric" && meta.metric_name ? (
                        <span className="px-1.5 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-800/40 font-mono text-[10px]">
                          {String(meta.metric_name)}: {String(meta.value ?? "")} {String(meta.unit ?? "")}
                        </span>
                      ) : null}
                    </div>

                    <p className="text-sm text-slate-200 break-words font-sans">{item.message}</p>
                  </div>

                  <div className="text-slate-500 flex flex-col md:items-end font-mono text-[11px] shrink-0 space-y-0.5">
                    <span>{new Date(item.timestamp).toISOString()}</span>
                    {item.trace_id ? (
                      <span className="text-indigo-400 hover:text-indigo-300" title={`Span: ${meta.span_id || "N/A"}`}>
                        trace:{item.trace_id.slice(0, 16)}...
                      </span>
                    ) : null}
                    {meta.span_id ? (
                      <span className="text-slate-500 text-[10px]">
                        span:{String(meta.span_id).slice(0, 8)}...
                      </span>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
