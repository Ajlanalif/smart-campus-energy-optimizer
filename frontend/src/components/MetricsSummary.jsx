import React from 'react';
import { DollarSign, Zap, TrendingDown, FileText, CheckCircle } from 'lucide-react';

export default function MetricsSummary({ result, source, latencyMs }) {
  if (!result) return null;

  const { total_cost_bdt, total_grid_kwh, peak_grid_kwh, plan_summary } = result;

  return (
    <div className="metrics-container">
      <div className="grid grid-4 metrics-grid">
        {/* Total Cost Card */}
        <div className="metric-card metric-cost">
          <div className="metric-icon-wrap">
            <DollarSign size={20} />
          </div>
          <div className="metric-content">
            <span className="metric-title">Total Grid Electricity Cost</span>
            <div className="metric-value font-mono">
              ৳ {Number(total_cost_bdt || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
            <span className="metric-hint">Objective: Minimized BDT</span>
          </div>
        </div>

        {/* Total Grid Energy */}
        <div className="metric-card metric-grid">
          <div className="metric-icon-wrap">
            <Zap size={20} />
          </div>
          <div className="metric-content">
            <span className="metric-title">Total Grid Energy Import</span>
            <div className="metric-value font-mono">
              {Number(total_grid_kwh || 0).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 2 })} <span className="metric-unit">kWh</span>
            </div>
            <span className="metric-hint">24-Hour Cumulative</span>
          </div>
        </div>

        {/* Peak Grid Import */}
        <div className="metric-card metric-peak">
          <div className="metric-icon-wrap">
            <TrendingDown size={20} />
          </div>
          <div className="metric-content">
            <span className="metric-title">Peak Grid Import</span>
            <div className="metric-value font-mono">
              {Number(peak_grid_kwh || 0).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 2 })} <span className="metric-unit">kWh</span>
            </div>
            <span className="metric-hint">Max Single-Hour Demand</span>
          </div>
        </div>

        {/* Execution Details */}
        <div className="metric-card metric-meta">
          <div className="metric-icon-wrap">
            <CheckCircle size={20} />
          </div>
          <div className="metric-content">
            <span className="metric-title">Pipeline Response</span>
            <div className="metric-value">
              {source === 'live' ? 'Live API' : 'Benchmark Ref'}
            </div>
            <span className="metric-hint">
              Latency: {latencyMs}ms {latencyMs <= 5000 ? '(Fast p95)' : '(> 5s)'}
            </span>
          </div>
        </div>
      </div>

      {/* Plan Summary Callout */}
      {plan_summary && (
        <div className="plan-summary-banner">
          <div className="summary-header">
            <FileText size={16} className="text-accent" />
            <span className="summary-title">Optimization Strategy Summary:</span>
          </div>
          <p className="summary-text">{plan_summary}</p>
        </div>
      )}
    </div>
  );
}
