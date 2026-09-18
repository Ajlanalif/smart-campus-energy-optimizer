import React, { useState, useEffect, useMemo } from 'react';
import Header from './components/Header';
import ScenarioSelector from './components/ScenarioSelector';
import DirectiveCard from './components/DirectiveCard';
import MetricsSummary from './components/MetricsSummary';
import EnergyChart from './components/EnergyChart';
import PlanTable from './components/PlanTable';
import ComplianceBadge from './components/ComplianceBadge';
import LoadingState from './components/LoadingState';
import { SAMPLE_CASES } from './services/mockData';
import { checkBackendHealth, optimizeEnergy } from './services/api';
import { validateSchedule } from './utils/validator';
import { LayoutDashboard, Table, FileCode, CheckSquare, AlertCircle } from 'lucide-react';

export default function App() {
  // Initialize with Sample Case 1
  const initialCase = SAMPLE_CASES[0];
  const [currentScenario, setCurrentScenario] = useState(initialCase.input);
  const [result, setResult] = useState(initialCase.expected_output);
  const [resultSource, setResultSource] = useState('mock');
  const [latencyMs, setLatencyMs] = useState(480);

  const [useMock, setUseMock] = useState(false);
  const [baseUrl, setBaseUrl] = useState('http://localhost:8000');
  const [backendStatus, setBackendStatus] = useState({ online: false, checking: true });
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [activeTab, setActiveTab] = useState('overview');

  // Check health on load
  const runHealthCheck = async (url = baseUrl) => {
    setBackendStatus((prev) => ({ ...prev, checking: true }));
    const res = await checkBackendHealth(url);
    setBackendStatus(res);
    // If backend is offline, default to mock mode so the app works out of the box
    if (!res.online) {
      setUseMock(true);
    }
  };

  useEffect(() => {
    runHealthCheck();
  }, [baseUrl]);

  // Compute live validation whenever scenario or result changes
  const validation = useMemo(() => {
    if (!currentScenario || !result) return null;
    return validateSchedule(currentScenario, result);
  }, [currentScenario, result]);

  // Run Optimization pipeline
  const handleRunOptimization = async () => {
    setIsLoading(true);
    setErrorMessage('');
    try {
      const response = await optimizeEnergy(currentScenario, {
        baseUrl,
        useMock,
      });

      if (!response.success) {
        setErrorMessage(response.error || 'Optimization request failed.');
        setIsLoading(false);
        return;
      }

      setResult(response.data);
      setResultSource(response.source);
      setLatencyMs(response.latencyMs);
    } catch (err) {
      setErrorMessage(`Unexpected error: ${err.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  // When selecting a preset scenario
  const handleSelectScenario = (newScenario) => {
    setCurrentScenario(newScenario);
    setErrorMessage('');
    // Auto-load matching expected output if in mock mode
    const matched = SAMPLE_CASES.find((c) => c.input?.scenario_id === newScenario.scenario_id);
    if (matched && matched.expected_output) {
      setResult(matched.expected_output);
      setResultSource('mock');
      setLatencyMs(420);
    }
  };

  return (
    <div className="app-layout">
      {/* Top Header */}
      <Header
        backendStatus={backendStatus}
        useMock={useMock}
        setUseMock={setUseMock}
        baseUrl={baseUrl}
        setBaseUrl={setBaseUrl}
        onRefreshHealth={runHealthCheck}
        latencyMs={latencyMs}
      />

      {/* Main Content Area */}
      <main className="container main-container">
        {/* Error Alert if any */}
        {errorMessage && (
          <div className="alert-error flex-between">
            <div className="flex-align gap-2">
              <AlertCircle size={20} />
              <div>
                <strong>Optimization Request Failed:</strong>
                <p style={{ margin: 0, fontSize: '0.9rem' }}>{errorMessage}</p>
              </div>
            </div>
            <button
              onClick={() => setErrorMessage('')}
              className="btn btn-sm btn-ghost"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Top Section: Scenario Selector & Editor */}
        <ScenarioSelector
          currentScenario={currentScenario}
          onSelectScenario={handleSelectScenario}
          onUpdateScenario={setCurrentScenario}
          onRunOptimization={handleRunOptimization}
          isLoading={isLoading}
        />

        {/* Loading Card */}
        {isLoading && <LoadingState source={useMock ? 'mock' : 'live'} />}

        {/* Results Section */}
        {!isLoading && result && (
          <div className="results-wrapper">
            {/* Top KPI Metrics Cards */}
            <MetricsSummary
              result={result}
              source={resultSource}
              latencyMs={latencyMs}
            />

            {/* Compliance Badge */}
            <ComplianceBadge validation={validation} />

            {/* Navigation Tabs */}
            <div className="tab-bar">
              <button
                className={`tab-btn ${activeTab === 'overview' ? 'active' : ''}`}
                onClick={() => setActiveTab('overview')}
              >
                <LayoutDashboard size={16} /> Overview & Visual Schedule
              </button>
              <button
                className={`tab-btn ${activeTab === 'directives' ? 'active' : ''}`}
                onClick={() => setActiveTab('directives')}
              >
                <FileCode size={16} /> Directive Interpretations (
                {result.directive_interpretation?.length || 0})
              </button>
              <button
                className={`tab-btn ${activeTab === 'table' ? 'active' : ''}`}
                onClick={() => setActiveTab('table')}
              >
                <Table size={16} /> 24-Hour Dispatch Table
              </button>
            </div>

            {/* Tab 1: Overview */}
            {activeTab === 'overview' && (
              <div className="tab-pane">
                <EnergyChart
                  scenario={currentScenario}
                  hourlyPlan={result.hourly_plan}
                />

                {/* Compact Directives Preview */}
                <div className="section-title-row">
                  <h3 className="section-title">Interpreted Operator Directives</h3>
                  <span className="text-muted text-sm">
                    {result.directive_interpretation?.length} note
                    {result.directive_interpretation?.length > 1 ? 's' : ''} parsed by model
                  </span>
                </div>
                <div className="directives-list">
                  {(result.directive_interpretation || []).map((dir, idx) => (
                    <DirectiveCard
                      key={idx}
                      directive={dir}
                      originalNote={currentScenario.operator_notes?.[dir.note_index]}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Tab 2: Directives Deep Dive */}
            {activeTab === 'directives' && (
              <div className="tab-pane">
                <div className="directives-list">
                  {(result.directive_interpretation || []).map((dir, idx) => (
                    <DirectiveCard
                      key={idx}
                      directive={dir}
                      originalNote={currentScenario.operator_notes?.[dir.note_index]}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Tab 3: Detailed Table */}
            {activeTab === 'table' && (
              <div className="tab-pane">
                <PlanTable
                  scenario={currentScenario}
                  hourlyPlan={result.hourly_plan}
                  directiveInterpretation={result.directive_interpretation}
                />
              </div>
            )}
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="site-footer">
        <div className="container footer-inner flex-between">
          <span className="text-muted text-sm">
            GridWise — BUP CSE Fest 2026 Hackathon Preliminary Round · Member 2 Presentation UI
          </span>
          <span className="text-muted text-sm font-mono">
            API Endpoints: <code>GET /health</code> · <code>POST /optimize-energy</code>
          </span>
        </div>
      </footer>
    </div>
  );
}
