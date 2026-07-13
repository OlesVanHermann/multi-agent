import React from 'react'
import Terminal from './Terminal'

// Panneau Keep Alive : table des profils login (+ barres d'usage) et
// terminal de la session keepalive sélectionnée. L'état vit dans
// useKeepAlive (App) pour survivre aux ouvertures/fermetures du panneau.
function KeepAliveSplit({ keepAlive, focused, pollInterval }) {
  const {
    keepAliveEntries, keepAliveInfo, keepAliveUsage,
    selectedKeepAlive, setSelectedKeepAlive,
    kaStart, kaStop,
  } = keepAlive

  return (
    <div className="crontab-split">
      <div className="crontab-top">
        <div className="crontab-header">
          <h3>LOGIN KEEP ALIVE</h3>
        </div>
        <table className="crontab-table keepalive-table">
          <thead>
            <tr><th>Profil</th><th>Login</th><th>Org</th><th>Email</th><th>CWD</th><th>Actions</th></tr>
          </thead>
          <tbody>
            {keepAliveEntries.map((e) => {
              const ki = keepAliveInfo[e.profile]
              const usage = keepAliveUsage[e.profile]
              const bars = usage?.bars || []
              return (
              <React.Fragment key={e.profile}>
              <tr>
                <td>
                  <button
                    className={`crontab-status ${e.running ? 'crontab-status-on' : 'crontab-status-off'} ka-profile-btn`}
                    onClick={() => setSelectedKeepAlive(e.session)}
                  >{e.profile}</button>
                </td>
                <td className="keepalive-info">{ki ? (ki.login_method || '?').slice(0, 20) : (e.running ? '...' : '—')}</td>
                <td className="keepalive-info">{ki ? (ki.organization || '?').slice(0, 20) : ''}</td>
                <td className="keepalive-info">{ki ? (ki.email || '?').slice(0, 20) : ''}</td>
                <td className="keepalive-info">{ki ? './' + (ki.cwd || '').split('/').filter(Boolean).pop() + '/' : ''}</td>
                <td className="crontab-actions">
                  {e.running
                    ? <button className="crontab-suspend" onClick={() => kaStop(e.profile)}>Stop</button>
                    : <button className="crontab-resume" onClick={() => kaStart(e.profile)}>Start</button>
                  }
                </td>
              </tr>
              <tr className="ka-usage-row">
                <td></td>
                <td colSpan="5">
                  {bars.length > 0 ? (
                    <span className="lm-usage-bars">
                      {bars.map((b, i) => (
                        <span key={i} className="lm-usage-bar" title={`${b.label}: ${b.percent}% — resets ${b.resets || ''}`}>
                          <span className="lm-usage-bar-fill" style={{
                            width: `${b.percent}%`,
                            background: b.percent > 80 ? 'var(--red)' : b.percent > 50 ? 'var(--orange)' : 'var(--green)'
                          }} />
                          <span className="lm-usage-bar-text">{b.percent}%</span>
                        </span>
                      ))}
                    </span>
                  ) : (
                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.6rem', fontStyle: 'italic' }}>pas de données usage</span>
                  )}
                </td>
              </tr>
              </React.Fragment>
              )
            })}
            {keepAliveEntries.length === 0 && (
              <tr><td colSpan={6} style={{textAlign:'center',color:'var(--text-secondary)',fontStyle:'italic'}}>Aucun profil de login</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="crontab-bottom">
        <div className="crontab-terminal-header">
          KEEPALIVE — {selectedKeepAlive || '(cliquez Voir)'}
        </div>
        {selectedKeepAlive
          ? <Terminal agentId={selectedKeepAlive} focused={focused} pollInterval={pollInterval} />
          : <div className="no-selection">Selectionnez un login pour voir son terminal</div>
        }
      </div>
    </div>
  )
}

export default KeepAliveSplit
