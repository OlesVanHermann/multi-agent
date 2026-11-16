// Suivi d'usage des forfaits : UNE présentation pour tous les moteurs.
//
// Le `percent` des snapshots keepalive (keepalive/usage_<profil>.json) est le
// pourcentage UTILISÉ : Claude Code l'affiche ainsi (/usage « 11% used ») ;
// Codex affiche « 60% left » (/status), converti en 100 - N par le collecteur
// (scripts/crontab-scheduler.py, _scrape_codex_status). La jauge se remplit
// donc avec la consommation, de 0 à 100 %, quel que soit le moteur.
//
// Couleurs (consigne opérateur 2026-11-16) : orange à partir de 2/3 utilisés,
// rouge à partir de 9/10 utilisés. Comparaisons entières (3 × p ≥ 200,
// 10 × p ≥ 900) : 66 % vert, 67 % orange, 89 % orange, 90 % rouge.

const COLORS = { ok: 'var(--green)', warn: 'var(--orange)', crit: 'var(--red)' }

// Pourcentage utilisé affiché : entier borné à [0, 100].
export function usageUsed(percent) {
  const n = Number(percent)
  if (!Number.isFinite(n)) return 0
  return Math.min(100, Math.max(0, Math.round(n)))
}

// 'ok' | 'warn' (≥ 2/3 utilisés) | 'crit' (≥ 9/10 utilisés)
export function usageLevel(percent) {
  const used = usageUsed(percent)
  if (used * 10 >= 900) return 'crit'
  if (used * 3 >= 200) return 'warn'
  return 'ok'
}

export function usageColor(percent) {
  return COLORS[usageLevel(percent)]
}

// Même libellé pour Claude et Codex.
export function usageTitle(bar) {
  const used = usageUsed(bar?.percent)
  const title = `${bar?.label || 'Quota'} : ${used} % utilisé, ${100 - used} % restant`
  return bar?.resets ? `${title} — reset ${bar.resets}` : title
}
