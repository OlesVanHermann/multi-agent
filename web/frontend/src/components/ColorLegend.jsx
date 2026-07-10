import React from 'react'

const dot = { display: 'inline-block', width: 40, textAlign: 'center' }

const ROWS = [
  ['blue',                'Bleu',           "waiting_approval — En attente de confirmation"],
  ['darkblue',            'Bleu foncé',     'plan_mode — Mode plan activé'],
  ['white',               'Blanc',          'starting — Démarrage en cours'],
  ['green',               'Vert foncé',     "has_bashes — Bashes en cours d'exécution"],
  ['lightgreen',          'Vert clair',     'busy — Claude en cours (esc to interrupt)'],
  ['gray border-orange',  'Bordure orange', 'context_warning — Contexte restant 1-10% (idle ou busy)'],
  ['gray border-blue',    'Bordure bleue',  'selected — Terminal ouvert'],
  ['red',                 'Rouge',          'context_compacted — Contexte compacté'],
  ['darkred',             'Rouge foncé',    'error / blocked — Erreur ou bloqué'],
  ['gray',                'Gris',           'idle / stale — Inactif'],
  ['darkgray',            'Gris foncé',     'stopped — Arrêté'],
]

function ColorLegend() {
  return (
    <div className="color-legend">
      <h3>Status — Couleurs</h3>
      <table>
        <thead><tr><th>Status</th><th>Couleur</th><th>Description</th></tr></thead>
        <tbody>
          {ROWS.map(([cls, name, desc]) => (
            <tr key={cls}>
              <td><span className={`agent-cell ${cls}`} style={dot}>●</span></td>
              <td>{name}</td>
              <td>{desc}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3 style={{marginTop:'1rem'}}>Priorité (haute → basse)</h3>
      <ol style={{margin:'0.5rem 0',paddingLeft:'1.5rem',color:'#ccc',fontSize:'0.85rem'}}>
        <li>context_limit / api_error</li>
        <li>context_compacted (compacting)</li>
        <li>plan_mode</li>
        <li>has_bashes</li>
        <li>busy</li>
        <li>context_warning (1-10%)</li>
        <li>active / idle</li>
      </ol>
    </div>
  )
}

export default ColorLegend
