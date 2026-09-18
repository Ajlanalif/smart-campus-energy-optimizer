import React, { useState } from 'react';
import { Zap, Activity, ShieldCheck, Settings, RefreshCw } from 'lucide-react';

export default function Header({
  backendStatus,
  useMock,
  setUseMock,
  baseUrl,
  setBaseUrl,
  onRefreshHealth,
  latencyMs,
}) {
  const [showSettings, setShowSettings] = useState(false);
  const [tempUrl, setTempUrl] = useState(baseUrl);

  const handleSaveSettings = (e) => {
    e.preventDefault();
    setBaseUrl(tempUrl);
    setShowSettings(false);
    onRefreshHealth(tempUrl);
  };

  return (
    <header className="site-header">
      <div className="header-inner container">
        <div className="header-brand">
          <div className="brand-icon-wrapper">
            <Zap className="brand-icon" size={24} />
          </div>
          <div>
            <div className="brand-title-row">
              <h1 className="brand-title">GridWise</h1>
              <span className="badge badge-primary">Smart Campus Energy Optimizer</span>
              <span className="badge badge-event">BUP CSE FEST 2026</span>
            </div>
            <p className="brand-subtitle">
              LLM-Assisted Operator Directive Interpretation & 24-Hour Schedule Optimization
            </p>
          </div>
        </div>

        <div className="header-actions">
          {/* Backend Status Pill */}
          <div className="status-pill">
            <span
              className={`status-dot ${
                useMock ? 'status-mock' : backendStatus.online ? 'status-online' : 'status-offline'
              }`}
            />
            <div className="status-text-block">
              <span className="status-label">
                {useMock ? 'Mock Demo Mode' : backendStatus.online ? 'Backend Online' : 'Backend Offline'}
              </span>
              <span className="status-subtext">
                {useMock
                  ? 'Built-in Reference Data'
                  : backendStatus.online
                  ? `${latencyMs ? `${latencyMs}ms` : 'Healthy'} · :8000`
                  : 'Check Connection'}
              </span>
            </div>
            <button
              onClick={() => onRefreshHealth()}
              title="Refresh Health"
              className="icon-btn"
              aria-label="Refresh status"
            >
              <RefreshCw size={14} />
            </button>
          </div>

          {/* Mode Switcher */}
          <div className="mode-toggle-group">
            <button
              type="button"
              className={`mode-btn ${!useMock ? 'active' : ''}`}
              onClick={() => setUseMock(false)}
            >
              Live API
            </button>
            <button
              type="button"
              className={`mode-btn ${useMock ? 'active' : ''}`}
              onClick={() => setUseMock(true)}
            >
              Mock Fallback
            </button>
          </div>

          {/* Settings button */}
          <button
            onClick={() => setShowSettings(!showSettings)}
            className="icon-btn-large"
            title="Configure Endpoint URL"
            aria-label="Settings"
          >
            <Settings size={18} />
          </button>
        </div>
      </div>

      {/* Settings Drawer/Modal */}
      {showSettings && (
        <div className="settings-banner">
          <div className="container settings-inner">
            <form onSubmit={handleSaveSettings} className="settings-form">
              <label htmlFor="api-url-input" className="settings-label">
                Backend API Base URL:
              </label>
              <input
                id="api-url-input"
                type="text"
                value={tempUrl}
                onChange={(e) => setTempUrl(e.target.value)}
                placeholder="http://localhost:8000"
                className="input-text settings-input"
              />
              <button type="submit" className="btn btn-sm btn-primary">
                Update & Reconnect
              </button>
              <button
                type="button"
                onClick={() => setShowSettings(false)}
                className="btn btn-sm btn-ghost"
              >
                Close
              </button>
            </form>
          </div>
        </div>
      )}
    </header>
  );
}
