/** Which phone and app the bank pages are running in. */

export const APP_PACKAGE = 'app.countersign.bank'

/** Opened inside the CS Bank Android app (its start URL carries ?app=android). Remembered for the session. */
export function inAndroidApp(): boolean {
  try {
    if (new URLSearchParams(window.location.search).get('app') === 'android') sessionStorage.setItem('cs.app', 'android')
    return sessionStorage.getItem('cs.app') === 'android'
  } catch {
    return new URLSearchParams(window.location.search).get('app') === 'android'
  }
}

export function deviceLabel() {
  const ua = navigator.userAgent
  const m = ua.match(/Android [\d.]+; ([^)]+)\)/) || ua.match(/(iPhone|iPad|Macintosh|Windows NT [\d.]+)/)
  return m ? m[1].trim() : 'this device'
}
