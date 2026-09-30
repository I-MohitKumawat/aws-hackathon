"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { ProductItem, OrderResult } from "../lib/types";

export default function StorefrontPage() {
  const [products, setProducts] = useState<ProductItem[]>([]);
  const [cart, setCart] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [latencyMs, setLatencyMs] = useState<number>(0);
  const [orderResult, setOrderResult] = useState<OrderResult | null>(null);
  const [orderError, setOrderError] = useState<string | null>(null);

  useEffect(() => {
    async function loadProducts() {
      try {
        setLoading(true);
        const prods = await api.getProducts();
        setProducts(prods);
      } catch (err: any) {
        console.error("Failed to load products:", err);
      } finally {
        setLoading(false);
      }
    }
    loadProducts();
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

      const res = await api.executeCheckout({
        items: flatItems,
        total: parseFloat(cartTotal.toFixed(2)),
        latency_ms: latencyMs > 0 ? latencyMs : undefined,
      });

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
      {/* Hero Banner */}
      <div className="bg-gradient-to-r from-emerald-950/60 via-slate-900 to-indigo-950/60 border border-slate-800 rounded-2xl p-6 sm:p-8 flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div>
          <div className="flex items-center space-x-2">
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 uppercase tracking-wider">
              Live Microservices Architecture
            </span>
            <span className="text-xs text-slate-400 font-mono">Port 3001</span>
          </div>
          <h1 className="text-3xl font-extrabold text-white mt-2 tracking-tight">
            CloudShop Catalog
          </h1>
          <p className="text-sm text-slate-300 mt-2 max-w-2xl leading-relaxed">
            Every transaction is instrumented with OpenTelemetry. Checkout requests propagate W3C distributed trace context across Checkout (:8080), Inventory (:8081), and Payment (:8082) services to the OpenTelemetry Collector and AI Investigator.
          </p>
        </div>

        <div className="flex flex-col sm:flex-row md:flex-col gap-2 shrink-0">
          <a
            href="http://localhost:3000/telemetry"
            target="_blank"
            rel="noopener noreferrer"
            className="px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-medium transition-all text-center flex items-center justify-center space-x-1.5 shadow-sm"
          >
            <span>Live Telemetry on Port 3000 ↗</span>
          </a>
          <a
            href="/simulate"
            className="px-4 py-2.5 rounded-xl bg-rose-950/50 hover:bg-rose-900/60 text-rose-300 border border-rose-800/80 text-xs font-semibold transition-all text-center flex items-center justify-center space-x-1.5 shadow-sm"
          >
            <span>⚡ Dev: Fault Injection Panel →</span>
          </a>
        </div>
      </div>

      {/* Order Status Feedback */}
      {orderResult && (
        <div className="p-6 rounded-2xl bg-emerald-950/40 border border-emerald-800/80 text-white space-y-4 shadow-xl">
          <div className="flex items-center justify-between border-b border-emerald-800/60 pb-3">
            <div className="flex items-center space-x-3">
              <span className="text-2xl">✅</span>
              <div>
                <h3 className="font-bold text-emerald-300 text-lg">Order Successfully Processed!</h3>
                <p className="text-xs text-emerald-400/80 font-mono">
                  Order ID: {orderResult.order_id} • Status: {orderResult.status}
                </p>
              </div>
            </div>
            <span className="text-xl font-bold font-mono text-emerald-300">
              ${orderResult.total.toFixed(2)}
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
            <div className="bg-slate-900/80 p-3 rounded-lg border border-emerald-900/50">
              <span className="text-slate-400 block">Inventory Reservation:</span>
              <span className="font-mono text-white font-medium">{orderResult.reservation_id || "N/A"}</span>
            </div>
            <div className="bg-slate-900/80 p-3 rounded-lg border border-emerald-900/50">
              <span className="text-slate-400 block">Payment Transaction:</span>
              <span className="font-mono text-white font-medium">{orderResult.payment_id || "N/A"}</span>
            </div>
            <div className="bg-slate-900/80 p-3 rounded-lg border border-emerald-900/50">
              <span className="text-slate-400 block">Coordinated Services:</span>
              <span className="font-mono text-indigo-300">checkout → inventory → payment</span>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
            <p className="text-xs text-slate-300">
              Traces, logs, and metrics were dispatched to OpenTelemetry Collector and stored in PostgreSQL.
            </p>
            <div className="flex items-center space-x-2">
              <a
                href="http://localhost:16686"
                target="_blank"
                rel="noopener noreferrer"
                className="px-3 py-1.5 rounded-lg bg-emerald-900/60 hover:bg-emerald-800/80 text-emerald-200 border border-emerald-700 text-xs font-mono transition-colors"
              >
                Inspect in Jaeger ↗
              </a>
              <a
                href="http://localhost:3000/telemetry"
                target="_blank"
                rel="noopener noreferrer"
                className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors"
              >
                View in Investigator ↗
              </a>
            </div>
          </div>
        </div>
      )}

      {orderError && (
        <div className="p-5 rounded-2xl bg-rose-950/40 border border-rose-800/80 text-rose-200 space-y-2">
          <div className="flex items-center space-x-2">
            <span className="text-lg">❌</span>
            <span className="font-bold text-sm">Checkout Request Failed</span>
          </div>
          <p className="text-xs font-mono bg-rose-950/80 p-3 rounded-lg border border-rose-900/60 break-words">
            {orderError}
          </p>
          <p className="text-xs text-rose-300/80">
            A failure occurred in the checkout pipeline. Check the <a href="http://localhost:3000" target="_blank" rel="noopener noreferrer" className="underline font-semibold">Incident Investigator</a> on port 3000 to see if an incident was auto-detected.
          </p>
        </div>
      )}

      {/* Product Catalog & Cart Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Products Grid (Left 2 Columns) */}
        <div className="lg:col-span-2 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h2 className="text-lg font-bold text-white">Available Products</h2>
            <span className="text-xs text-slate-400 font-mono">
              Live from checkout-service (:8080)
            </span>
          </div>

          {loading ? (
            <div className="p-12 text-center text-slate-500">Loading live catalog...</div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {products.map((item) => (
                <div
                  key={item.sku}
                  className="bg-slate-900/60 border border-slate-800 hover:border-slate-700 transition-all rounded-xl p-5 flex flex-col justify-between space-y-4"
                >
                  <div>
                    <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                      <span className="uppercase tracking-wider font-mono text-[10px] bg-slate-800 px-2 py-0.5 rounded">
                        {item.category}
                      </span>
                      <span className="font-mono">{item.warehouse}</span>
                    </div>
                    <h3 className="font-semibold text-white text-base mt-1">{item.name}</h3>
                    <p className="text-xs text-slate-400 font-mono mt-1">SKU: {item.sku}</p>
                  </div>

                  <div className="flex items-center justify-between pt-3 border-t border-slate-800/80">
                    <div>
                      <span className="text-lg font-bold text-white font-mono">
                        ${item.price.toFixed(2)}
                      </span>
                      <span className="text-[11px] text-slate-400 block">
                        Stock: {item.stock} units
                      </span>
                    </div>
                    <button
                      onClick={() => addToCart(item.sku)}
                      className="px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium transition-colors shadow-sm"
                    >
                      + Add to Cart
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Shopping Cart & Checkout Box (Right 1 Column) */}
        <div className="space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h2 className="text-lg font-bold text-white">Your Cart</h2>
            <span className="text-xs font-mono text-slate-400">
              {totalItemCount} item{totalItemCount === 1 ? "" : "s"}
            </span>
          </div>

          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-5">
            {cartItems.length === 0 ? (
              <div className="py-12 text-center text-slate-500 text-sm">
                Your cart is currently empty.
                <p className="text-xs text-slate-600 mt-1">Add items from the catalog to place a test order.</p>
              </div>
            ) : (
              <div className="space-y-3">
                {cartItems.map((ci) => (
                  <div
                    key={ci.sku}
                    className="flex items-center justify-between text-xs py-2 border-b border-slate-800/60"
                  >
                    <div className="min-w-0 pr-2">
                      <p className="font-medium text-white truncate">{ci.name}</p>
                      <p className="text-slate-400 font-mono">
                        ${ci.price.toFixed(2)} x {ci.qty}
                      </p>
                    </div>
                    <div className="flex items-center space-x-2 shrink-0">
                      <span className="font-mono text-white font-semibold">
                        ${ci.total.toFixed(2)}
                      </span>
                      <button
                        onClick={() => removeFromCart(ci.sku)}
                        className="w-5 h-5 rounded bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white flex items-center justify-center font-bold"
                      >
                        -
                      </button>
                      <button
                        onClick={() => addToCart(ci.sku)}
                        className="w-5 h-5 rounded bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white flex items-center justify-center font-bold"
                      >
                        +
                      </button>
                    </div>
                  </div>
                ))}

                {/* Simulated Latency Injection Slider */}
                <div className="pt-3 border-t border-slate-800 space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-400">Artificial Latency:</span>
                    <span className="font-mono text-slate-200">{latencyMs} ms</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="2000"
                    step="250"
                    value={latencyMs}
                    onChange={(e) => setLatencyMs(Number(e.target.value))}
                    className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-emerald-500"
                  />
                  <div className="flex justify-between text-[10px] text-slate-500 font-mono">
                    <span>0ms (fast)</span>
                    <span>1000ms</span>
                    <span>2000ms</span>
                  </div>
                </div>

                {/* Total & Checkout */}
                <div className="pt-4 border-t border-slate-800 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold text-slate-300">Total:</span>
                    <span className="text-xl font-bold font-mono text-white">
                      ${cartTotal.toFixed(2)}
                    </span>
                  </div>

                  <button
                    onClick={handleCheckout}
                    disabled={submitting || cartItems.length === 0}
                    className="w-full py-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-500 text-white font-semibold text-sm transition-all shadow-lg shadow-emerald-600/20 flex items-center justify-center space-x-2 cursor-pointer disabled:cursor-not-allowed"
                  >
                    {submitting ? (
                      <>
                        <span className="w-2 h-2 rounded-full bg-white animate-ping"></span>
                        <span>Processing Order...</span>
                      </>
                    ) : (
                      <span>Complete Checkout 🚀</span>
                    )}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
