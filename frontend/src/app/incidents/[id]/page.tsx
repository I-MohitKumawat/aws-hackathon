"use client";

import { useEffect, useState, use } from "react";
import Link from "next/link";
import { api } from "../../../lib/api-client";
import { Incident, Evidence, InvestigationJob, InvestigationReport } from "../../../lib/types";
import TraceWaterfall from "../../../components/TraceWaterfall";

const serviceColorMap: Record<string, { bg: string; text: string; border: string }> = {
  checkout: { bg: "bg-teal-50", text: "text-teal-800", border: "border-teal-300" },
  inventory: { bg: "bg-purple-50", text: "text-purple-800", border: "border-purple-300" },
  payment: { bg: "bg-emerald-50", text: "text-emerald-800", border: "border-emerald-300" },
  backend: { bg: "bg-sky-50", text: "text-sky-800", border: "border-sky-300" },
};

const severityColorMap: Record<string, { bg: string; text: string; border: string }> = {
  critical: { bg: "bg-red-50", text: "text-red-700", border: "border-red-300" },
  high: { bg: "bg-orange-50", text: "text-orange-700", border: "border-orange-300" },
  medium: { bg: "bg-amber-50", text: "text-amber-700", border: "border-amber-300" },
  low: { bg: "bg-blue-50", text: "text-blue-700", border: "border-blue-300" },
};

export default function IncidentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = use(params);
  const incidentId = resolvedParams.id;

  const [incident, setIncident] = useState<Incident | null>(null);
  const [evidenceList, setEvidenceList] = useState<Evidence[]>([]);
  const [activeJob, setActiveJob] = useState<InvestigationJob | null>(null);
  const [report, setReport] = useState<InvestigationReport | null>(null);

  const [loading, setLoading] = useState<boolean>(true);
  const [investigating, setInvestigating] = useState<boolean>(false);
  const [resolving, setResolving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Interaction states
  const [filterType, setFilterType] = useState<"all" | "trace" | "log" | "metric">("all");
  const [searchEvidence, setSearchEvidence] = useState<string>("");
  const [highlightedEvidenceId, setHighlightedEvidenceId] = useState<string | null>(null);
  const [activeWaterfallTraceId, setActiveWaterfallTraceId] = useState<string | null>(null);
  const [expandedEvidenceIds, setExpandedEvidenceIds] = useState<Record<string, boolean>>({});

  const toggleExpand = (id: string) => {
    setExpandedEvidenceIds((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  // Load Incident, Evidence, and existing Report
  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [incData, evData, repData] = await Promise.all([
        api.getIncident(incidentId),
        api.getIncidentEvidence(incidentId),
        api.getIncidentReport(incidentId).catch(() => null),
      ]);
      setIncident(incData);
      setEvidenceList(evData.items);
      if (repData) {
        setReport(repData);
      }
    } catch (err: any) {
      setError(err.message || "Failed to load incident details");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
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
        stage: "retrieving_evidence",
        progress: 20,
      });
    } catch (err: any) {
      setError(err.message || "Failed to initiate AI investigation");
      setInvestigating(false);
    }
  };

  const handleResolveIncident = async () => {
    if (!incident) return;
    try {
      setResolving(true);
      const updated = await api.resolveIncident(incident.id);
      setIncident(updated);
    } catch (err: any) {
      setError(err.message || "Failed to resolve incident");
    } finally {
      setResolving(false);
    }
  };

  const scrollToEvidence = (evId: string) => {
    const targetItem = evidenceList.find((e) => e.id === evId);
    if (targetItem && filterType !== "all" && targetItem.type !== filterType) {
      setFilterType("all");
    }
    setSearchEvidence("");
    setHighlightedEvidenceId(evId);
    setTimeout(() => {
      const el = document.getElementById(`evidence-${evId}`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }, 150);
    setTimeout(() => {
      setHighlightedEvidenceId((curr) => (curr === evId ? null : curr));
    }, 4000);
  };

  if (loading && !incident) {
    return (
      <div className="py-20 text-center text-slate-500 bg-white border border-slate-200 rounded-lg text-xs space-y-2">
        <div className="w-6 h-6 border-2 border-teal-600 border-t-transparent rounded-full animate-spin mx-auto"></div>
        <p>Loading incident details & telemetry evidence...</p>
      </div>
    );
  }

  if (error && !incident) {
    return (
      <div className="p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs space-y-2">
        <p className="font-bold">Error loading incident:</p>
        <p>{error}</p>
        <Link href="/" className="text-teal-700 underline font-semibold inline-block pt-1">
          ← Return to Incidents Dashboard
        </Link>
      </div>
    );
  }

  const traceCount = evidenceList.filter((e) => e.type === "trace").length;
  const logCount = evidenceList.filter((e) => e.type === "log").length;
  const metricCount = evidenceList.filter((e) => e.type === "metric").length;

  const filteredEvidence = evidenceList.filter((item) => {
    if (filterType !== "all" && item.type !== filterType) return false;
    if (searchEvidence.trim()) {
      const q = searchEvidence.toLowerCase();
      const matchMsg = item.message.toLowerCase().includes(q);
      const matchId = item.id.toLowerCase().includes(q);
      const matchSvc = item.service.toLowerCase().includes(q);
      return matchMsg || matchId || matchSvc;
    }
    return true;
  });

  const svcStyle = incident ? serviceColorMap[incident.service] || { bg: "bg-slate-50", text: "text-slate-700", border: "border-slate-300" } : { bg: "", text: "", border: "" };
  const sevStyle = incident ? severityColorMap[incident.severity] || { bg: "bg-slate-50", text: "text-slate-700", border: "border-slate-300" } : { bg: "", text: "", border: "" };

  // First available trace ID for quick waterfall launch
  const firstTraceItem = evidenceList.find((e) => e.trace_id);

  return (
    <div className="space-y-5 text-xs">
      {/* Top Breadcrumb */}
      <div>
        <Link
          href="/"
          className="inline-flex items-center space-x-1 text-teal-700 hover:text-teal-900 font-medium transition-colors"
        >
          <span>←</span>
          <span>Back to Incidents Search</span>
        </Link>
      </div>

      {/* Incident Header (Jaeger Trace Style) */}
      <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm space-y-3">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div className="space-y-1.5 min-w-0">
            {/* Top Badges */}
            <div className="flex items-center space-x-2 flex-wrap gap-y-1">
              <span
                className={`px-2 py-0.5 rounded font-mono font-semibold text-[11px] border uppercase ${svcStyle.bg} ${svcStyle.text} ${svcStyle.border}`}
              >
                {incident?.service}
              </span>
              <span
                className={`px-2 py-0.5 rounded font-semibold text-[11px] border uppercase ${sevStyle.bg} ${sevStyle.text} ${sevStyle.border}`}
              >
                {incident?.severity}
              </span>
              <span className="px-2 py-0.5 rounded font-semibold text-[11px] border uppercase bg-slate-100 text-slate-700 border-slate-300">
                {incident?.status}
              </span>
              {incident?.source === "auto_detected" ? (
                <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-purple-50 text-purple-700 border border-purple-200 flex items-center space-x-1">
                  <span>⚡</span>
                  <span>Auto-Detected</span>
                </span>
              ) : (
                <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 text-slate-600 border border-slate-200">
                  Manual
                </span>
              )}
              {incident?.detection_rule && (
                <span className="px-1.5 py-0.5 rounded font-mono text-[11px] bg-slate-50 text-slate-600 border border-slate-200">
                  rule:{incident.detection_rule}
                </span>
              )}
            </div>

            {/* Title */}
            <h1 className="text-lg font-bold text-slate-900 tracking-tight">
              {incident?.title}
            </h1>
            {incident?.description && (
              <p className="text-slate-600 leading-relaxed">{incident.description}</p>
            )}
          </div>

          {/* Action Buttons */}
          <div className="flex items-center space-x-2 shrink-0">
            {incident?.status !== "resolved" && (
              <button
                onClick={handleResolveIncident}
                disabled={resolving}
                className="px-3 py-1.5 rounded bg-white hover:bg-slate-50 disabled:opacity-50 border border-slate-300 text-slate-700 font-medium text-xs transition-colors shadow-sm cursor-pointer"
              >
                {resolving ? "Resolving..." : "Mark Resolved"}
              </button>
            )}

            <button
              onClick={handleStartInvestigation}
              disabled={investigating}
              className="px-4 py-1.5 rounded bg-teal-600 hover:bg-teal-700 disabled:bg-teal-800 disabled:opacity-60 text-white font-medium text-xs tracking-wide shadow-sm transition-colors flex items-center space-x-1.5 cursor-pointer"
            >
              {investigating ? (
                <>
                  <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                  <span>Investigating...</span>
                </>
              ) : (
                <span>Trigger AI Investigation</span>
              )}
            </button>
          </div>
        </div>

        {/* Jaeger Metadata Summary Bar */}
        <div className="pt-2.5 border-t border-slate-100 flex items-center space-x-4 text-[11px] text-slate-500 font-mono flex-wrap gap-y-1">
          <span>Incident ID: <strong className="text-slate-700 select-all">{incident?.id}</strong></span>
          <span>•</span>
          <span>Started: <strong className="text-slate-700">{incident ? new Date(incident.started_at).toLocaleString() : ""}</strong></span>
          {incident?.ended_at && (
            <>
              <span>•</span>
              <span className="text-emerald-700">Resolved: <strong>{new Date(incident.ended_at).toLocaleString()}</strong></span>
            </>
          )}
          <span>•</span>
          <span>Evidence Count: <strong className="text-slate-700">{evidenceList.length}</strong></span>
          {firstTraceItem?.trace_id && (
            <>
              <span>•</span>
              <button
                onClick={() => setActiveWaterfallTraceId(firstTraceItem.trace_id!)}
                className="text-teal-700 hover:text-teal-900 underline font-semibold flex items-center space-x-1 cursor-pointer"
              >
                <span>Trace Waterfall</span>
                <span>⚡</span>
              </button>
              <a
                href={`http://localhost:16686/trace/${firstTraceItem.trace_id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-slate-500 hover:text-teal-700 underline"
              >
                Jaeger ↗
              </a>
            </>
          )}
        </div>
      </div>

      {/* Auto-Detection Reason Box */}
      {incident?.source === "auto_detected" && (
        <div className="bg-purple-50/60 border border-purple-200 rounded-lg p-3.5 space-y-1.5">
          <div className="flex items-center space-x-2 text-purple-900 font-semibold text-xs">
            <span>⚡ Automatically Correlated & Detected</span>
            {incident.detection_rule && (
              <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-purple-100 border border-purple-300">
                {incident.detection_rule}
              </span>
            )}
          </div>
          {incident.detection_reason && (
            <p className="text-purple-950 font-mono text-[11px] leading-relaxed">
              <strong>Trigger Reason:</strong> {incident.detection_reason}
            </p>
          )}
        </div>
      )}

      {/* Real Investigation Job Progress (No Fake Animations) */}
      {activeJob && (
        <div className="bg-white border border-teal-200 rounded-lg p-4 shadow-sm space-y-2.5">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center space-x-2">
              <span className="font-bold text-slate-900">AI Investigation Progress</span>
              <span className="text-slate-500 font-mono text-[11px]">Job: {activeJob.job_id}</span>
            </div>
            <span className="px-2 py-0.5 rounded font-mono font-semibold text-[10px] uppercase bg-teal-50 text-teal-800 border border-teal-200">
              {activeJob.status}
            </span>
          </div>

          {activeJob.stage && (
            <p className="text-slate-600 text-xs">
              Current Stage:{" "}
              <strong className="font-mono text-slate-800">{activeJob.stage}</strong>
              {activeJob.stage === "retrieving_evidence" && " (Querying PostgreSQL evidence records)"}
              {activeJob.stage === "analyzing_evidence" && " (Prompting Ollama qwen3:4b with telemetry context)"}
            </p>
          )}

          {activeJob.progress !== null && activeJob.progress !== undefined && (
            <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden border border-slate-200">
              <div
                className="bg-teal-600 h-2 rounded-full transition-all duration-500"
                style={{ width: `${activeJob.progress}%` }}
              ></div>
            </div>
          )}
        </div>
      )}

      {/* AI Investigation Report */}
      {report ? (
        <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm space-y-4">
          <div className="border-b border-slate-100 pb-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-bold text-slate-900 flex items-center space-x-2">
                <span>🤖 AI Investigation Report</span>
              </h2>
              <p className="text-[11px] text-slate-500 font-mono mt-0.5">
                Generated: {new Date(report.created_at).toLocaleString()} • Model: Ollama qwen3:4b
              </p>
            </div>
            <button
              onClick={handleStartInvestigation}
              disabled={investigating}
              className="px-2.5 py-1 rounded bg-slate-100 hover:bg-slate-200 border border-slate-300 text-slate-700 font-medium text-xs transition-colors cursor-pointer self-start sm:self-auto"
            >
              Re-run Investigation ↻
            </button>
          </div>

          {/* Report Summary */}
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-3.5 space-y-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500 block">
              Incident Summary & Diagnosis
            </span>
            <p className="text-slate-800 leading-relaxed text-xs font-medium">
              {report.summary}
            </p>
          </div>

          {/* Root-Cause Hypotheses & Evidence Correlations */}
          <div className="space-y-3">
            <h3 className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
              Root-Cause Hypotheses & Evidence Citations
            </h3>

            {report.hypotheses.map((hyp) => {
              const statusPill =
                hyp.status === "supported"
                  ? "bg-emerald-50 text-emerald-800 border-emerald-300"
                  : hyp.status === "possible"
                  ? "bg-amber-50 text-amber-800 border-amber-300"
                  : "bg-slate-100 text-slate-700 border-slate-300";

              return (
                <div
                  key={hyp.id}
                  className="bg-white border border-slate-200 rounded-lg p-3.5 space-y-2.5"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold text-teal-800 text-xs">
                      #{hyp.id}
                    </span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${statusPill}`}>
                      {hyp.status}
                    </span>
                  </div>

                  <p className="text-slate-900 font-semibold text-xs leading-normal">
                    {hyp.description}
                  </p>

                  {/* Supporting Evidence Citations */}
                  <div className="space-y-2 text-xs pt-1">
                    {hyp.supporting_evidence && hyp.supporting_evidence.length > 0 && (
                      <div className="flex items-center space-x-2 flex-wrap gap-y-1">
                        <span className="font-semibold text-emerald-700 text-[11px]">
                          Supporting Evidence:
                        </span>
                        {hyp.supporting_evidence.map((evId) => (
                          <button
                            key={evId}
                            onClick={() => scrollToEvidence(evId)}
                            title={`Click to scroll to evidence record ${evId}`}
                            className="inline-flex items-center space-x-1 px-2 py-0.5 rounded bg-emerald-50 hover:bg-emerald-100 text-emerald-800 font-mono text-[11px] border border-emerald-300 transition-colors cursor-pointer"
                          >
                            <span>{evId}</span>
                            <span className="text-[10px]">↓</span>
                          </button>
                        ))}
                      </div>
                    )}

                    {/* Contradicting Evidence Citations */}
                    {hyp.contradicting_evidence && hyp.contradicting_evidence.length > 0 && (
                      <div className="flex items-center space-x-2 flex-wrap gap-y-1">
                        <span className="font-semibold text-red-700 text-[11px]">
                          Contradicting Evidence:
                        </span>
                        {hyp.contradicting_evidence.map((evId) => (
                          <button
                            key={evId}
                            onClick={() => scrollToEvidence(evId)}
                            title={`Click to scroll to evidence record ${evId}`}
                            className="inline-flex items-center space-x-1 px-2 py-0.5 rounded bg-red-50 hover:bg-red-100 text-red-800 font-mono text-[11px] border border-red-300 transition-colors cursor-pointer"
                          >
                            <span>{evId}</span>
                            <span className="text-[10px]">↓</span>
                          </button>
                        ))}
                      </div>
                    )}

                    {/* Missing Evidence */}
                    {hyp.missing_evidence && hyp.missing_evidence.length > 0 && (
                      <div className="flex items-center space-x-2 flex-wrap gap-y-1">
                        <span className="font-semibold text-amber-700 text-[11px]">
                          Missing Evidence:
                        </span>
                        {hyp.missing_evidence.map((item, idx) => (
                          <span
                            key={idx}
                            className="px-2 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-300 text-[11px]"
                          >
                            {item}
                          </span>
                        ))}
                      </div>
                    )}

                    {/* Recommended Next Step */}
                    {hyp.next_step && (
                      <div className="bg-slate-50 border border-slate-200 rounded p-2.5 text-slate-700 mt-2">
                        <span className="font-bold text-slate-900">Recommended Next Step: </span>
                        <span>{hyp.next_step}</span>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : !activeJob ? (
        <div className="bg-white border border-dashed border-slate-300 rounded-lg p-6 text-center space-y-2">
          <p className="font-bold text-slate-700 text-xs">No AI Investigation Report Generated Yet</p>
          <p className="text-slate-500 text-xs max-w-md mx-auto">
            Click &quot;Trigger AI Investigation&quot; above to prompt local Ollama (qwen3:4b) with real PostgreSQL telemetry evidence and generate diagnostic root-cause hypotheses.
          </p>
        </div>
      ) : null}

      {/* Telemetry Evidence Section */}
      <div className="space-y-3">
        {/* Controls Bar */}
        <div className="bg-white border border-slate-200 rounded-lg p-3 shadow-sm flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          {/* Tabs */}
          <div className="flex items-center space-x-1.5 text-xs">
            <button
              onClick={() => setFilterType("all")}
              className={`px-3 py-1 rounded font-medium transition-colors ${
                filterType === "all"
                  ? "bg-teal-600 text-white shadow-xs"
                  : "bg-slate-100 hover:bg-slate-200 text-slate-700"
              }`}
            >
              All ({evidenceList.length})
            </button>
            <button
              onClick={() => setFilterType("trace")}
              className={`px-3 py-1 rounded font-medium transition-colors ${
                filterType === "trace"
                  ? "bg-teal-600 text-white shadow-xs"
                  : "bg-slate-100 hover:bg-slate-200 text-slate-700"
              }`}
            >
              Traces ({traceCount})
            </button>
            <button
              onClick={() => setFilterType("log")}
              className={`px-3 py-1 rounded font-medium transition-colors ${
                filterType === "log"
                  ? "bg-teal-600 text-white shadow-xs"
                  : "bg-slate-100 hover:bg-slate-200 text-slate-700"
              }`}
            >
              Logs ({logCount})
            </button>
            <button
              onClick={() => setFilterType("metric")}
              className={`px-3 py-1 rounded font-medium transition-colors ${
                filterType === "metric"
                  ? "bg-teal-600 text-white shadow-xs"
                  : "bg-slate-100 hover:bg-slate-200 text-slate-700"
              }`}
            >
              Metrics ({metricCount})
            </button>
          </div>

          {/* Search within evidence */}
          <div className="w-full sm:w-64">
            <input
              type="text"
              placeholder="Search evidence..."
              value={searchEvidence}
              onChange={(e) => setSearchEvidence(e.target.value)}
              className="w-full bg-slate-50 border border-slate-300 rounded px-2.5 py-1 text-slate-800 text-xs focus:bg-white focus:border-teal-600 focus:outline-none"
            />
          </div>
        </div>

        {/* Evidence Records List */}
        {filteredEvidence.length === 0 ? (
          <div className="bg-white border border-dashed border-slate-300 rounded-lg p-8 text-center text-slate-500">
            {evidenceList.length === 0
              ? "No telemetry evidence recorded for this incident yet."
              : `No evidence found matching type "${filterType}".`}
          </div>
        ) : (
          <div className="space-y-2">
            {filteredEvidence.map((item) => {
              const isHighlighted = highlightedEvidenceId === item.id;
              const isExpanded = Boolean(expandedEvidenceIds[item.id]);
              const meta = item.metadata || {};

              const typeBadge =
                item.type === "trace"
                  ? "bg-indigo-50 text-indigo-800 border-indigo-200"
                  : item.type === "log"
                  ? "bg-sky-50 text-sky-800 border-sky-200"
                  : item.type === "metric"
                  ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                  : "bg-slate-100 text-slate-700 border-slate-200";

              const sev = item.severity?.toLowerCase();
              const sevBadge =
                sev === "error" || sev === "critical"
                  ? "bg-red-50 text-red-700 border-red-200"
                  : sev === "warn" || sev === "warning"
                  ? "bg-amber-50 text-amber-700 border-amber-200"
                  : "bg-slate-100 text-slate-600 border-slate-200";

              return (
                <div
                  key={item.id}
                  id={`evidence-${item.id}`}
                  className={`bg-white border rounded-lg p-3 space-y-2 transition-all duration-300 ${
                    isHighlighted
                      ? "border-teal-500 ring-2 ring-teal-400 bg-teal-50/50 shadow-md"
                      : "border-slate-200 hover:border-slate-300"
                  }`}
                >
                  <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2">
                    <div className="space-y-1 min-w-0 flex-1">
                      {/* Top Identifiers */}
                      <div className="flex items-center space-x-2 flex-wrap gap-y-1">
                        <span className="font-mono font-bold text-teal-800 text-[11px] select-all">
                          {item.id}
                        </span>
                        <span className={`px-1.5 py-0.5 rounded font-mono font-semibold text-[10px] border uppercase ${typeBadge}`}>
                          {item.type}
                        </span>
                        {item.severity && (
                          <span className={`px-1.5 py-0.5 rounded font-semibold text-[10px] border uppercase ${sevBadge}`}>
                            {item.severity}
                          </span>
                        )}
                        <span className="font-mono text-slate-700 bg-slate-100 px-1.5 py-0.5 rounded text-[11px] border border-slate-200">
                          {item.service}
                        </span>

                        {/* Metric info pill */}
                        {item.type === "metric" && meta.metric_name ? (
                          <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-800 border border-emerald-200 font-mono text-[10px]">
                            {String(meta.metric_name)}: {String(meta.value ?? "")} {String(meta.unit ?? "")}
                          </span>
                        ) : null}

                        {/* Trace duration pill */}
                        {item.type === "trace" && meta.duration_ms !== undefined ? (
                          <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 font-mono text-[10px]">
                            {Number(meta.duration_ms).toFixed(1)}ms
                          </span>
                        ) : null}
                      </div>

                      {/* Message Content */}
                      <p className="text-slate-800 break-words leading-relaxed text-xs">
                        {item.message}
                      </p>
                    </div>

                    {/* Actions and Timestamp on right */}
                    <div className="flex sm:flex-col sm:items-end justify-between items-center text-slate-500 font-mono text-[11px] shrink-0 space-y-1">
                      <span>{new Date(item.timestamp).toISOString()}</span>
                      <div className="flex items-center space-x-2">
                        {item.trace_id && (
                          <>
                            <button
                              onClick={() => setActiveWaterfallTraceId(item.trace_id!)}
                              className="px-2 py-0.5 rounded bg-teal-50 hover:bg-teal-100 text-teal-800 border border-teal-200 transition-colors text-[10px] font-semibold cursor-pointer"
                            >
                              Trace Waterfall ⚡
                            </button>
                            <a
                              href={`http://localhost:16686/trace/${item.trace_id}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-slate-500 hover:text-teal-700 underline text-[10px]"
                            >
                              Jaeger ↗
                            </a>
                          </>
                        )}
                        <button
                          onClick={() => toggleExpand(item.id)}
                          className="px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-300 text-[10px] cursor-pointer"
                        >
                          {isExpanded ? "Hide JSON ▲" : "Attributes ▼"}
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Expanded JSON Inspector */}
                  {isExpanded && (
                    <div className="pt-2 border-t border-slate-100 space-y-1">
                      <span className="text-slate-400 font-mono text-[10px] block uppercase font-bold">
                        TELEMETRY ATTRIBUTES / PAYLOAD:
                      </span>
                      <pre className="p-2.5 rounded bg-slate-50 border border-slate-200 text-[11px] text-slate-800 overflow-x-auto font-mono max-h-56 leading-relaxed select-all">
                        {JSON.stringify(
                          {
                            id: item.id,
                            service: item.service,
                            type: item.type,
                            timestamp: item.timestamp,
                            trace_id: item.trace_id,
                            severity: item.severity,
                            metadata: item.metadata,
                          },
                          null,
                          2
                        )}
                      </pre>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Trace Waterfall Modal */}
      {activeWaterfallTraceId && (
        <TraceWaterfall
          traceId={activeWaterfallTraceId}
          incidentId={incidentId}
          onClose={() => setActiveWaterfallTraceId(null)}
        />
      )}
    </div>
  );
}
