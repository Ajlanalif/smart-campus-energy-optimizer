import React from 'react';
import { Sun, Battery, AlertTriangle, ShieldCheck, HelpCircle, ArrowRight } from 'lucide-react';

const DIRECTIVE_METADATA = {
  solar_reduction: {
    label: 'Solar Reduction',
    colorClass: 'directive-solar',
    icon: Sun,
    description: 'Reduces usable rooftop solar forecast during window.',
  },
  minimum_battery_reserve: {
    label: 'Minimum Battery Reserve',
    colorClass: 'directive-battery',
    icon: Battery,
    description: 'Enforces minimum state of charge to guard critical reserves.',
  },
  no_charge_window: {
    label: 'No Charge Window',
    colorClass: 'directive-no-charge',
    icon: AlertTriangle,
    description: 'Prohibits battery charging during maintenance or peak window.',
  },
  no_discharge_window: {
    label: 'No Discharge Window',
    colorClass: 'directive-no-discharge',
    icon: AlertTriangle,
    description: 'Prohibits battery discharging during maintenance window.',
  },
  max_grid_window: {
    label: 'Max Grid Import Cap',
    colorClass: 'directive-grid',
    icon: ShieldCheck,
    description: 'Restricts maximum grid electricity purchase in kW.',
  },
  no_op: {
    label: 'No-Op (Distractor / Irrelevant)',
    colorClass: 'directive-noop',
    icon: HelpCircle,
    description: 'Operator note does not affect 24-hour campus energy schedule.',
  },
};

function formatHours(hours) {
  if (!Array.isArray(hours) || hours.length === 0) return 'None';
  const start = hours[0];
  const end = hours[hours.length - 1] + 1; // start-inclusive, end-exclusive
  const formatTime = (h) => {
    const ampm = h >= 12 ? 'PM' : 'AM';
    const hour12 = h % 12 === 0 ? 12 : h % 12;
    return `${hour12}:00 ${ampm}`;
  };
  return `Hours [${hours.join(', ')}] · ${formatTime(start)} – ${formatTime(end)}`;
}

export default function DirectiveCard({ directive, originalNote }) {
  const meta = DIRECTIVE_METADATA[directive.directive_type] || DIRECTIVE_METADATA.no_op;
  const IconComponent = meta.icon;
  const adj = directive.structured_adjustment;

  return (
    <div className={`directive-card ${meta.colorClass} ${directive.applies ? 'is-applied' : 'is-noop'}`}>
      <div className="directive-header">
        <div className="flex-align gap-2">
          <div className="directive-icon-bubble">
            <IconComponent size={18} />
          </div>
          <div>
            <div className="directive-title-row">
              <span className="note-pill">Note #{directive.note_index}</span>
              <span className={`directive-badge ${meta.colorClass}`}>
                {meta.label}
              </span>
              <span className={`applies-pill ${directive.applies ? 'applies-true' : 'applies-false'}`}>
                {directive.applies ? 'APPLIES TO OPTIMIZER' : 'NO-OP / DISTRACTOR'}
              </span>
            </div>
            {originalNote && (
              <p className="original-note-quote">
                &ldquo;{originalNote}&rdquo;
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="directive-body">
        {directive.applies && adj ? (
          <div className="adjustment-grid">
            <div className="adj-item">
              <span className="adj-label">Affected Time Window:</span>
              <span className="adj-value font-mono">{formatHours(adj.hours)}</span>
            </div>

            {adj.factor !== undefined && (
              <div className="adj-item">
                <span className="adj-label">Usable Solar Factor:</span>
                <span className="adj-value font-mono">
                  {adj.factor} ({Math.round(adj.factor * 100)}% usable remaining)
                </span>
              </div>
            )}

            {adj.minimum_energy_kwh !== undefined && (
              <div className="adj-item">
                <span className="adj-label">Required Reserve:</span>
                <span className="adj-value font-mono">≥ {adj.minimum_energy_kwh} kWh</span>
              </div>
            )}

            {adj.max_grid_kwh !== undefined && (
              <div className="adj-item">
                <span className="adj-label">Max Grid Cap:</span>
                <span className="adj-value font-mono">≤ {adj.max_grid_kwh} kWh / hr</span>
              </div>
            )}
          </div>
        ) : (
          <div className="noop-notice">
            <span>Deterministic Guardrail: structured_adjustment is <code>null</code>. This note will not alter optimizer constraints.</span>
          </div>
        )}

        <div className="explanation-box">
          <span className="explanation-label">Model Reasoning:</span>
          <p className="explanation-text">{directive.explanation}</p>
        </div>
      </div>
    </div>
  );
}
