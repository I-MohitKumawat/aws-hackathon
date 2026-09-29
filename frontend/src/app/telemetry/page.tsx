"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "../../lib/api-client";
import { Evidence } from "../../lib/types";
import TraceWaterfall from "../../components/TraceWaterfall";

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
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <div className="flex items-center space-x-2">
            <h2 className="text-2xl font-bold tracking-tight text-white">Live Telemetry Explorer</h2>
            <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-indigo-950 text-indigo-400 border border-indigo-800">
              {total.toLocaleString()} Records
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-1 max-w-2xl">
            Real-time telemetry stream including distributed traces, structured logs, and operational metrics ingested from microservices via OpenTelemetry Collector.
          </p>
        </div>

        {/* Refresh controls */}
        <div className="flex items-center space-x-3 text-xs">
          <label className="flex items-center space-x-2 cursor-pointer bg-slate-900 px-3 py-1.5 rounded-lg border border-slate-800">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded bg-slate-950 border-slate-700 text-indigo-600 focus:ring-0"
            />
            <span className="text-slate-300">Live Auto-Refresh (4s)</span>
          </label>

          <button
            onClick={() => fetchEvidence()}
            className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium transition-colors shadow-sm"
          >
            Refresh ↻
          </button>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-3 text-xs">
        {/* Search */}
        <div className="md:col-span-2 space-y-1">
          <label className="text-slate-400 font-medium block">Search Text</label>
          <input
            type="text"
            placeholder="Search message or attributes..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
            className="w-full bg-slate-950 text-slate-200 border border-slate-700 rounded-lg px-3 py-1.5 outline-none focus:ring-1 focus:ring-indigo-500 text-xs"
          />
        </div>

        {/* Service */}
        <div className="space-y-1">
          <label className="text-slate-400 font-medium block">Service</label>
          <select
            value={service}
            onChange={(e) => {
              setService(e.target.value);
              setPage(0);
            }}
            className="w-full bg-slate-950 text-slate-200 border border-slate-700 rounded-lg px-2.5 py-1.5 outline-none focus:ring-1 focus:ring-indigo-500 text-xs"
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
          <label className="text-slate-400 font-medium block">Telemetry Type</label>
          <select
            value={type}
            onChange={(e) => {
              setType(e.target.value);
              setPage(0);
            }}
            className="w-full bg-slate-950 text-slate-200 border border-slate-700 rounded-lg px-2.5 py-1.5 outline-none focus:ring-1 focus:ring-indigo-500 text-xs"
          >
            <option value="">All Types</option>
            <option value="trace">Traces</option>
            <option value="log">Logs</option>
            <option value="metric">Metrics</option>
          </select>
        </div>

        {/* Severity */}
        <div className="space-y-1">
          <label className="text-slate-400 font-medium block">Severity</label>
          <select
            value={severity}
            onChange={(e) => {
              setSeverity(e.target.value);
              setPage(0);
            }}
            className="w-full bg-slate-950 text-slate-200 border border-slate-700 rounded-lg px-2.5 py-1.5 outline-none focus:ring-1 focus:ring-indigo-500 text-xs"
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
        <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-800 text-rose-300 text-xs">
          {error}
        </div>
      )}

      {/* Telemetry Stream List */}
      <div className="space-y-2.5">
        {loading && evidenceList.length === 0 ? (
          <div className="py-16 text-center text-slate-500 text-sm">Loading telemetry records...</div>
        ) : evidenceList.length === 0 ? (
          <div className="p-12 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded-xl">
            No telemetry records found matching the active filters.
          </div>
        ) : (
          evidenceList.map((item) => {
            const isExpanded = expandedIds[item.id];
            const meta = item.metadata || {};

            const typeBadgeClass =
              item.type === "trace"
                ? "bg-indigo-950/80 text-indigo-300 border-indigo-800/60"
                : item.type === "log"
                ? "bg-cyan-950/80 text-cyan-300 border-cyan-800/60"
                : item.type === "metric"
                ? "bg-emerald-950/80 text-emerald-300 border-emerald-800/60"
                : "bg-slate-800 text-slate-300 border-slate-700";

            const sev = item.severity?.toLowerCase();
            const sevBadgeClass =
              sev === "error" || sev === "critical"
                ? "bg-rose-950/70 text-rose-300 border-rose-800/60"
                : sev === "warn" || sev === "warning"
                ? "bg-amber-950/70 text-amber-300 border-amber-800/60"
                : sev === "info"
                ? "bg-blue-950/70 text-blue-300 border-blue-800/60"
                : "bg-slate-800/80 text-slate-400 border-slate-700/60";

            return (
              <div
                key={item.id}
                className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800/80 hover:border-slate-700 transition-all space-y-2 text-xs"
              >
                <div className="flex flex-col md:flex-row md:items-start justify-between gap-3">
                  <div className="space-y-1.5 flex-1 min-w-0">
                    <div className="flex items-center space-x-2 flex-wrap gap-y-1">
                      <span className="font-mono text-indigo-400 font-semibold">{item.id}</span>
                      <span
                        className={`uppercase px-1.5 py-0.5 rounded font-semibold text-[10px] tracking-wide border ${typeBadgeClass}`}
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
                      <span className="text-slate-300 font-mono bg-slate-950 px-1.5 py-0.5 rounded border border-slate-800">
                        {item.service}
                      </span>
                      {item.incident_id && (
                        <a
                          href={`/incidents/${item.incident_id}`}
                          className="text-[10px] font-mono text-purple-400 hover:text-purple-300 bg-purple-950/40 px-1.5 py-0.5 rounded border border-purple-800/50"
                        >
                          inc:{item.incident_id.slice(0, 8)}...
                        </a>
                      )}
                      {item.type === "trace" && meta.duration_ms !== undefined ? (
                        <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 font-mono text-[10px]">
                          {Number(meta.duration_ms).toFixed(1)}ms
                        </span>
                      ) : null}
                    </div>

                    <p className="text-sm text-slate-200 font-sans break-words">{item.message}</p>
                  </div>

                  {/* Actions & Timestamps */}
                  <div className="flex md:flex-col md:items-end justify-between items-center text-slate-500 font-mono text-[11px] shrink-0 space-y-1">
                    <span>{new Date(item.timestamp).toISOString()}</span>
                    <div className="flex items-center space-x-2">
                      {item.trace_id && (
                        <button
                          onClick={() => {
                            setActiveTraceId(item.trace_id || null);
                            setActiveIncidentId(item.incident_id || "");
                          }}
                          className="px-2 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-800 hover:bg-indigo-900 transition-colors text-[10px]"
                        >
                          Trace Waterfall ⚡
                        </button>
                      )}
                      <button
                        onClick={() => toggleExpand(item.id)}
                        className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[10px]"
                      >
                        {isExpanded ? "Hide JSON ▲" : "Inspect JSON ▼"}
                      </button>
                    </div>
                  </div>
                </div>

                {/* Expanded Metadata JSON Inspector */}
                {isExpanded && (
                  <div className="pt-2 border-t border-slate-800/80 space-y-1">
                    <span className="text-slate-500 font-mono text-[10px] block">
                      TELEMETRY ATTRIBUTES & PAYLOAD:
                    </span>
                    <pre className="p-3 rounded-lg bg-slate-950 border border-slate-800 text-[11px] text-slate-300 overflow-x-auto font-mono max-h-64 leading-relaxed">
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
        <div className="flex items-center justify-between pt-4 border-t border-slate-800 text-xs text-slate-400">
          <span>
            Page {page + 1} of {totalPages} ({total.toLocaleString()} items)
          </span>
          <div className="flex items-center space-x-2">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 disabled:opacity-40 border border-slate-800 text-slate-300 font-medium"
            >
              ← Previous
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 disabled:opacity-40 border border-slate-800 text-slate-300 font-medium"
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
