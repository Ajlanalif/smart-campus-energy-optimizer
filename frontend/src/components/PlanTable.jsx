import React, { useState } from 'react';
import { Table, Search, Download } from 'lucide-react';

export default function PlanTable({ scenario, hourlyPlan, directiveInterpretation }) {
  const [filterAction, setFilterAction] = useState('all');

  if (!hourlyPlan || hourlyPlan.length !== 24 || !scenario?.hours) {
    return null;
  }

  // Find which hours are affected by active directives
  const affectedHoursSet = new Set();
  if (Array.isArray(directiveInterpretation)) {
    directiveInterpretation.forEach((d) => {
      if (d.applies && d.structured_adjustment?.hours) {
        d.structured_adjustment.hours.forEach((h) => affectedHoursSet.add(h));
      }
    });
  }

  const rows = hourlyPlan.map((p, idx) => {
    const sc = scenario.hours[idx] || {};
    const cost = p.grid_kwh * (sc.tariff_bdt_per_kwh || 0);
    return {
      ...p,
      demand_kwh: sc.demand_kwh || 0,
      solar_available_kwh: sc.solar_kwh || 0,
      tariff: sc.tariff_bdt_per_kwh || 0,
      hourly_cost_bdt: cost,
      hasDirective: affectedHoursSet.has(p.hour),
    };
  });

  const filteredRows = rows.filter((r) => {
    if (filterAction === 'all') return true;
    if (filterAction === 'directive') return r.hasDirective;
    return r.battery_action === filterAction;
  });

  const downloadCsv = () => {
    const headers = [
      'Hour',
      'Tariff_BDT',
      'Demand_kWh',
      'Solar_Avail_kWh',
      'Solar_Used_kWh',
      'Grid_Import_kWh',
      'Battery_Action',
      'Battery_kWh',
      'Battery_Energy_After_kWh',
      'Cost_BDT',
    ];
    const csvContent = [
      headers.join(','),
      ...rows.map((r) =>
        [
          r.hour,
          r.tariff,
          r.demand_kwh,
          r.solar_available_kwh,
          r.solar_used_kwh,
          r.grid_kwh,
          r.battery_action,
          r.battery_kwh,
          r.battery_energy_after_kwh,
          r.hourly_cost_bdt.toFixed(2),
        ].join(',')
      ),
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', `schedule_${scenario.scenario_id || 'gridwise'}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="card table-card">
      <div className="card-header flex-between">
        <div>
          <h3 className="card-title flex-align">
            <Table className="icon-accent" size={18} />
            24-Hour Dispatch Plan (Hour 00:00 to 23:00)
          </h3>
          <p className="card-subtitle">
            Detailed hourly energy balance, battery transitions, and grid expenditure.
          </p>
        </div>

        <div className="flex-align gap-2">
          {/* Action Filter */}
          <div className="table-filter-group">
            <button
              className={`filter-btn ${filterAction === 'all' ? 'active' : ''}`}
              onClick={() => setFilterAction('all')}
            >
              All (24)
            </button>
            <button
              className={`filter-btn ${filterAction === 'charge' ? 'active' : ''}`}
              onClick={() => setFilterAction('charge')}
            >
              Charge
            </button>
            <button
              className={`filter-btn ${filterAction === 'discharge' ? 'active' : ''}`}
              onClick={() => setFilterAction('discharge')}
            >
              Discharge
            </button>
            <button
              className={`filter-btn ${filterAction === 'directive' ? 'active' : ''}`}
              onClick={() => setFilterAction('directive')}
            >
              Directives ({affectedHoursSet.size})
            </button>
          </div>

          <button
            type="button"
            onClick={downloadCsv}
            className="btn btn-sm btn-outline flex-align"
            title="Download Plan as CSV"
          >
            <Download size={14} />
            CSV
          </button>
        </div>
      </div>

      <div className="card-body" style={{ padding: 0 }}>
        <div className="table-responsive">
          <table className="schedule-table">
            <thead>
              <tr>
                <th>Hour</th>
                <th>Tariff</th>
                <th>Demand</th>
                <th>Solar Avail / Used</th>
                <th>Grid Import</th>
                <th>Battery Action</th>
                <th>Battery Flow</th>
                <th>Battery SoC</th>
                <th>Hour Cost</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((row) => (
                <tr
                  key={row.hour}
                  className={`${row.hasDirective ? 'row-directive-active' : ''} ${
                    row.battery_action === 'charge'
                      ? 'row-charge'
                      : row.battery_action === 'discharge'
                      ? 'row-discharge'
                      : ''
                  }`}
                >
                  <td className="font-mono font-bold">
                    {row.hour < 10 ? `0${row.hour}:00` : `${row.hour}:00`}
                    {row.hasDirective && (
                      <span className="directive-tag" title="Affected by operator directive">
                        ★
                      </span>
                    )}
                  </td>
                  <td className="font-mono">৳{row.tariff}</td>
                  <td className="font-mono">{row.demand_kwh} kWh</td>
                  <td className="font-mono">
                    <span className="text-muted">{row.solar_available_kwh}</span> /{' '}
                    <span className="text-warning font-bold">{row.solar_used_kwh}</span>
                  </td>
                  <td className="font-mono font-bold text-primary">{row.grid_kwh} kWh</td>
                  <td>
                    <span
                      className={`action-badge action-${row.battery_action}`}
                    >
                      {row.battery_action.toUpperCase()}
                    </span>
                  </td>
                  <td className="font-mono">
                    {row.battery_action === 'idle' ? '-' : `${row.battery_kwh} kWh`}
                  </td>
                  <td className="font-mono font-bold text-cyan">
                    {row.battery_energy_after_kwh} kWh
                  </td>
                  <td className="font-mono">৳{row.hourly_cost_bdt.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
