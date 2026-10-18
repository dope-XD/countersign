import { useCallback, useState } from 'react'
import Toast from '../components/Toast'

export function useToast() {
  const [msg, setMsg] = useState<string | null>(null)
  const [tone, setTone] = useState<'info' | 'error'>('info')
  // stable identity: pages use `show` in effect dependencies
  const show = useCallback((m: string, t: 'info' | 'error' = 'info') => {
    setTone(t)
    setMsg(m)
  }, [])
  const done = useCallback(() => setMsg(null), [])
  const node = <Toast msg={msg} tone={tone} onDone={done} />
  return { show, node }
}
