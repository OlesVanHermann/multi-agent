import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '../../basePath'

// Gestion des favoris par projet (api/config/favoris) : liste des projets,
// projet courant (mémorisé en localStorage par user), positions 1-6,
// renommage débouncé en mode config.
export function useFavoris(username) {
  const [favoris, setFavoris] = useState({})       // {agentId: position 1-6}
  const [favorisMode, setFavorisMode] = useState(false) // config view
  const [project, setProject] = useState(() =>
    localStorage.getItem(`fav_project_${username}`) || ''
  )
  const [projectInput, setProjectInput] = useState('')
  const [projects, setProjects] = useState([])
  const projectRef = useRef(project)

  // Refresh projects list from backend
  const refreshProjects = useCallback(() => {
    return fetch(api(`api/config/favoris/projects?user=${username}`))
      .then(r => r.ok ? r.json() : { projects: [] })
      .then(d => { setProjects(d.projects || []); return d.projects || [] })
      .catch(() => [])
  }, [username])

  // Load projects list + resolve initial project
  useEffect(() => {
    refreshProjects().then(list => {
      let p = localStorage.getItem(`fav_project_${username}`) || ''
      if ((!p || !list.includes(p)) && list.length > 0) p = list[0]
      if (p) {
        setProject(p)
        projectRef.current = p
        localStorage.setItem(`fav_project_${username}`, p)
      }
    })
  }, [username, refreshProjects])

  // Load favoris when project changes
  useEffect(() => {
    if (!project) return
    projectRef.current = project
    fetch(api(`api/config/favoris?user=${username}&project=${encodeURIComponent(project)}`))
      .then(r => r.ok ? r.json() : {})
      .then(d => setFavoris(d || {}))
      .catch(() => {})
  }, [username, project])

  // Debounced project rename (only active in favorisMode with existing project)
  useEffect(() => {
    if (!favorisMode || !projectInput || !projectRef.current || projectInput === projectRef.current) return
    const timer = setTimeout(() => {
      const oldP = projectRef.current
      const newP = projectInput
      if (!oldP || oldP === newP) return
      fetch(api('api/config/favoris/rename'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user: username, old_project: oldP, new_project: newP })
      })
        .then(r => r.ok ? r.json() : null)
        .then(d => {
          if (!d) return
          setProject(d.project)
          projectRef.current = d.project
          setFavoris(d.favoris || {})
          localStorage.setItem(`fav_project_${username}`, d.project)
          refreshProjects()
        })
        .catch(() => {})
    }, 500)
    return () => clearTimeout(timer)
  }, [projectInput, favorisMode, username, refreshProjects])

  // Create project "new" and enter config mode immediately
  const createProject = useCallback(() => {
    const newName = 'new'
    fetch(api('api/config/favoris'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user: username, project: newName, favoris: {} })
    })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (!d) return
        setProject(d.project)
        projectRef.current = d.project
        setProjectInput(d.project)
        setFavoris({})
        localStorage.setItem(`fav_project_${username}`, d.project)
        refreshProjects()
        setFavorisMode(true)
      })
      .catch(() => {})
  }, [username, refreshProjects])

  // Enter favoris mode: if no project yet (NEW), create one
  const enterFavorisMode = useCallback(() => {
    if (favorisMode) {
      // Exit config mode
      setFavorisMode(false)
      return
    }
    if (!project) {
      createProject()
    } else {
      // Existing project — enter config, populate input
      setProjectInput(project)
      setFavorisMode(true)
    }
  }, [favorisMode, project, createProject])

  // Select an existing project from the dropdown ('__new__' creates one)
  const selectProject = useCallback((p) => {
    if (p === '__new__') {
      createProject()
      return
    }
    setProject(p)
    projectRef.current = p
    localStorage.setItem(`fav_project_${username}`, p)
  }, [username, createProject])

  // Delete current project
  const deleteProject = useCallback(() => {
    if (!project) return
    fetch(api('api/config/favoris/delete'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user: username, project })
    })
      .then(r => r.ok ? r.json() : null)
      .then(() => {
        setFavorisMode(false)
        setFavoris({})
        setProject('')
        projectRef.current = ''
        setProjectInput('')
        localStorage.removeItem(`fav_project_${username}`)
        refreshProjects().then(list => {
          if (list.length > 0) {
            setProject(list[0])
            projectRef.current = list[0]
            localStorage.setItem(`fav_project_${username}`, list[0])
          }
        })
      })
      .catch(() => {})
  }, [project, username, refreshProjects])

  const saveFavoris = useCallback((newFav) => {
    setFavoris(newFav)
    if (!project) return
    fetch(api('api/config/favoris'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user: username, project, favoris: newFav })
    }).catch(() => {})
  }, [username, project])

  const handleFavChange = (agentId, val) => {
    const newFav = { ...favoris }
    if (val === 'no') {
      delete newFav[agentId]
    } else {
      // Remove any other agent with same position
      const pos = parseInt(val)
      Object.keys(newFav).forEach(k => { if (newFav[k] === pos) delete newFav[k] })
      newFav[agentId] = pos
    }
    saveFavoris(newFav)
  }

  return {
    favoris, favorisMode, project, projectInput, setProjectInput, projects, projectRef,
    refreshProjects, enterFavorisMode, selectProject, deleteProject, handleFavChange,
  }
}
