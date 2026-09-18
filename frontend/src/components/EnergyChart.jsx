import React, { useState } from 'react';
import { BarChart3, Info } from 'lucide-react';

export default function EnergyChart({ scenario, hourlyPlan }) {
  const [hoveredHour, setHoveredHour] = useState(null);

  if (!hourlyPlan || hourlyPlan.length !== 24 || !scenario?.hours) {
    return null;
  }

  // Combine scenario hour data and plan data
  const data = hourlyPlan.map((p, idx) => {
    const sc = scenario.hours[idx] || {};
    return {
      hour: p.hour,
      demand: sc.demand_kwh || 0,
      solarRaw: sc.solar_kwh || 0,
      solarUsed: p.solar_used_kwh || 0,
      grid: p.grid_kwh || 0,
      action: p.battery_action,
      batteryKwh: p.battery_kwh || 0,
      batteryLevel: p.battery_energy_after_kwh || 0,
      tariff: sc.tariff_bdt_per_kwh || 0,
    };
  });

  // Calculate scales
  const maxEnergy = Math.max(
    ...data.map((d) => Math.max(d.demand, d.grid, d.solarUsed + d.grid, d.batteryLevel)),
    100
  );
  const chartHeight = 220;
  const chartWidth = 720;
  const paddingLeft = 45;
  const paddingBottom = 30;
  const paddingTop = 20;
  const usableWidth = chartWidth - paddingLeft - 20;
  const usableHeight = chartHeight - paddingBottom - paddingTop;

  const getX = (hour) => paddingLeft + (hour / 23) * usableWidth;
  const getY = (val) => paddingTop + usableHeight - (val / maxEnergy) * usableHeight;

  // Battery Level Line points
  const batteryPoints = data.map((d) => `${getX(d.hour)},${getY(d.batteryLevel)}`).join(' ');

  // Demand line points
  const demandPoints = data.map((d) => `${getX(d.hour)},${getY(d.demand)}`).join(' ');

  const hoveredData = hoveredHour !== null ? data[hoveredHour] : null;

  return (
    <div className="card chart-card">
      <div className="card-header flex-between">
        <div>
          <h3 className="card-title flex-align">
            <BarChart3 className="icon-accent" size={18} />
            24-Hour Campus Energy Schedule & BESS Dynamic Profile
          </h3>
          <p className="card-subtitle">
            Hover over any hour to inspect the supply-demand balance and battery state-of-charge.
          </p>
        </div>

        {/* Legend */}
        <div className="chart-legend">
          <span className="legend-item">
            <span className="legend-swatch swatch-demand" /> Demand
          </span>
          <span className="legend-item">
            <span className="legend-swatch swatch-grid" /> Grid Import
          </span>
          <span className="legend-item">
            <span className="legend-swatch swatch-solar" /> Solar Used
          </span>
          <span className="legend-item">
            <span className="legend-swatch swatch-battery" /> Battery SoC
          </span>
          <span className="legend-item">
            <span className="legend-swatch swatch-charge" /> Charge
          </span>
          <span className="legend-item">
            <span className="legend-swatch swatch-discharge" /> Discharge
          </span>
        </div>
      </div>

      <div className="card-body">
        <div className="chart-svg-wrapper">
          <svg
            viewBox={`0 0 ${chartWidth} ${chartHeight}`}
            className="energy-chart-svg"
            preserveAspectRatio="xMidYMid meet"
          >
            {/* Grid lines */}
            {[0, 0.25, 0.5, 0.75, 1].map((ratio, idx) => {
              const y = paddingTop + usableHeight * (1 - ratio);
              const val = Math.round(maxEnergy * ratio);
              return (
                <g key={idx}>
                  <line
                    x1={paddingLeft}
                    y1={y}
                    x2={chartWidth - 20}
                    y2={y}
                    stroke="rgba(255,255,255,0.08)"
                    strokeDasharray="3 3"
                  />
                  <text
                    x={paddingLeft - 8}
                    y={y + 4}
                    fill="rgba(255,255,255,0.4)"
                    fontSize="10"
                    textAnchor="end"
                    fontFamily="monospace"
                  >
                    {val}
                  </text>
                </g>
              );
            })}

            {/* X-axis hours labels */}
            {[0, 3, 6, 9, 12, 15, 18, 21, 23].map((h) => {
              const x = getX(h);
              return (
                <text
                  key={h}
                  x={x}
                  y={chartHeight - 8}
                  fill="rgba(255,255,255,0.5)"
                  fontSize="10"
                  textAnchor="middle"
                  fontFamily="monospace"
                >
                  {h < 10 ? `0${h}:00` : `${h}:00`}
                </text>
              );
            })}

            {/* Stacked Bars for Grid + Solar Used */}
            {data.map((d) => {
              const x = getX(d.hour);
              const barWidth = Math.max(usableWidth / 24 - 4, 6);
              const solarHeight = (d.solarUsed / maxEnergy) * usableHeight;
              const gridHeight = (d.grid / maxEnergy) * usableHeight;
              const ySolar = paddingTop + usableHeight - solarHeight;
              const yGrid = ySolar - gridHeight;

              return (
                <g
                  key={d.hour}
                  onMouseEnter={() => setHoveredHour(d.hour)}
                  onMouseLeave={() => setHoveredHour(null)}
                  style={{ cursor: 'pointer' }}
                >
                  {/* Solar bar */}
                  {d.solarUsed > 0 && (
                    <rect
                      x={x - barWidth / 2}
                      y={ySolar}
                      width={barWidth}
                      height={solarHeight}
                      fill="#eab308"
                      opacity={hoveredHour === d.hour ? 0.95 : 0.75}
                      rx={2}
                    />
                  )}
                  {/* Grid bar on top of solar */}
                  {d.grid > 0 && (
                    <rect
                      x={x - barWidth / 2}
                      y={yGrid}
                      width={barWidth}
                      height={gridHeight}
                      fill="#3b82f6"
                      opacity={hoveredHour === d.hour ? 0.95 : 0.75}
                      rx={2}
                    />
                  )}

                  {/* Battery Action Indicator Pip */}
                  {d.action === 'charge' && (
                    <circle
                      cx={x}
                      y={paddingTop + usableHeight + 6}
                      r={3}
                      fill="#10b981"
                      title="Battery Charge"
                    />
                  )}
                  {d.action === 'discharge' && (
                    <circle
                      cx={x}
                      y={paddingTop + usableHeight + 6}
                      r={3}
                      fill="#f97316"
                      title="Battery Discharge"
                    />
                  )}
                </g>
              );
            })}

            {/* Demand line */}
            <polyline
              fill="none"
              stroke="rgba(255, 255, 255, 0.45)"
              strokeWidth="2"
              strokeDasharray="4 4"
              points={demandPoints}
            />

            {/* Battery SoC Curve */}
            <polyline
              fill="none"
              stroke="#06b6d4"
              strokeWidth="2.5"
              points={batteryPoints}
            />

            {/* Markers for Battery Points */}
            {data.map((d) => (
              <circle
                key={`b-${d.hour}`}
                cx={getX(d.hour)}
                cy={getY(d.batteryLevel)}
                r={hoveredHour === d.hour ? 5 : 2.5}
                fill="#06b6d4"
                stroke="#0f172a"
                strokeWidth="1.5"
                onMouseEnter={() => setHoveredHour(d.hour)}
                onMouseLeave={() => setHoveredHour(null)}
              />
            ))}

            {/* Hover vertical line */}
            {hoveredHour !== null && (
              <line
                x1={getX(hoveredHour)}
                y1={paddingTop}
                x2={getX(hoveredHour)}
                y2={paddingTop + usableHeight}
                stroke="rgba(255, 255, 255, 0.6)"
                strokeDasharray="2 2"
                pointerEvents="none"
              />
            )}
          </svg>
        </div>

        {/* Hover Info Tooltip Box */}
        {hoveredData ? (
          <div className="chart-tooltip-panel">
            <div className="tooltip-title font-mono">
              Hour {hoveredData.hour}:00 · Tariff ৳{hoveredData.tariff}/kWh
            </div>
            <div className="tooltip-grid">
              <span className="tooltip-item">
                <span className="text-muted">Demand:</span>{' '}
                <strong>{hoveredData.demand} kWh</strong>
              </span>
              <span className="tooltip-item">
                <span className="text-muted">Grid Import:</span>{' '}
                <strong style={{ color: '#3b82f6' }}>{hoveredData.grid} kWh</strong>
              </span>
              <span className="tooltip-item">
                <span className="text-muted">Solar Used:</span>{' '}
                <strong style={{ color: '#eab308' }}>
                  {hoveredData.solarUsed} / {hoveredData.solarRaw} kWh
                </strong>
              </span>
              <span className="tooltip-item">
                <span className="text-muted">Battery Action:</span>{' '}
                <strong
                  style={{
                    color:
                      hoveredData.action === 'charge'
                        ? '#10b981'
                        : hoveredData.action === 'discharge'
                        ? '#f97316'
                        : '#94a3b8',
                  }}
                >
                  {hoveredData.action.toUpperCase()}{' '}
                  {hoveredData.action !== 'idle' ? `(${hoveredData.batteryKwh} kWh)` : ''}
                </strong>
              </span>
              <span className="tooltip-item">
                <span className="text-muted">Battery SoC:</span>{' '}
                <strong style={{ color: '#06b6d4' }}>{hoveredData.batteryLevel} kWh</strong>
              </span>
            </div>
          </div>
        ) : (
          <div className="chart-hint-row text-muted text-sm flex-align">
            <Info size={14} />
            <span>Click or hover over any hour to see the supply/demand breakdown.</span>
          </div>
        )}
      </div>
    </div>
  );
}
