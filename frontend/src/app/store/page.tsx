"use client";

import { useEffect, useState } from "react";
import { api } from "../../lib/api-client";
import { ProductItem, OrderResult, Incident } from "../../lib/types";
import TraceWaterfall from "../../components/TraceWaterfall";

export default function StorePage() {
  const [products, setProducts] = useState<ProductItem[]>([]);
  const [cart, setCart] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [latencyMs, setLatencyMs] = useState<number>(0);
  const [orderResult, setOrderResult] = useState<OrderResult | null>(null);
  const [orderError, setOrderError] = useState<string | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selectedIncidentId, setSelectedIncidentId] = useState<string>("");
  const [activeTraceId, setActiveTraceId] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      try {
        setLoading(true);
        const [prods, incs] = await Promise.all([
          api.getProducts(),
          api.getIncidents({ limit: 10, status: "open" }).catch(() => ({ items: [] })),
        ]);
        setProducts(prods);
        setIncidents(incs.items);
      } catch (err: any) {
        console.error("Failed to load store data:", err);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  const addToCart = (sku: string) => {
    setCart((prev) => ({ ...prev, [sku]: (prev[sku] || 0) + 1 }));
  };

  const removeFromCart = (sku: string) => {
    setCart((prev) => {
      const next = { ...prev };
      if (next[sku] > 1) {
        next[sku] -= 1;
      } else {
        delete next[sku];
      }
      return next;
    });
  };

  const cartItems = Object.entries(cart).map(([sku, qty]) => {
    const item = products.find((p) => p.sku === sku);
    return {
      sku,
      name: item?.name || sku,
      price: item?.price || 0,
      qty,
      total: (item?.price || 0) * qty,
    };
  });

  const cartTotal = cartItems.reduce((acc, item) => acc + item.total, 0);
  const totalItemCount = cartItems.reduce((acc, item) => acc + item.qty, 0);

  const handleCheckout = async () => {
    if (cartItems.length === 0) return;
    try {
      setSubmitting(true);
      setOrderError(null);
      setOrderResult(null);

      const flatItems: string[] = [];
      cartItems.forEach((ci) => {
        for (let i = 0; i < ci.qty; i++) flatItems.push(ci.sku);
      });

      const res = await api.executeCheckout(
        {
          items: flatItems,
          total: parseFloat(cartTotal.toFixed(2)),
          latency_ms: latencyMs > 0 ? latencyMs : undefined,
        },
        selectedIncidentId || undefined
      );

      setOrderResult(res);
      setCart({});
    } catch (err: any) {
      setOrderError(err.message || "Checkout request failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-8">
      {/* Store Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <div className="flex items-center space-x-2">
            <h2 className="text-2xl font-bold tracking-tight text-white">Cloud Hardware Store</h2>
            <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-indigo-950 text-indigo-400 border border-indigo-800">
              Live Microservices
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-1 max-w-2xl">
            Real distributed transactions spanning <strong>Checkout (8080)</strong>, <strong>Inventory (8081)</strong>, and <strong>Payment (8082)</strong>. All actions emit OpenTelemetry traces, structured logs, and metrics.
          </p>
        </div>

        {/* Incident Context Selector */}
        <div className="flex items-center space-x-2 bg-slate-900 p-2 rounded-xl border border-slate-800 text-xs">
          <span className="text-slate-400">Tag Incident:</span>
          <select
            value={selectedIncidentId}
            onChange={(e) => setSelectedIncidentId(e.target.value)}
            className="bg-slate-950 text-slate-200 border border-slate-700 rounded-lg px-2.5 py-1 text-xs focus:ring-1 focus:ring-indigo-500 outline-none"
          >
            <option value="">None (Auto-Correlation)</option>
            {incidents.map((inc) => (
              <option key={inc.id} value={inc.id}>
                {inc.title.slice(0, 30)}... ({inc.id.slice(0, 8)})
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Product Catalog */}
        <div className="lg:col-span-2 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
              Available Hardware ({products.length})
            </h3>
            <span className="text-xs text-slate-500 font-mono">Stock verified from Inventory API</span>
          </div>

          {loading ? (
            <div className="py-12 text-center text-slate-500">Loading catalog from Inventory Service...</div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {products.map((p) => {
                const countInCart = cart[p.sku] || 0;
                return (
                  <div
                    key={p.sku}
                    className="p-5 rounded-xl bg-slate-900/60 border border-slate-800 hover:border-slate-700 transition-all flex flex-col justify-between space-y-4"
                  >
                    <div>
                      <div className="flex items-start justify-between">
                        <span className="text-xs font-mono text-indigo-400">{p.category}</span>
                        <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400 font-mono">
                          {p.warehouse}
                        </span>
                      </div>
                      <h4 className="text-base font-semibold text-white mt-1">{p.name}</h4>
                      <div className="flex items-center space-x-2 mt-2">
                        <span className="text-lg font-bold text-white">${p.price.toFixed(2)}</span>
                        <span className="text-xs text-emerald-400">({p.stock} in stock)</span>
                      </div>
                    </div>

                    <div className="pt-2 flex items-center justify-between border-t border-slate-800/80">
                      <span className="text-xs text-slate-500 font-mono">{p.sku}</span>
                      <button
                        onClick={() => addToCart(p.sku)}
                        className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-all shadow-sm flex items-center space-x-1"
                      >
                        <span>Add to Cart</span>
                        {countInCart > 0 && (
                          <span className="w-4 h-4 rounded-full bg-indigo-950 text-indigo-200 text-[10px] flex items-center justify-center font-bold">
                            {countInCart}
                          </span>
                        )}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Cart & Checkout Panel */}
        <div className="space-y-6">
          <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl space-y-5">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white flex items-center space-x-2">
                <span>🛒 Shopping Cart</span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-950 text-indigo-300 font-mono">
                  {totalItemCount}
                </span>
              </h3>
              {cartItems.length > 0 && (
                <button
                  onClick={() => setCart({})}
                  className="text-xs text-slate-400 hover:text-rose-400 transition-colors"
                >
                  Clear Cart
                </button>
              )}
            </div>

            {cartItems.length === 0 ? (
              <div className="py-10 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded-xl">
                Cart is empty. Add products from the catalog to execute a distributed checkout.
              </div>
            ) : (
              <div className="space-y-3">
                {cartItems.map((item) => (
                  <div
                    key={item.sku}
                    className="flex items-center justify-between text-xs py-1 border-b border-slate-800/60"
                  >
                    <div className="flex-1 min-w-0 pr-2">
                      <p className="text-slate-200 font-medium truncate">{item.name}</p>
                      <p className="text-slate-500 font-mono">${item.price.toFixed(2)} each</p>
                    </div>
                    <div className="flex items-center space-x-2 shrink-0">
                      <div className="flex items-center space-x-1 bg-slate-950 px-1 py-0.5 rounded border border-slate-800 font-mono">
                        <button
                          onClick={() => removeFromCart(item.sku)}
                          className="px-1 text-slate-400 hover:text-white"
                        >
                          -
                        </button>
                        <span className="px-1 text-slate-200">{item.qty}</span>
                        <button
                          onClick={() => addToCart(item.sku)}
                          className="px-1 text-slate-400 hover:text-white"
                        >
                          +
                        </button>
                      </div>
                      <span className="font-mono text-slate-300 w-16 text-right">
                        ${item.total.toFixed(2)}
                      </span>
                    </div>
                  </div>
                ))}

                {/* Subtotal */}
                <div className="pt-2 flex items-center justify-between text-sm font-semibold border-t border-slate-800">
                  <span className="text-slate-300">Total</span>
                  <span className="text-white font-mono text-base">${cartTotal.toFixed(2)}</span>
                </div>
              </div>
            )}

            {/* Artificial Latency Control */}
            <div className="pt-3 border-t border-slate-800/80 space-y-1.5 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Artificial Latency Delay:</span>
                <span className="font-mono text-indigo-400">{latencyMs} ms</span>
              </div>
              <input
                type="range"
                min="0"
                max="5000"
                step="250"
                value={latencyMs}
                onChange={(e) => setLatencyMs(Number(e.target.value))}
                className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-indigo-500"
              />
              <p className="text-[10px] text-slate-500">
                Adds delay across downstream services to test latency metrics and span waterfalls.
              </p>
            </div>

            {/* Place Order Button */}
            <button
              onClick={handleCheckout}
              disabled={cartItems.length === 0 || submitting}
              className="w-full py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600 text-white font-semibold text-sm transition-all shadow-lg shadow-indigo-600/20 flex items-center justify-center space-x-2"
            >
              {submitting ? (
                <>
                  <span className="w-2 h-2 rounded-full bg-white animate-ping"></span>
                  <span>Executing Distributed Checkout...</span>
                </>
              ) : (
                <span>Complete Order (${cartTotal.toFixed(2)})</span>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Order Result Modal */}
      {orderResult && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-lg shadow-2xl p-6 space-y-5">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center space-x-2">
                <span className="w-3 h-3 rounded-full bg-emerald-400"></span>
                <h3 className="text-lg font-bold text-white">Order Confirmed!</h3>
              </div>
              <button
                onClick={() => setOrderResult(null)}
                className="text-slate-400 hover:text-white p-1"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3 font-mono text-xs bg-slate-950/60 p-4 rounded-xl border border-slate-800">
              <div className="flex justify-between">
                <span className="text-slate-400">ORDER ID:</span>
                <span className="text-white font-bold">{orderResult.order_id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">STATUS:</span>
                <span className="text-emerald-400 uppercase font-semibold">{orderResult.status}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">TOTAL:</span>
                <span className="text-white">${orderResult.total.toFixed(2)}</span>
              </div>
              {orderResult.reservation_id && (
                <div className="flex justify-between">
                  <span className="text-slate-400">RESERVATION:</span>
                  <span className="text-purple-300">{orderResult.reservation_id}</span>
                </div>
              )}
              {orderResult.payment_id && (
                <div className="flex justify-between">
                  <span className="text-slate-400">PAYMENT:</span>
                  <span className="text-indigo-300">{orderResult.payment_id}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-slate-400">SERVICES INVOLVED:</span>
                <span className="text-slate-300">Checkout → Inventory → Payment</span>
              </div>
            </div>

            <div className="flex flex-col sm:flex-row gap-2 pt-2">
              <a
                href="/telemetry"
                className="flex-1 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold text-center transition-all shadow-sm"
              >
                Inspect Telemetry Explorer →
              </a>
              <button
                onClick={() => setOrderResult(null)}
                className="px-4 py-2.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Order Error Notification */}
      {orderError && (
        <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-800 text-rose-300 text-xs space-y-1">
          <div className="font-semibold text-sm flex items-center space-x-1.5">
            <span>⚠ Checkout Failure</span>
          </div>
          <p>{orderError}</p>
        </div>
      )}

      {/* Trace Waterfall Modal if active */}
      {activeTraceId && (
        <TraceWaterfall
          traceId={activeTraceId}
          incidentId={selectedIncidentId || ""}
          onClose={() => setActiveTraceId(null)}
        />
      )}
    </div>
  );
}
