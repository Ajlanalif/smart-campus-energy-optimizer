import React, { useState } from 'react';
import { SAMPLE_CASES } from '../services/mockData';
import { Play, FileText, Battery, Sun, Zap, Plus, Trash2, Code } from 'lucide-react';

export default function ScenarioSelector({
  currentScenario,
  onSelectScenario,
  onUpdateScenario,
  onRunOptimization,
  isLoading,
}) {
  const [showJsonModal, setShowJsonModal] = useState(false);
  const [jsonText, setJsonText] = useState('');

  const handleCaseChange = (e) => {
    const selectedId = e.target.value;
    const found = SAMPLE_CASES.find((c) => c.input?.scenario_id === selectedId);
    if (found) {
      onSelectScenario(JSON.parse(JSON.stringify(found.input)));
    }
  };

  const handleNoteChange = (index, value) => {
    const updatedNotes = [...(currentScenario.operator_notes || [])];
    updatedNotes[index] = value;
    onUpdateScenario({ ...currentScenario, operator_notes: updatedNotes });
  };

  const handleAddNote = () => {
    const currentNotes = currentScenario.operator_notes || [];
    if (currentNotes.length < 3) {
      onUpdateScenario({
        ...currentScenario,
        operator_notes: [...currentNotes, 'New campus operator directive note...'],
      });
    }
  };

  const handleRemoveNote = (index) => {
    const currentNotes = currentScenario.operator_notes || [];
    if (currentNotes.length > 1) {
      const updatedNotes = currentNotes.filter((_, i) => i !== index);
      onUpdateScenario({ ...currentScenario, operator_notes: updatedNotes });
    }
  };

  const openJsonEditor = () => {
    setJsonText(JSON.stringify(currentScenario, null, 2));
    setShowJsonModal(true);
  };

  const handleApplyJson = () => {
    try {
      const parsed = JSON.parse(jsonText);
      onUpdateScenario(parsed);
      setShowJsonModal(false);
    } catch (err) {
      alert('Invalid JSON: ' + err.message);
    }
  };

  // Compute summary stats of scenario
  const totalDemand = currentScenario.hours?.reduce((acc, h) => acc + h.demand_kwh, 0) || 0;
  const totalSolar = currentScenario.hours?.reduce((acc, h) => acc + h.solar_kwh, 0) || 0;
  const maxTariff = Math.max(...(currentScenario.hours?.map((h) => h.tariff_bdt_per_kwh) || [0]));

  return (
    <div className="card scenario-card">
      <div className="card-header">
        <div className="flex-between">
          <div>
            <h2 className="card-title flex-align">
              <FileText className="icon-accent" size={20} />
              Campus Scenario & Directives
            </h2>
            <p className="card-subtitle">
              Select an official benchmark scenario or test custom natural-language operator directives.
            </p>
          </div>
          <button
            type="button"
            onClick={openJsonEditor}
            className="btn btn-sm btn-outline flex-align"
            title="Inspect / Edit Raw JSON"
          >
            <Code size={14} />
            Raw JSON
          </button>
        </div>
      </div>

      <div className="card-body">
        {/* Preset Selector Dropdown */}
        <div className="form-group">
          <label htmlFor="scenario-select" className="form-label">
            Benchmark Case Presets (10 Official Public Cases):
          </label>
          <select
            id="scenario-select"
            className="select-input"
            value={currentScenario.scenario_id || ''}
            onChange={handleCaseChange}
          >
            {SAMPLE_CASES.map((c) => (
              <option key={c.id} value={c.input.scenario_id}>
                {c.id} — {c.label} ({c.input.operator_notes?.length} note
                {c.input.operator_notes?.length > 1 ? 's' : ''})
              </option>
            ))}
          </select>
        </div>

        {/* Battery & Forecast Snapshot */}
        <div className="grid grid-3 snapshot-grid">
          <div className="snapshot-item">
            <div className="snapshot-icon-wrap battery-wrap">
              <Battery size={18} />
            </div>
            <div>
              <div className="snapshot-label">Battery Storage (BESS)</div>
              <div className="snapshot-value">
                {currentScenario.battery?.capacity_kwh} kWh{' '}
                <span className="text-muted text-sm">
                  ({currentScenario.battery?.initial_energy_kwh} kWh start)
                </span>
              </div>
              <div className="snapshot-subtext">
                Reserve: ≥{currentScenario.battery?.minimum_energy_kwh} kWh · ±
                {currentScenario.battery?.max_charge_kwh_per_hour} kW max
              </div>
            </div>
          </div>

          <div className="snapshot-item">
            <div className="snapshot-icon-wrap demand-wrap">
              <Zap size={18} />
            </div>
            <div>
              <div className="snapshot-label">24-Hour Campus Demand</div>
              <div className="snapshot-value">{totalDemand.toLocaleString()} kWh</div>
              <div className="snapshot-subtext">Peak Tariff: ৳{maxTariff}/kWh</div>
            </div>
          </div>

          <div className="snapshot-item">
            <div className="snapshot-icon-wrap solar-wrap">
              <Sun size={18} />
            </div>
            <div>
              <div className="snapshot-label">Forecast Solar Output</div>
              <div className="snapshot-value">{totalSolar.toLocaleString()} kWh</div>
              <div className="snapshot-subtext">Subject to operator reductions</div>
            </div>
          </div>
        </div>

        {/* Operator Notes Section */}
        <div className="operator-notes-section">
          <div className="flex-between notes-header">
            <label className="form-label" style={{ marginBottom: 0 }}>
              Natural-Language Operator Notes ({currentScenario.operator_notes?.length || 0}/3):
            </label>
            {(currentScenario.operator_notes?.length || 0) < 3 && (
              <button
                type="button"
                onClick={handleAddNote}
                className="btn-text flex-align"
                style={{ fontSize: '0.85rem' }}
              >
                <Plus size={14} /> Add Note
              </button>
            )}
          </div>

          <div className="notes-list">
            {(currentScenario.operator_notes || []).map((note, index) => (
              <div key={index} className="note-input-row">
                <span className="note-index-badge">Note #{index}</span>
                <input
                  type="text"
                  value={note}
                  onChange={(e) => handleNoteChange(index, e.target.value)}
                  placeholder="Enter operator note in plain English..."
                  className="input-text note-input"
                />
                {(currentScenario.operator_notes?.length || 0) > 1 && (
                  <button
                    type="button"
                    onClick={() => handleRemoveNote(index)}
                    className="icon-btn-danger"
                    title="Remove Note"
                  >
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Run Optimization Button */}
        <div className="action-row">
          <button
            type="button"
            className="btn btn-primary btn-lg flex-align btn-glow"
            onClick={onRunOptimization}
            disabled={isLoading}
          >
            <Play size={18} fill="currentColor" />
            {isLoading ? 'Running LLM & Optimizer...' : 'Run Optimization Pipeline'}
          </button>
        </div>
      </div>

      {/* Raw JSON Modal */}
      {showJsonModal && (
        <div className="modal-backdrop">
          <div className="modal-content card">
            <div className="card-header flex-between">
              <h3 className="card-title">Inspect / Edit Raw Scenario JSON</h3>
              <button
                type="button"
                onClick={() => setShowJsonModal(false)}
                className="icon-btn"
              >
                ✕
              </button>
            </div>
            <div className="card-body">
              <textarea
                value={jsonText}
                onChange={(e) => setJsonText(e.target.value)}
                className="json-textarea"
                rows={16}
                spellCheck="false"
              />
            </div>
            <div className="card-footer flex-end gap-2">
              <button
                type="button"
                onClick={() => setShowJsonModal(false)}
                className="btn btn-ghost"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleApplyJson}
                className="btn btn-primary"
              >
                Apply Scenario JSON
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
