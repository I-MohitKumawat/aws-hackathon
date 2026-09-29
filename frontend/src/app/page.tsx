"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api-client";
import { Incident } from "../lib/types";

const severityColors: Record<string, string> = {
  critical: "bg-red-500/10 text-red-400 border-red-500/20",
  high: "bg-orange-500/10 text-orange-400 border-orange-500/20",
  medium: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
  low: "bg-blue-500/10 text-blue-400 border-blue-500/20",
};

const statusColors: Record<string, string> = {
  open: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  investigating: "bg-indigo-500/10 text-indigo-400 border-indigo-500/20",
  resolved: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  ignored: "bg-slate-500/10 text-slate-400 border-slate-500/20",
};

export default function DashboardPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchIncidents() {
      try {
        setLoading(true);
        setError(null);
        const res = await api.getIncidents(statusFilter ? { status: statusFilter } : undefined);
        setIncidents(res.items);
      } catch (err: any) {
        setError(err.message || "Failed to load incidents");
      } finally {
        setLoading(false);
      }
    }
    fetchIncidents();
  }, [statusFilter]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-white">Active Incidents</h2>
          <p className="text-sm text-slate-400 mt-1">
            Real-time telemetry correlation and automated AI root cause investigation.
          </p>
        </div>
        <div className="flex items-center space-x-2">
          {["", "open", "investigating", "resolved"].map((status) => (
            <button
              key={status}
              onClick={() => setStatusFilter(status)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                statusFilter === status
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "bg-slate-900 text-slate-400 hover:text-white border border-slate-800"
              }`}
            >
              {status ? status.charAt(0).toUpperCase() + status.slice(1) : "All"}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-lg bg-red-950/40 border border-red-800 text-red-300 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="py-12 flex justify-center items-center text-slate-500 text-sm">
          Loading incidents...
        </div>
      ) : incidents.length === 0 ? (
        <div className="py-12 text-center text-slate-500 text-sm border border-dashed border-slate-800 rounded-xl">
          No incidents found for the selected filter.
        </div>
      ) : (
        <div className="grid gap-4">
          {incidents.map((incident) => (
            <div
              key={incident.id}
              className="p-5 rounded-xl bg-slate-900/60 border border-slate-800 hover:border-slate-700 transition-all flex flex-col md:flex-row md:items-center justify-between gap-4"
            >
              <div className="space-y-1.5">
                <div className="flex items-center space-x-2">
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wider border ${
                      severityColors[incident.severity] || "text-slate-400"
                    }`}
                  >
                    {incident.severity}
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-medium border ${
                      statusColors[incident.status] || "text-slate-400"
                    }`}
                  >
                    {incident.status}
                  </span>
                  <span className="text-xs font-mono text-indigo-400 bg-indigo-950/50 px-2 py-0.5 rounded">
                    svc:{incident.service}
                  </span>
                </div>
                <h3 className="text-base font-semibold text-white">{incident.title}</h3>
                {incident.description && (
                  <p className="text-sm text-slate-400 line-clamp-1">{incident.description}</p>
                )}
                <div className="text-xs text-slate-500 flex items-center space-x-3 pt-1">
                  <span>ID: {incident.id}</span>
                  <span>•</span>
                  <span>Started: {new Date(incident.started_at).toLocaleString()}</span>
                </div>
              </div>

              <div className="flex items-center space-x-2 self-start md:self-center">
                <a
                  href={`/incidents/${incident.id}`}
                  className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-all shadow-sm"
                >
                  View Details & Investigate
                </a>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
