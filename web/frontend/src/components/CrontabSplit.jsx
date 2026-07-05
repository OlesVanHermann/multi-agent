import React from 'react'
import Terminal from './Terminal'

// Panneau Crontab 3 volets : liste des tâches, éditeur, terminal du
// scheduler (001). L'état vit dans useCrontab (App) pour survivre aux
// ouvertures/fermetures du panneau.
function CrontabSplit({ crontab, agents, focused, pollInterval }) {
  const {
    crontabEntries, crontabForm, setCrontabForm, crontabEdit, setCrontabEdit,
    cronAgent, setCronAgent, cronPeriod, setCronPeriod, cronPrompt, setCronPrompt,
    cronCreate, cronUpdate, cronSuspendResume, cronDelete,
    cronStartEdit, cronStartCopy, cronStartNew,
  } = crontab

  return (
    <div className="crontab-3split">
      <div className="crontab-list">
        <div className="crontab-header">
          <h3>TACHES PLANIFIEES</h3>
          <button className="crontab-add-btn" onClick={cronStartNew}>+ Nouveau</button>
        </div>
        <table className="crontab-table">
          <thead>
            <tr><th>Agent</th><th>Periode</th><th>Prompt</th><th>Status</th><th>Actions</th></tr>
          </thead>
          <tbody>
            {crontabEntries.map((e, i) => (
              <tr key={i} className={e.suspended ? 'crontab-suspended' : ''}>
                <td>{e.agent_id}</td>
                <td>{e.period} min</td>
                <td className="crontab-prompt-cell">{e.prompt.length > 60 ? e.prompt.slice(0, 60) + '...' : e.prompt}</td>
                <td><span className={`crontab-status ${e.suspended ? 'crontab-status-off' : 'crontab-status-on'}`}>{e.suspended ? 'Suspendu' : 'Actif'}</span></td>
                <td className="crontab-actions">
                  <button title="Modifier" onClick={() => cronStartEdit(e)}>Modifier</button>
                  <button title="Copier vers un autre agent/periode" onClick={() => cronStartCopy(e)}>Copier</button>
                  <button title={e.suspended ? 'Reactiver la tache' : 'Suspendre la tache'} className={e.suspended ? 'crontab-resume' : 'crontab-suspend'} onClick={() => cronSuspendResume(e)}>
                    {e.suspended ? 'Activer' : 'Suspendre'}
                  </button>
                  <button title="Supprimer la tache" className="crontab-del" onClick={() => cronDelete(e)}>Supprimer</button>
                </td>
              </tr>
            ))}
            {crontabEntries.length === 0 && (
              <tr><td colSpan={5} style={{textAlign:'center',color:'var(--text-secondary)',fontStyle:'italic'}}>Aucune tache planifiee</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="crontab-editor">
        {crontabForm ? (
          <div className="crontab-form">
            <div className="crontab-form-inline">
              <span className="crontab-form-label">{crontabEdit ? 'Modifier' : 'Nouveau'}</span>
              <select value={cronAgent} onChange={e => setCronAgent(e.target.value)}>
                <option value="">Agent</option>
                {agents.map(a => <option key={a.id} value={a.id}>{a.id}</option>)}
              </select>
              <select value={cronPeriod} onChange={e => setCronPeriod(Number(e.target.value))}>
                {[10, 30, 60, 120].map(v => <option key={v} value={v}>{v}min</option>)}
              </select>
            </div>
            <div className="crontab-form-row">
              <label>Prompt</label>
              <textarea rows={4} value={cronPrompt} onChange={e => setCronPrompt(e.target.value)} placeholder="Contenu du prompt..." />
            </div>
            <div className="crontab-form-actions">
              <button onClick={crontabEdit ? cronUpdate : cronCreate}>
                {crontabEdit ? 'Modifier' : 'Ajouter'}
              </button>
              <button onClick={() => { setCrontabForm(false); setCrontabEdit(null) }}>Annuler</button>
            </div>
          </div>
        ) : (
          <div className="crontab-editor-empty">Cliquer sur Modifier ou + Nouveau</div>
        )}
      </div>
      <div className="crontab-bottom">
        <div className="crontab-terminal-header">SCHEDULER — 001</div>
        <Terminal agentId="001" focused={focused} pollInterval={pollInterval} />
      </div>
    </div>
  )
}

export default CrontabSplit
