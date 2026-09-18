import React, { useState } from 'react';
import { ShieldCheck, AlertCircle, ChevronDown, ChevronUp, Check, X } from 'lucide-react';

export default function ComplianceBadge({ validation }) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!validation) return null;

  const { isValid, checks, errors, recalculated } = validation;

  const checkItems = [
    {
      key: 'energyBalance',
      label: 'Hourly Energy Balance',
      desc: 'Grid + Solar + Discharge == Demand + Charge (±0.01 kWh)',
      pass: checks.energyBalance,
    },
    {
      key: 'solarBounds',
      label: 'Effective Solar Usage Limits',
      desc: 'solar_used <= effective_solar (factored solar reduction applied)',
      pass: checks.solarBounds,
    },
    {
      key: 'batteryRateLimits',
      label: 'Battery Charge/Discharge Rate Limits',
      desc: 'Hourly flow respects max_charge & max_discharge kW limits',
      pass: checks.batteryRateLimits,
    },
    {
      key: 'batteryTransitions',
      label: 'Battery State-of-Charge Continuity',
      desc: 'E_after = E_before + Charge - Discharge',
      pass: checks.batteryTransitions,
    },
    {
      key: 'batteryBounds',
      label: 'Battery Capacity & Reserve Bounds',
      desc: 'E_after stays between directive minimum reserve and capacity',
      pass: checks.batteryBounds,
    },
    {
      key: 'endOfDayNeutrality',
      label: 'End-of-Day Neutrality (Hour 23)',
      desc: 'final battery_energy_after_kwh equals initial_energy_kwh',
      pass: checks.endOfDayNeutrality,
    },
    {
      key: 'directivesFollowed',
      label: 'Operator Directives Adherence',
      desc: 'no_charge, no_discharge, and max_grid caps satisfied in target hours',
      pass: checks.directivesFollowed,
    },
    {
      key: 'totalsMatch',
      label: 'Recalculation Totals Match',
      desc: 'total_grid_kwh, total_cost_bdt, and peak_grid_kwh match schedule replay',
      pass: checks.totalsMatch,
    },
  ];

  const passedCount = checkItems.filter((i) => i.pass).length;

  return (
    <div className={`compliance-panel ${isValid ? 'compliance-pass' : 'compliance-fail'}`}>
      <div className="compliance-summary-row flex-between" onClick={() => setIsExpanded(!isExpanded)}>
        <div className="flex-align gap-2">
          {isValid ? (
            <div className="compliance-icon-bubble pass">
              <ShieldCheck size={22} />
            </div>
          ) : (
            <div className="compliance-icon-bubble fail">
              <AlertCircle size={22} />
            </div>
          )}
          <div>
            <div className="flex-align gap-2">
              <h4 className="compliance-title">
                {isValid ? 'Canonical GridWise Compliance Verified' : 'Compliance Violations Detected'}
              </h4>
              <span className={`compliance-count-pill ${isValid ? 'pass' : 'fail'}`}>
                {passedCount} / {checkItems.length} Checks Passed
              </span>
            </div>
            <p className="compliance-subtext">
              Deterministic replay of 24-hour physical laws, battery conservation, and directive constraints.
            </p>
          </div>
        </div>

        <button
          type="button"
          className="btn-text flex-align"
          aria-label="Toggle compliance checklist"
        >
          {isExpanded ? (
            <>
              Hide Details <ChevronUp size={16} />
            </>
          ) : (
            <>
              Inspect Checklist <ChevronDown size={16} />
            </>
          )}
        </button>
      </div>

      {isExpanded && (
        <div className="compliance-expanded-body">
          <div className="grid grid-2 check-items-grid">
            {checkItems.map((item) => (
              <div
                key={item.key}
                className={`check-item-card ${item.pass ? 'item-pass' : 'item-fail'}`}
              >
                <div className="check-status-icon">
                  {item.pass ? <Check size={16} /> : <X size={16} />}
                </div>
                <div>
                  <div className="check-label">{item.label}</div>
                  <div className="check-desc">{item.desc}</div>
                </div>
              </div>
            ))}
          </div>

          {errors && errors.length > 0 && (
            <div className="compliance-error-box">
              <span className="font-bold">Violation Details:</span>
              <ul className="compliance-error-list">
                {errors.map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            </div>
          )}

          {recalculated && (
            <div className="recalculated-box flex-between text-sm font-mono">
              <span>Recalculated Grid: <strong>{recalculated.total_grid_kwh} kWh</strong></span>
              <span>Recalculated Cost: <strong>৳{recalculated.total_cost_bdt}</strong></span>
              <span>Peak Grid: <strong>{recalculated.peak_grid_kwh} kWh</strong></span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
