"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { api } from "../../lib/api-client";
import { Evidence } from "../../lib/types";
import TraceWaterfall from "../../components/TraceWaterfall";

const serviceColorMap: Record<string, { bg: string; text: string; border: string }> = {
  checkout: { bg: "bg-teal-50", text: "text-teal-800", border: "border-teal-300" },
  inventory: { bg: "bg-purple-50", text: "text-purple-800", border: "border-purple-300" },
  payment: { bg: "bg-emerald-50", text: "text-emerald-800", border: "border-emerald-300" },
  backend: { bg: "bg-sky-50", text: "text-sky-800", border: "border-sky-300" },
};

export default function TelemetryPage() {
  const [evidenceList, setEvidenceList] = useState<Evidence[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [service, setService] = useState<string>("");
  const [type, setType] = useState<string>("");
  const [severity, setSeverity] = useState<string>("");
  const [search, setSearch] = useState<string>("");
  const [autoRefresh, setAutoRefresh] = useState<boolean>(false);
  const [page, setPage] = useState<number>(0);
  const pageSize = 25;

  // Waterfall modal
  const [activeTraceId, setActiveTraceId] = useState<string | null>(null);
  const [activeIncidentId, setActiveIncidentId] = useState<string>("");

  // Expanded items
  const [expandedIds, setExpandedIds] = useState<Record<string, boolean>>({});

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const fetchEvidence = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.getGlobalEvidence({
        limit: pageSize,
        offset: page * pageSize,
        service: service || undefined,
        type: type || undefined,
        severity: severity || undefined,
        search: search.trim() || undefined,
      });
      setEvidenceList(res.items);
      setTotal(res.total);
    } catch (err: any) {
      setError(err.message || "Failed to load telemetry evidence");
    } finally {
      setLoading(false);
    }
  }, [page, service, type, severity, search]);

  useEffect(() => {
    fetchEvidence();
  }, [fetchEvidence]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      fetchEvidence();
    }, 4000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchEvidence]);

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="space-y-4 text-xs">
      {/* Header Bar */}
      <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <div className="flex items-center space-x-2">
            <h2 className="text-base font-bold text-slate-900">Live Telemetry Explorer</h2>
            <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-teal-50 text-teal-800 border border-teal-200 font-semibold">
              {total.toLocaleString()} Records
            </span>
          </div>
          <p className="text-slate-600 mt-0.5">
            Real-time telemetry stream including distributed traces, structured logs, and metrics ingested via OpenTelemetry Collector.
          </p>
        </div>

        {/* Refresh controls */}
        <div className="flex items-center space-x-3 text-xs shrink-0">
          <label className="flex items-center space-x-1.5 cursor-pointer text-slate-600 hover:text-slate-900 select-none">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded border-slate-300 text-teal-600 focus:ring-0 cursor-pointer"
            />
            <span className="text-[11px]">Live Auto-Refresh (4s)</span>
          </label>

          <button
            onClick={() => fetchEvidence()}
            className="px-2.5 py-1 rounded bg-slate-100 hover:bg-slate-200 border border-slate-300 text-slate-700 font-medium text-xs transition-colors flex items-center space-x-1 cursor-pointer"
          >
            <span>↻</span>
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="bg-white border border-slate-200 rounded-lg p-3.5 shadow-sm grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-3">
        {/* Search */}
        <div className="md:col-span-2 space-y-1">
          <label className="text-slate-600 font-semibold block text-[11px]">Search Text</label>
          <input
            type="text"
            placeholder="Search message or attributes..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
            className="w-full bg-slate-50 border border-slate-300 rounded px-2.5 py-1 text-slate-800 text-xs focus:bg-white focus:border-teal-600 focus:outline-none"
          />
        </div>

        {/* Service */}
        <div className="space-y-1">
          <label className="text-slate-600 font-semibold block text-[11px]">Service</label>
          <select
            value={service}
            onChange={(e) => {
              setService(e.target.value);
              setPage(0);
            }}
            className="w-full bg-slate-50 border border-slate-300 rounded px-2 py-1 text-slate-800 text-xs focus:bg-white focus:border-teal-600 focus:outline-none"
          >
            <option value="">All Services</option>
            <option value="checkout">checkout</option>
            <option value="inventory">inventory</option>
            <option value="payment">payment</option>
            <option value="backend">backend</option>
          </select>
        </div>

        {/* Type */}
        <div className="space-y-1">
          <label className="text-slate-600 font-semibold block text-[11px]">Telemetry Type</label>
          <select
            value={type}
            onChange={(e) => {
              setType(e.target.value);
              setPage(0);
            }}
            className="w-full bg-slate-50 border border-slate-300 rounded px-2 py-1 text-slate-800 text-xs focus:bg-white focus:border-teal-600 focus:outline-none"
          >
            <option value="">All Types</option>
            <option value="trace">Traces</option>
            <option value="log">Logs</option>
            <option value="metric">Metrics</option>
          </select>
        </div>

        {/* Severity */}
        <div className="space-y-1">
          <label className="text-slate-600 font-semibold block text-[11px]">Severity</label>
          <select
            value={severity}
            onChange={(e) => {
              setSeverity(e.target.value);
              setPage(0);
            }}
            className="w-full bg-slate-50 border border-slate-300 rounded px-2 py-1 text-slate-800 text-xs focus:bg-white focus:border-teal-600 focus:outline-none"
          >
            <option value="">All Severities</option>
            <option value="error">error / critical</option>
            <option value="warning">warning</option>
            <option value="info">info</option>
          </select>
        </div>
      </div>

      {/* Error Message */}
      {error && (
        <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs">
          {error}
        </div>
      )}

      {/* Telemetry Stream List */}
      <div className="space-y-2">
        {loading && evidenceList.length === 0 ? (
          <div className="py-16 text-center text-slate-500 bg-white border border-slate-200 rounded-lg text-xs space-y-2">
            <div className="w-5 h-5 border-2 border-teal-600 border-t-transparent rounded-full animate-spin mx-auto"></div>
            <p>Loading telemetry records...</p>
          </div>
        ) : evidenceList.length === 0 ? (
          <div className="bg-white border border-dashed border-slate-300 rounded-lg p-10 text-center text-slate-500 text-xs">
            No telemetry records found matching the active filters.
          </div>
        ) : (
          evidenceList.map((item) => {
            const isExpanded = expandedIds[item.id];
            const meta = item.metadata || {};

            const typeBadgeClass =
              item.type === "trace"
                ? "bg-indigo-50 text-indigo-800 border-indigo-200"
                : item.type === "log"
                ? "bg-sky-50 text-sky-800 border-sky-200"
                : item.type === "metric"
                ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                : "bg-slate-100 text-slate-700 border-slate-200";

            const sev = item.severity?.toLowerCase();
            const sevBadgeClass =
              sev === "error" || sev === "critical"
                ? "bg-red-50 text-red-700 border-red-200"
                : sev === "warn" || sev === "warning"
                ? "bg-amber-50 text-amber-700 border-amber-200"
                : "bg-slate-100 text-slate-600 border-slate-200";

            const svcStyle = serviceColorMap[item.service] || {
              bg: "bg-slate-50",
              text: "text-slate-700",
              border: "border-slate-300",
            };

            return (
              <div
                key={item.id}
                className="bg-white border border-slate-200 hover:border-slate-300 rounded-lg p-3 space-y-2 transition-all shadow-2xs"
              >
                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2">
                  <div className="space-y-1 min-w-0 flex-1">
                    <div className="flex items-center space-x-2 flex-wrap gap-y-1">
                      <span className="font-mono text-teal-800 font-bold text-[11px] select-all">
                        {item.id}
                      </span>
                      <span
                        className={`uppercase px-1.5 py-0.5 rounded font-mono font-semibold text-[10px] tracking-wide border ${typeBadgeClass}`}
                      >
                        {item.type}
                      </span>
                      {item.severity && (
                        <span
                          className={`uppercase px-1.5 py-0.5 rounded font-semibold text-[10px] border ${sevBadgeClass}`}
                        >
                          {item.severity}
                        </span>
                      )}
                      <span
                        className={`font-mono text-[10px] px-1.5 py-0.5 rounded border uppercase font-semibold ${svcStyle.bg} ${svcStyle.text} ${svcStyle.border}`}
                      >
                        {item.service}
                      </span>
                      {item.incident_id && (
                        <Link
                          href={`/incidents/${item.incident_id}`}
                          className="text-[10px] font-mono text-purple-700 hover:text-purple-900 bg-purple-50 px-1.5 py-0.5 rounded border border-purple-200"
                        >
                          inc:{item.incident_id.slice(0, 8)}...
                        </Link>
                      )}
                      {item.type === "trace" && meta.duration_ms !== undefined ? (
                        <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 font-mono text-[10px]">
                          {Number(meta.duration_ms).toFixed(1)}ms
                        </span>
                      ) : null}
                    </div>

                    <p className="text-slate-800 leading-relaxed text-xs break-words">
                      {item.message}
                    </p>
                  </div>

                  {/* Actions & Timestamps */}
                  <div className="flex sm:flex-col sm:items-end justify-between items-center text-slate-500 font-mono text-[11px] shrink-0 space-y-1">
                    <span>{new Date(item.timestamp).toISOString()}</span>
                    <div className="flex items-center space-x-2">
                      {item.trace_id && (
                        <>
                          <button
                            onClick={() => {
                              setActiveTraceId(item.trace_id || null);
                              setActiveIncidentId(item.incident_id || "");
                            }}
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

                {/* Expanded Metadata JSON Inspector */}
                {isExpanded && (
                  <div className="pt-2 border-t border-slate-100 space-y-1">
                    <span className="text-slate-400 font-mono text-[10px] block uppercase font-bold">
                      TELEMETRY ATTRIBUTES & PAYLOAD:
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
          })
        )}
      </div>

      {/* Pagination Bar */}
      {totalPages > 1 && (
        <div className="bg-white border border-slate-200 rounded-lg p-3 flex items-center justify-between text-xs text-slate-600">
          <span>
            Page {page + 1} of {totalPages} ({total.toLocaleString()} records)
          </span>
          <div className="flex items-center space-x-2">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-3 py-1 rounded bg-slate-100 hover:bg-slate-200 disabled:opacity-40 border border-slate-300 text-slate-700 font-medium"
            >
              ← Previous
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="px-3 py-1 rounded bg-slate-100 hover:bg-slate-200 disabled:opacity-40 border border-slate-300 text-slate-700 font-medium"
            >
              Next →
            </button>
          </div>
        </div>
      )}

      {/* Trace Waterfall Modal */}
      {activeTraceId && (
        <TraceWaterfall
          traceId={activeTraceId}
          incidentId={activeIncidentId}
          onClose={() => setActiveTraceId(null)}
        />
      )}
    </div>
  );
}
