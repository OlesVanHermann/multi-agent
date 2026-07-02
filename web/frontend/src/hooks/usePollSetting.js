import { useState } from 'react'

export function usePollSetting(key, defaultVal) {
  const [val, setVal] = useState(() => {
    const saved = localStorage.getItem(`poll_${key}`)
    return saved ? Number(saved) : defaultVal
  })
  const update = (e) => {
    const v = Number(e.target.value)
    setVal(v)
    localStorage.setItem(`poll_${key}`, v)
  }
  return [val, update]
}
