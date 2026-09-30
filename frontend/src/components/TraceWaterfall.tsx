"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api-client";
import { TraceDetailResponse, TraceSpanItem } from "../lib/types";

interface TraceWaterfallProps {
  traceId: string;
  incidentId: string;
  isInline?: boolean;
  onClose?: () => void;
}

const serviceColorPalette: Record<string, { bg: string; text: string; bar: string; border: string }> = {
  checkout: { bg: "bg-teal-50", text: "text-teal-800", bar: "bg-teal-600", border: "border-teal-200" },
  inventory: { bg: "bg-purple-50", text: "text-purple-800", bar: "bg-purple-600", border: "border-purple-200" },
  payment: { bg: "bg-emerald-50", text: "text-emerald-800", bar: "bg-emerald-600", border: "border-emerald-200" },
  backend: { bg: "bg-sky-50", text: "text-sky-800", bar: "bg-sky-600", border: "border-sky-200" },
  default: { bg: "bg-slate-50", text: "text-slate-800", bar: "bg-slate-600", border: "border-slate-200" },
};

export default function TraceWaterfall({ traceId, incidentId, isInline = false, onClose }: TraceWaterfallProps) {
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

  const spans = data?.spans || [];

  // Calculate timing waterfall
  const spanTimes = spans.map((s) => {
    const t = new Date(s.timestamp).getTime();
    const dur = s.duration_ms || (s.metadata?.duration_ms as number) || 5;
    return { span: s, start: t, end: t + dur, dur };
  });

  const minTime = spanTimes.length > 0 ? Math.min(...spanTimes.map((x) => x.start)) : 0;
  const maxTime = spanTimes.length > 0 ? Math.max(...spanTimes.map((x) => Math.max(x.end, x.start + x.dur))) : 100;
  const totalDurationMs = Math.max(maxTime - minTime, 1);

  // Distinct services involved
  const distinctServices = Array.from(new Set(spans.map((s) => s.service)));

  // Generate tick markers for timeline axis
  const tickSteps = 5;
  const ticks = Array.from({ length: tickSteps + 1 }, (_, i) => {
    const pct = (i / tickSteps) * 100;
    const ms = (i / tickSteps) * totalDurationMs;
    return { pct, ms: ms.toFixed(1) };
  });

  const content = (
    <div className={`flex flex-col ${isInline ? "bg-white border border-slate-200 rounded-lg shadow-sm" : "bg-white border border-slate-300 rounded-xl shadow-2xl max-w-6xl w-full max-h-[92vh]"} overflow-hidden text-xs`}>
      {/* Header bar matching Jaeger style */}
      <div className="px-5 py-3.5 border-b border-slate-200 bg-slate-50 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center space-x-2 flex-wrap gap-y-1">
            <span className="font-bold text-slate-900 text-sm">
              Trace: {spans[0]?.span_name || spans[0]?.message || traceId.slice(0, 16)}
            </span>
            <span className="px-2 py-0.5 rounded bg-teal-50 text-teal-800 border border-teal-200 font-mono font-semibold text-[11px]">
              {spans.length} Spans
            </span>
          </div>

          {/* Jaeger Metadata Summary Bar */}
          <div className="flex items-center space-x-3 text-[11px] text-slate-500 font-mono flex-wrap gap-y-1">
            <span>Trace Start: <strong className="text-slate-700">{spans[0] ? new Date(spans[0].timestamp).toLocaleTimeString() : "N/A"}</strong></span>
            <span>•</span>
            <span>Duration: <strong className="text-slate-700">{totalDurationMs.toFixed(1)}ms</strong></span>
            <span>•</span>
            <span>Services: <strong className="text-slate-700">{distinctServices.length} ({distinctServices.join(", ")})</strong></span>
            <span>•</span>
            <span>Trace ID: <strong className="text-slate-700 select-all">{traceId}</strong></span>
          </div>
        </div>

        <div className="flex items-center space-x-3 shrink-0">
          <a
            href={`http://localhost:16686/trace/${traceId}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center space-x-1 px-3 py-1.5 rounded bg-white hover:bg-slate-50 border border-slate-300 text-teal-700 hover:text-teal-800 font-medium transition-colors text-xs shadow-sm"
          >
            <span>Open in Jaeger UI</span>
            <span>↗</span>
          </a>
          {onClose && (
            <button
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-slate-700 rounded hover:bg-slate-200 transition-colors"
              title="Close trace waterfall"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <div className="py-16 text-center text-slate-500 space-y-2">
          <div className="w-5 h-5 border-2 border-teal-600 border-t-transparent rounded-full animate-spin mx-auto"></div>
          <p>Loading trace spans...</p>
        </div>
      ) : error ? (
        <div className="p-4 bg-red-50 border-b border-red-200 text-red-700 text-xs">
          {error}
        </div>
      ) : spans.length === 0 ? (
        <div className="py-12 text-center text-slate-500">
          No spans recorded for this trace ID yet.
        </div>
      ) : (
        <div className="flex flex-col lg:flex-row overflow-hidden flex-1 min-h-[360px]">
          {/* Left / Center: Waterfall Tree + Timeline Bars */}
          <div className="flex-1 overflow-y-auto p-4 space-y-2 border-b lg:border-b-0 lg:border-r border-slate-200">
            {/* Timeline Axis Ticks */}
            <div className="relative h-6 border-b border-slate-200 select-none text-[10px] text-slate-400 font-mono">
              {ticks.map((t, idx) => (
                <div
                  key={idx}
                  className="absolute transform -translate-x-1/2 flex flex-col items-center"
                  style={{ left: `${t.pct}%` }}
                >
                  <span>{t.ms}ms</span>
                  <div className="w-px h-1.5 bg-slate-300 mt-0.5"></div>
                </div>
              ))}
            </div>

            {/* Span Rows */}
            <div className="space-y-1.5 pt-1">
              {spanTimes.map(({ span, start, dur }, idx) => {
                const sColor = serviceColorPalette[span.service] || serviceColorPalette.default;
                const isSelected = selectedSpan?.evidence_id === span.evidence_id;
                const offsetMs = Math.max(0, start - minTime);
                const leftPct = Math.min(99, Math.max(0, (offsetMs / totalDurationMs) * 100));
                const widthPct = Math.min(100 - leftPct, Math.max(1.5, (dur / totalDurationMs) * 100));
                const isError =
                  span.severity === "error" ||
                  (span.metadata?.status_code as string) === "ERROR" ||
                  Boolean(span.metadata?.exception_message);

                return (
                  <div
                    key={span.evidence_id || idx}
                    onClick={() => setSelectedSpan(span)}
                    className={`p-2 rounded border cursor-pointer transition-all ${
                      isSelected
                        ? "bg-teal-50/60 border-teal-500 shadow-xs"
                        : "bg-slate-50/50 border-slate-200 hover:bg-slate-100/70"
                    }`}
                  >
                    {/* Span Header */}
                    <div className="flex items-center justify-between gap-2 mb-1.5 text-xs">
                      <div className="flex items-center space-x-2 min-w-0">
                        <span
                          className={`px-1.5 py-0.5 rounded font-mono font-semibold text-[10px] border uppercase shrink-0 ${sColor.bg} ${sColor.text} ${sColor.border}`}
                        >
                          {span.service}
                        </span>
                        <span className="font-mono text-slate-800 font-medium truncate">
                          {span.span_name || span.message}
                        </span>
                      </div>
                      <div className="flex items-center space-x-2 font-mono text-[11px] shrink-0">
                        {isError && (
                          <span className="px-1.5 py-0.2 rounded bg-red-100 text-red-800 border border-red-200 text-[10px] uppercase font-bold">
                            Error
                          </span>
                        )}
                        <span className="text-slate-600 font-semibold">{dur.toFixed(1)}ms</span>
                      </div>
                    </div>

                    {/* Timeline Bar Track */}
                    <div className="h-3 w-full bg-slate-200/70 rounded relative overflow-hidden">
                      <div
                        className={`absolute top-0 bottom-0 rounded transition-all flex items-center justify-end px-1 ${
                          isError ? "bg-red-500" : sColor.bar
                        }`}
                        style={{
                          left: `${leftPct}%`,
                          width: `${widthPct}%`,
                        }}
                      >
                        {widthPct > 15 && (
                          <span className="text-[9px] text-white font-mono font-bold">
                            {dur.toFixed(1)}ms
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Right Pane: Span Details Inspector */}
          <div className="w-full lg:w-84 p-4 bg-slate-50/60 overflow-y-auto space-y-3 shrink-0">
            <h4 className="font-bold text-slate-800 uppercase tracking-wider text-[11px] border-b border-slate-200 pb-1.5">
              Span Attributes & Details
            </h4>
            {selectedSpan ? (
              <div className="space-y-2.5 font-mono text-xs">
                <div>
                  <span className="text-slate-400 block text-[10px] uppercase font-sans font-semibold">Service</span>
                  <span className="text-slate-800 font-semibold">{selectedSpan.service}</span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[10px] uppercase font-sans font-semibold">Operation</span>
                  <span className="text-teal-700 font-semibold break-words">
                    {selectedSpan.span_name || selectedSpan.message}
                  </span>
                </div>
                {selectedSpan.span_id && (
                  <div>
                    <span className="text-slate-400 block text-[10px] uppercase font-sans font-semibold">Span ID</span>
                    <span className="text-slate-700 select-all">{selectedSpan.span_id}</span>
                  </div>
                )}
                {selectedSpan.parent_span_id && (
                  <div>
                    <span className="text-slate-400 block text-[10px] uppercase font-sans font-semibold">Parent Span ID</span>
                    <span className="text-slate-700 select-all">{selectedSpan.parent_span_id}</span>
                  </div>
                )}
                <div>
                  <span className="text-slate-400 block text-[10px] uppercase font-sans font-semibold">Duration</span>
                  <span className="text-slate-800 font-semibold">{selectedSpan.duration_ms?.toFixed(2) ?? "N/A"} ms</span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[10px] uppercase font-sans font-semibold">Start Timestamp</span>
                  <span className="text-slate-600 text-[11px]">
                    {new Date(selectedSpan.timestamp).toISOString()}
                  </span>
                </div>

                {selectedSpan.metadata && Object.keys(selectedSpan.metadata).length > 0 && (
                  <div>
                    <span className="text-slate-400 block text-[10px] uppercase font-sans font-semibold mb-1">
                      Attributes / Tags
                    </span>
                    <pre className="p-2.5 rounded bg-white border border-slate-200 text-[10px] overflow-x-auto text-slate-800 max-h-56 leading-relaxed select-all">
                      {JSON.stringify(selectedSpan.metadata, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-slate-500 text-xs">Select a span from the waterfall to inspect its attributes.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );

  if (isInline) {
    return content;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 sm:p-6 overflow-y-auto">
      {content}
    </div>
  );
}
