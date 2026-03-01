import React, { useState, Suspense, useCallback, useMemo, useRef } from 'react'
import { CATEGORIES, FEATURES, createLazyPanel, searchFeatures } from './drive-features-registry'

// ============================================================
//  ERROR BOUNDARY -- catches lazy-load failures
// ============================================================

class PanelErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="df-error">
          <span className="df-error-icon">&#x26A0;&#xFE0F;</span>
          <span className="df-error-title">Failed to load panel</span>
          <span className="df-error-detail">{this.state.error?.message || 'Unknown error'}</span>
          <button
            className="df-error-retry"
            onClick={() => this.setState({ hasError: false, error: null })}
          >
            Retry
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

// ============================================================
//  LOADING SPINNER
// ============================================================

function LoadingSpinner() {
  return (
    <div className="df-loading">
      <div className="df-spinner" />
      <span>Loading panel...</span>
    </div>
  )
}

// ============================================================
//  DRIVE FEATURES TAB -- Main export
// ============================================================

export default function DriveFeaturesTab() {
  const [selectedFeature, setSelectedFeature] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')
  // Cache lazy components so we don't re-create them on every render
  const lazyCache = useRef({})

  // Find the selected feature entry
  const activeFeature = useMemo(
    () => FEATURES.find(f => f.id === selectedFeature),
    [selectedFeature]
  )

  // Get or create the lazy component for the active feature
  const PanelComponent = useMemo(() => {
    if (!activeFeature) return null
    if (!lazyCache.current[activeFeature.id]) {
      lazyCache.current[activeFeature.id] = createLazyPanel(
        activeFeature.panelPath,
        activeFeature.name
      )
    }
    return lazyCache.current[activeFeature.id]
  }, [activeFeature])

  // Filtered features based on search
  const filteredFeatures = useMemo(
    () => searchFeatures(searchQuery),
    [searchQuery]
  )

  // Group filtered features by category
  const grouped = useMemo(() => {
    const map = {}
    for (const cat of CATEGORIES) {
      const items = filteredFeatures.filter(f => f.category === cat.id)
      if (items.length > 0) map[cat.id] = items
    }
    return map
  }, [filteredFeatures])

  const handleBack = useCallback(() => {
    setSelectedFeature(null)
  }, [])

  const handleSelect = useCallback((featureId) => {
    setSelectedFeature(featureId)
  }, [])

  // -- Panel view (a specific feature is selected) --
  if (activeFeature && PanelComponent) {
    return (
      <div className="df-panel-view">
        <div className="df-panel-header">
          <button className="df-back-btn" onClick={handleBack}>
            &#x2190; Back
          </button>
          <span className="df-panel-icon">{activeFeature.icon}</span>
          <span className="df-panel-name">{activeFeature.name}</span>
        </div>
        <div className="df-panel-content">
          <PanelErrorBoundary key={activeFeature.id}>
            <Suspense fallback={<LoadingSpinner />}>
              <PanelComponent name={activeFeature.name} />
            </Suspense>
          </PanelErrorBoundary>
        </div>
      </div>
    )
  }

  // -- Grid view (category dashboard) --
  return (
    <div className="df-grid-view">
      {/* Search bar */}
      <div className="df-search-bar">
        <input
          type="text"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          placeholder="Search features..."
          className="df-search-input"
        />
        <span className="df-search-count">
          {filteredFeatures.length} / {FEATURES.length} features
        </span>
      </div>

      {/* Categories with feature cards */}
      <div className="df-categories">
        {CATEGORIES.map(cat => {
          const items = grouped[cat.id]
          if (!items) return null
          return (
            <div key={cat.id} className="df-category">
              <div className="df-category-header">
                <span className="df-category-icon">{cat.icon}</span>
                <span className="df-category-label">{cat.label}</span>
                <span className="df-category-count">{items.length}</span>
              </div>
              <div className="df-feature-grid">
                {items.map(feature => (
                  <button
                    key={feature.id}
                    className="df-feature-card"
                    onClick={() => handleSelect(feature.id)}
                    title={feature.name}
                  >
                    <span className="df-card-icon">{feature.icon}</span>
                    <span className="df-card-name">{feature.name}</span>
                  </button>
                ))}
              </div>
            </div>
          )
        })}

        {Object.keys(grouped).length === 0 && (
          <div className="df-empty">
            No features match &ldquo;{searchQuery}&rdquo;
          </div>
        )}
      </div>
    </div>
  )
}
