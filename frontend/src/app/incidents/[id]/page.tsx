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
        <h2 className="text-base font-semibold text-white">Telemetry & Evidence Timeline</h2>
        {evidenceList.length === 0 ? (
          <div className="p-8 text-center text-slate-500 text-sm border border-dashed border-slate-800 rounded-xl">
            No telemetry evidence recorded yet.
          </div>
        ) : (
          <div className="space-y-2.5">
            {evidenceList.map((item) => (
              <div
                key={item.id}
                className="p-3.5 rounded-lg bg-slate-900/50 border border-slate-800/80 hover:border-slate-700 flex flex-col md:flex-row md:items-center justify-between gap-3 text-xs"
              >
                <div className="space-y-1">
                  <div className="flex items-center space-x-2">
                    <span className="font-mono text-indigo-400 font-medium">{item.id}</span>
                    <span className="uppercase px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 font-semibold">
                      {item.type}
                    </span>
                    {item.severity && (
                      <span className="px-1.5 py-0.5 rounded bg-red-950/60 text-red-400 border border-red-800/50 uppercase font-semibold">
                        {item.severity}
                      </span>
                    )}
                    <span className="text-slate-400 font-mono">svc:{item.service}</span>
                  </div>
                  <p className="text-sm text-slate-200">{item.message}</p>
                </div>

                <div className="text-slate-500 flex flex-col md:items-end font-mono">
                  <span>{new Date(item.timestamp).toISOString()}</span>
                  {item.trace_id && <span className="text-indigo-400">trace:{item.trace_id}</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
