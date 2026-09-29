"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api-client";
import { TraceDetailResponse, TraceSpanItem } from "../lib/types";

interface TraceWaterfallProps {
  traceId: string;
  incidentId: string;
  onClose?: () => void;
}

const serviceColors: Record<string, { bg: string; text: string; bar: string }> = {
  checkout: { bg: "bg-indigo-950/60 border-indigo-800/60", text: "text-indigo-400", bar: "bg-indigo-500" },
  inventory: { bg: "bg-purple-950/60 border-purple-800/60", text: "text-purple-400", bar: "bg-purple-500" },
  payment: { bg: "bg-emerald-950/60 border-emerald-800/60", text: "text-emerald-400", bar: "bg-emerald-500" },
  backend: { bg: "bg-cyan-950/60 border-cyan-800/60", text: "text-cyan-400", bar: "bg-cyan-500" },
};

export default function TraceWaterfall({ traceId, incidentId, onClose }: TraceWaterfallProps) {
  const [data, setData] = useState<TraceDetailResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSpan, setSelectedSpan] = useState<TraceSpanItem | null>(null);

  useEffect(() => {
    async function loadTrace() {
      try {
        setLoading(true);
        setError(null);
        const res = await api.getTraceSpans(incidentId, traceId);
        setData(res);
        if (res.spans.length > 0) {
          setSelectedSpan(res.spans[0]);
        }
      } catch (err: any) {
        setError(err.message || "Failed to load trace spans");
      } finally {
        setLoading(false);
      }
    }
    loadTrace();
  }, [traceId, incidentId]);

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
        <div className="p-8 rounded-xl bg-slate-900 border border-slate-800 text-center space-y-3">
          <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto"></div>
          <p className="text-sm text-slate-300">Loading trace spans for {traceId.slice(0, 16)}...</p>
        </div>
      </div>
    );
  }

  const spans = data?.spans || [];

  // Calculate timing waterfall
  const spanTimes = spans.map((s) => {
    const t = new Date(s.timestamp).getTime();
    const dur = s.duration_ms || (s.metadata?.duration_ms as number) || 5;
    return { span: s, start: t, end: t + dur, dur };
  });

  const minTime = spanTimes.length > 0 ? Math.min(...spanTimes.map((x) => x.start)) : 0;
  const maxTime = spanTimes.length > 0 ? Math.max(...spanTimes.map((x) => Math.max(x.end, x.start + x.dur))) : 100;
  const totalDurationMs = Math.max(maxTime - minTime, 10);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4 sm:p-6 overflow-y-auto">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-5xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/60">
          <div className="space-y-1">
            <div className="flex items-center space-x-2">
              <span className="text-base font-bold text-white">Distributed Trace Waterfall</span>
              <span className="text-xs px-2 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-800 font-mono">
                {spans.length} Spans
              </span>
              <span className="text-xs text-slate-400 font-mono">
                Total: {totalDurationMs.toFixed(1)}ms
              </span>
            </div>
            <div className="flex items-center space-x-3 text-xs text-slate-400 font-mono">
              <span>Trace ID: {traceId}</span>
              <a
                href={`http://localhost:16686/trace/${traceId}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-indigo-400 hover:text-indigo-300 underline flex items-center space-x-1"
              >
                <span>Open in Jaeger UI ↗</span>
              </a>
            </div>
          </div>
          {onClose && (
            <button
              onClick={onClose}
              className="p-2 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition-colors"
            >
              ✕
            </button>
          )}
        </div>

        {error ? (
          <div className="p-6 text-sm text-red-400 bg-red-950/20">{error}</div>
        ) : spans.length === 0 ? (
          <div className="p-12 text-center text-slate-500 text-sm">
            No spans recorded for this trace ID yet.
          </div>
        ) : (
          <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
            {/* Waterfall Gantt View */}
            <div className="flex-1 p-6 overflow-y-auto border-b md:border-b-0 md:border-r border-slate-800 space-y-3">
              {/* Timeline Header axis */}
              <div className="flex items-center justify-between text-[11px] text-slate-500 font-mono border-b border-slate-800 pb-1.5 px-2">
                <span>Service / Operation</span>
                <span>Timeline (0ms - {totalDurationMs.toFixed(0)}ms)</span>
              </div>

              {/* Span Rows */}
              <div className="space-y-2">
                {spanTimes.map(({ span, start, dur }, idx) => {
                  const sColors = serviceColors[span.service] || {
                    bg: "bg-slate-800 text-slate-300",
                    text: "text-slate-300",
                    bar: "bg-slate-500",
                  };
                  const isSelected = selectedSpan?.evidence_id === span.evidence_id;
                  const offsetMs = Math.max(0, start - minTime);
                  const leftPct = Math.min(100, Math.max(0, (offsetMs / totalDurationMs) * 100));
                  const widthPct = Math.min(100 - leftPct, Math.max(2, (dur / totalDurationMs) * 100));
                  const isError =
                    span.severity === "error" ||
                    (span.metadata?.status_code as string) === "ERROR" ||
                    Boolean(span.metadata?.exception_message);

                  return (
                    <div
                      key={span.evidence_id || idx}
                      onClick={() => setSelectedSpan(span)}
                      className={`p-2.5 rounded-lg border cursor-pointer transition-all ${
                        isSelected
                          ? "bg-slate-800/90 border-indigo-500 ring-1 ring-indigo-500/30"
                          : "bg-slate-950/40 border-slate-800/80 hover:border-slate-700"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1.5 text-xs">
                        <div className="flex items-center space-x-2">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-semibold border uppercase ${sColors.bg} ${sColors.text}`}
                          >
                            {span.service}
                          </span>
                          <span className="font-mono text-slate-200 font-medium">
                            {span.span_name || span.message}
                          </span>
                        </div>
                        <div className="flex items-center space-x-2 font-mono text-[11px]">
                          {isError && (
                            <span className="px-1.5 py-0.2 rounded bg-rose-950 text-rose-300 border border-rose-800 text-[10px] uppercase font-bold">
                              Error
                            </span>
                          )}
                          <span className="text-slate-400">{dur.toFixed(1)}ms</span>
                        </div>
                      </div>

                      {/* Visual Bar Container */}
                      <div className="h-2 w-full bg-slate-800/60 rounded-full relative overflow-hidden">
                        <div
                          className={`absolute top-0 bottom-0 rounded-full transition-all ${
                            isError ? "bg-rose-500" : sColors.bar
                          }`}
                          style={{
                            left: `${leftPct}%`,
                            width: `${widthPct}%`,
                          }}
                        ></div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Span Inspector Panel */}
            <div className="w-full md:w-80 p-5 bg-slate-950/40 overflow-y-auto space-y-4 text-xs">
              <h4 className="font-semibold text-slate-200 uppercase tracking-wider text-[11px]">
                Span Details
              </h4>
              {selectedSpan ? (
                <div className="space-y-3 font-mono">
                  <div>
                    <span className="text-slate-500 block text-[10px]">SERVICE</span>
                    <span className="text-slate-200">{selectedSpan.service}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block text-[10px]">OPERATION</span>
                    <span className="text-indigo-300 break-words">
                      {selectedSpan.span_name || selectedSpan.message}
                    </span>
                  </div>
                  {selectedSpan.span_id && (
                    <div>
                      <span className="text-slate-500 block text-[10px]">SPAN ID</span>
                      <span className="text-slate-300">{selectedSpan.span_id}</span>
                    </div>
                  )}
                  {selectedSpan.parent_span_id && (
                    <div>
                      <span className="text-slate-500 block text-[10px]">PARENT SPAN ID</span>
                      <span className="text-slate-300">{selectedSpan.parent_span_id}</span>
                    </div>
                  )}
                  <div>
                    <span className="text-slate-500 block text-[10px]">DURATION</span>
                    <span className="text-slate-200">{selectedSpan.duration_ms?.toFixed(1) ?? "N/A"} ms</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block text-[10px]">TIMESTAMP</span>
                    <span className="text-slate-400 text-[10px]">
                      {new Date(selectedSpan.timestamp).toISOString()}
                    </span>
                  </div>

                  {selectedSpan.metadata && Object.keys(selectedSpan.metadata).length > 0 && (
                    <div>
                      <span className="text-slate-500 block text-[10px] mb-1">METADATA / ATTRIBUTES</span>
                      <pre className="p-2 rounded bg-slate-900 border border-slate-800 text-[10px] overflow-x-auto text-slate-300 max-h-48 leading-relaxed">
                        {JSON.stringify(selectedSpan.metadata, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-slate-500">Select a span row to inspect telemetry attributes.</p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
