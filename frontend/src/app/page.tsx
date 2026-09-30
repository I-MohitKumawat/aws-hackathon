"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { api } from "../lib/api-client";
import { Incident } from "../lib/types";

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

const statusColorMap: Record<string, { bg: string; text: string; border: string }> = {
  open: { bg: "bg-amber-50", text: "text-amber-800", border: "border-amber-300" },
  investigating: { bg: "bg-indigo-50", text: "text-indigo-800", border: "border-indigo-300" },
  resolved: { bg: "bg-emerald-50", text: "text-emerald-800", border: "border-emerald-300" },
  ignored: { bg: "bg-slate-100", text: "text-slate-600", border: "border-slate-300" },
};

export default function DashboardPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filter state
  const [selectedService, setSelectedService] = useState<string>("");
  const [selectedSeverity, setSelectedSeverity] = useState<string>("");
  const [selectedStatus, setSelectedStatus] = useState<string>("");
  const [selectedSource, setSelectedSource] = useState<string>("");
  const [limit, setLimit] = useState<number>(50);
  const [searchTerm, setSearchTerm] = useState<string>("");
  const [autoRefresh, setAutoRefresh] = useState<boolean>(false);

  const fetchIncidents = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const params: any = { limit };
      if (selectedService) params.service = selectedService;
      if (selectedSeverity) params.severity = selectedSeverity;
      if (selectedStatus) params.status = selectedStatus;
      if (selectedSource) params.source = selectedSource;

      const res = await api.getIncidents(params);
      setIncidents(res.items);
      setTotalCount(res.total);
    } catch (err: any) {
      setError(err.message || "Failed to load incidents from backend");
    } finally {
      setLoading(false);
    }
  }, [selectedService, selectedSeverity, selectedStatus, selectedSource, limit]);

  useEffect(() => {
    fetchIncidents();
  }, [fetchIncidents]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      fetchIncidents();
    }, 5000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchIncidents]);

  const handleResetFilters = () => {
    setSelectedService("");
    setSelectedSeverity("");
    setSelectedStatus("");
    setSelectedSource("");
    setSearchTerm("");
    setLimit(50);
  };

  // Filter by local search term if typed
  const displayedIncidents = incidents.filter((inc) => {
    if (!searchTerm.trim()) return true;
    const q = searchTerm.toLowerCase();
    return (
      inc.title.toLowerCase().includes(q) ||
      inc.service.toLowerCase().includes(q) ||
      inc.id.toLowerCase().includes(q) ||
      (inc.detection_reason && inc.detection_reason.toLowerCase().includes(q)) ||
      (inc.detection_rule && inc.detection_rule.toLowerCase().includes(q)) ||
      (inc.description && inc.description.toLowerCase().includes(q))
    );
  });

  const activeFiltersCount =
    (selectedService ? 1 : 0) +
    (selectedSeverity ? 1 : 0) +
    (selectedStatus ? 1 : 0) +
    (selectedSource ? 1 : 0) +
    (searchTerm.trim() ? 1 : 0);

  return (
    <div className="flex flex-col lg:flex-row gap-5 items-start">
      {/* Left Sidebar: Jaeger-Style Search & Filters */}
      <aside className="w-full lg:w-72 shrink-0 bg-white border border-slate-200 rounded-lg p-4 shadow-sm space-y-4">
        <div className="flex items-center justify-between border-b border-slate-100 pb-2">
          <h2 className="text-xs font-bold uppercase tracking-wider text-slate-700">
            Search Incidents
          </h2>
          {activeFiltersCount > 0 && (
            <button
              onClick={handleResetFilters}
              className="text-[11px] text-teal-700 hover:text-teal-900 underline font-medium"
            >
              Reset All
            </button>
          )}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            fetchIncidents();
          }}
          className="space-y-3.5 text-xs"
        >
          {/* Service */}
          <div>
            <label className="block text-[11px] font-semibold text-slate-600 mb-1">
              Service
            </label>
            <select
              value={selectedService}
              onChange={(e) => setSelectedService(e.target.value)}
              className="w-full bg-slate-50 border border-slate-300 rounded px-2.5 py-1.5 text-slate-800 text-xs focus:bg-white focus:border-teal-600 focus:outline-none transition-colors"
            >
              <option value="">All Services</option>
              <option value="checkout">checkout</option>
              <option value="inventory">inventory</option>
              <option value="payment">payment</option>
              <option value="backend">backend</option>
            </select>
          </div>

          {/* Severity */}
          <div>
            <label className="block text-[11px] font-semibold text-slate-600 mb-1">
              Severity
            </label>
            <select
              value={selectedSeverity}
              onChange={(e) => setSelectedSeverity(e.target.value)}
              className="w-full bg-slate-50 border border-slate-300 rounded px-2.5 py-1.5 text-slate-800 text-xs focus:bg-white focus:border-teal-600 focus:outline-none transition-colors"
            >
              <option value="">All Severities</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>

          {/* Status */}
          <div>
            <label className="block text-[11px] font-semibold text-slate-600 mb-1">
              Status
            </label>
            <select
              value={selectedStatus}
              onChange={(e) => setSelectedStatus(e.target.value)}
              className="w-full bg-slate-50 border border-slate-300 rounded px-2.5 py-1.5 text-slate-800 text-xs focus:bg-white focus:border-teal-600 focus:outline-none transition-colors"
            >
              <option value="">All Statuses</option>
              <option value="open">Open</option>
              <option value="investigating">Investigating</option>
              <option value="resolved">Resolved</option>
            </select>
          </div>

          {/* Source */}
          <div>
            <label className="block text-[11px] font-semibold text-slate-600 mb-1">
              Source
            </label>
            <select
              value={selectedSource}
              onChange={(e) => setSelectedSource(e.target.value)}
              className="w-full bg-slate-50 border border-slate-300 rounded px-2.5 py-1.5 text-slate-800 text-xs focus:bg-white focus:border-teal-600 focus:outline-none transition-colors"
            >
              <option value="">All Sources</option>
              <option value="auto_detected">⚡ Auto-Detected</option>
              <option value="manual">Manual</option>
            </select>
          </div>

          {/* Search Keywords */}
          <div>
            <label className="block text-[11px] font-semibold text-slate-600 mb-1">
              Search Keywords
            </label>
            <input
              type="text"
              placeholder="e.g. timeout, connection, spike"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full bg-slate-50 border border-slate-300 rounded px-2.5 py-1.5 text-slate-800 text-xs focus:bg-white focus:border-teal-600 focus:outline-none transition-colors"
            />
          </div>

          {/* Limit */}
          <div>
            <label className="block text-[11px] font-semibold text-slate-600 mb-1">
              Limit Results
            </label>
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="w-full bg-slate-50 border border-slate-300 rounded px-2.5 py-1.5 text-slate-800 text-xs focus:bg-white focus:border-teal-600 focus:outline-none transition-colors"
            >
              <option value={10}>10</option>
              <option value={20}>20</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </div>

          {/* Find Button */}
          <button
            type="submit"
            className="w-full mt-2 py-2 px-4 rounded bg-teal-600 hover:bg-teal-700 active:bg-teal-800 text-white font-medium text-xs tracking-wide shadow-sm transition-colors cursor-pointer"
          >
            Find Incidents
          </button>
        </form>
      </aside>

      {/* Right Main Content */}
      <section className="flex-1 min-w-0 w-full space-y-3">
        {/* Results Header Bar */}
        <div className="bg-white border border-slate-200 rounded-lg p-3 shadow-sm flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
          <div className="flex items-center space-x-2 flex-wrap gap-y-1">
            <span className="font-bold text-slate-900 text-sm">
              {displayedIncidents.length} Incident{displayedIncidents.length === 1 ? "" : "s"}
            </span>
            {totalCount > displayedIncidents.length && (
              <span className="text-slate-500 font-mono text-[11px]">
                (of {totalCount} total)
              </span>
            )}

            {/* Active filter badges */}
            {selectedService && (
              <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-300 text-[11px]">
                <span>service: {selectedService}</span>
                <button onClick={() => setSelectedService("")} className="hover:text-slate-900 ml-1">✕</button>
              </span>
            )}
            {selectedSeverity && (
              <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-300 text-[11px]">
                <span>severity: {selectedSeverity}</span>
                <button onClick={() => setSelectedSeverity("")} className="hover:text-slate-900 ml-1">✕</button>
              </span>
            )}
            {selectedStatus && (
              <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-300 text-[11px]">
                <span>status: {selectedStatus}</span>
                <button onClick={() => setSelectedStatus("")} className="hover:text-slate-900 ml-1">✕</button>
              </span>
            )}
            {selectedSource && (
              <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-300 text-[11px]">
                <span>source: {selectedSource}</span>
                <button onClick={() => setSelectedSource("")} className="hover:text-slate-900 ml-1">✕</button>
              </span>
            )}
          </div>

          {/* Controls */}
          <div className="flex items-center space-x-3 text-xs shrink-0">
            <label className="flex items-center space-x-1.5 cursor-pointer text-slate-600 hover:text-slate-900 select-none">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="rounded border-slate-300 text-teal-600 focus:ring-0 cursor-pointer"
              />
              <span className="text-[11px]">Auto-refresh (5s)</span>
            </label>

            <button
              onClick={() => fetchIncidents()}
              className="px-2.5 py-1 rounded bg-slate-100 hover:bg-slate-200 border border-slate-300 text-slate-700 font-medium text-xs transition-colors flex items-center space-x-1 cursor-pointer"
            >
              <span>↻</span>
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="p-3.5 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs flex items-center justify-between">
            <span>{error}</span>
            <button
              onClick={() => fetchIncidents()}
              className="text-red-800 underline font-semibold ml-2 hover:text-red-950"
            >
              Retry
            </button>
          </div>
        )}

        {/* Results List */}
        {loading && incidents.length === 0 ? (
          <div className="py-16 text-center text-slate-500 bg-white border border-slate-200 rounded-lg text-xs space-y-2">
            <div className="w-5 h-5 border-2 border-teal-600 border-t-transparent rounded-full animate-spin mx-auto"></div>
            <p>Loading incidents from backend...</p>
          </div>
        ) : displayedIncidents.length === 0 ? (
          <div className="py-16 text-center text-slate-500 bg-white border border-dashed border-slate-300 rounded-lg text-xs space-y-2">
            <p className="font-semibold text-slate-700">No incidents found matching current filters.</p>
            <p className="text-slate-400">Try adjusting your filters or search keywords.</p>
          </div>
        ) : (
          <div className="space-y-2.5">
            {displayedIncidents.map((incident) => {
              const svcStyle = serviceColorMap[incident.service] || {
                bg: "bg-slate-50",
                text: "text-slate-700",
                border: "border-slate-300",
              };
              const sevStyle = severityColorMap[incident.severity] || {
                bg: "bg-slate-50",
                text: "text-slate-700",
                border: "border-slate-300",
              };
              const statStyle = statusColorMap[incident.status] || {
                bg: "bg-slate-50",
                text: "text-slate-700",
                border: "border-slate-300",
              };

              return (
                <div
                  key={incident.id}
                  className="bg-white border border-slate-200 hover:border-slate-300 hover:shadow-sm rounded-lg p-3.5 space-y-2 transition-all"
                >
                  {/* Top Metadata Row */}
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <div className="flex items-center space-x-2 flex-wrap gap-y-1">
                      {/* Service Badge */}
                      <span
                        className={`px-2 py-0.5 rounded font-mono font-semibold text-[11px] border uppercase ${svcStyle.bg} ${svcStyle.text} ${svcStyle.border}`}
                      >
                        {incident.service}
                      </span>

                      {/* Severity Pill */}
                      <span
                        className={`px-2 py-0.5 rounded font-semibold text-[11px] border uppercase ${sevStyle.bg} ${sevStyle.text} ${sevStyle.border}`}
                      >
                        {incident.severity}
                      </span>

                      {/* Status Badge */}
                      <span
                        className={`px-2 py-0.5 rounded font-semibold text-[11px] border uppercase ${statStyle.bg} ${statStyle.text} ${statStyle.border}`}
                      >
                        {incident.status}
                      </span>

                      {/* Source */}
                      {incident.source === "auto_detected" ? (
                        <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-purple-50 text-purple-700 border border-purple-200 flex items-center space-x-1">
                          <span>⚡</span>
                          <span>Auto-Detected</span>
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 text-slate-600 border border-slate-200">
                          Manual
                        </span>
                      )}

                      {/* Detection Rule Tag */}
                      {incident.detection_rule && (
                        <span className="px-1.5 py-0.5 rounded text-[11px] font-mono bg-slate-50 text-slate-600 border border-slate-200">
                          rule:{incident.detection_rule}
                        </span>
                      )}
                    </div>

                    {/* Timestamp */}
                    <div className="text-[11px] font-mono text-slate-500">
                      {new Date(incident.started_at).toLocaleString()}
                    </div>
                  </div>

                  {/* Title & Reason Row */}
                  <div className="space-y-1">
                    <div className="flex items-baseline space-x-2">
                      <span className="text-[11px] font-mono text-slate-400 select-all shrink-0">
                        #{incident.id.slice(0, 8)}
                      </span>
                      <Link
                        href={`/incidents/${incident.id}`}
                        className="text-sm font-semibold text-slate-900 hover:text-teal-700 transition-colors"
                      >
                        {incident.title}
                      </Link>
                    </div>

                    {incident.description && (
                      <p className="text-xs text-slate-600 line-clamp-2">
                        {incident.description}
                      </p>
                    )}

                    {incident.detection_reason && (
                      <div className="text-[11px] bg-slate-50 border border-slate-200 rounded px-2.5 py-1 text-slate-700 font-mono">
                        <strong className="text-slate-900 font-semibold font-sans">Trigger:</strong>{" "}
                        {incident.detection_reason}
                      </div>
                    )}
                  </div>

                  {/* Bottom Footer / Action */}
                  <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
                    <div className="flex items-center space-x-3 text-[11px] font-mono">
                      <span>ID: {incident.id}</span>
                      {incident.ended_at && (
                        <>
                          <span>•</span>
                          <span className="text-emerald-700">
                            Resolved: {new Date(incident.ended_at).toLocaleTimeString()}
                          </span>
                        </>
                      )}
                    </div>

                    <Link
                      href={`/incidents/${incident.id}`}
                      className="inline-flex items-center space-x-1 text-xs font-semibold text-teal-700 hover:text-teal-800 bg-teal-50 hover:bg-teal-100 px-3 py-1 rounded border border-teal-200 transition-colors"
                    >
                      <span>Inspect Incident</span>
                      <span>→</span>
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
