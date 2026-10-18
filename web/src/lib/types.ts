export type Tier = 'GREEN' | 'AMBER' | 'RED'

export type Customer = {
  id: string
  name: string
  age: number
  city: string
  language: string
  registered_mobile: string
  account_no: string
  balance: number
  upi_id: string
  usual_upi_max: number
  known_payees: string[]
  family_circle: string[]
}

export type ReqState = { status: string; by?: string; at?: number; until?: number; approval_id?: string; reason?: string }

export type BankRequest = {
  id: string
  customer_id: string
  channel: string
  call_id: string | null
  action: string
  details: Record<string, unknown>
  tier: Tier | null
  status: string
  created_at: number
  cooloff_until: number | null
  missing: string[] // requirements still outstanding, computed by the engine
  policy: {
    risk: string
    tier: Tier
    note: string
    no_phone_approval: boolean
    no_sensitive_details: boolean
    reqs: Record<string, ReqState>
    overrides: unknown[]
  }
}

export type Verdict = {
  r: number
  voice_tier: Tier
  tier: Tier
  live_tier: Tier
  reasons: string[]
  reason_text: string[]
  features: { s1: number; drift: number | null; windows: number }
  context: { flags: string[]; fri?: string | null; caller_cli?: string; live_app_session?: boolean; calls_24h?: number }
  context_raised: boolean
  updated: number
}

export type Call = {
  id: string
  caller_cli: string
  language: string
  status: 'ringing' | 'live' | 'ended'
  customer: Customer | null
  started: number
  elapsed: number
  tier: Tier | null
  verdict: Verdict | null
  windows: { t: number; p: number; drift: number | null }[]
  challenge: { id: string; say: string; done: boolean } | null
  liveness: { passed: boolean; lag_s: number | null; match: number; s1_reply: number | null; reasons: string[]; kind: string } | null
  requests: BankRequest[]
  case_id: string | null
  first_tier_at: number | null
  model: { s1: string; version: string; s2: boolean }
  timeline: { t: number; event: string; [k: string]: unknown }[]
}

export type Approval = {
  id: string
  request_id: string
  kind: 'app_approval' | 'family_ping'
  target_customer: string
  summary: { question: string; detail?: string; amount?: number; payee?: string; [k: string]: unknown }
  status: string
  created_at: number
}

export type ActionField = { key: string; label: string; placeholder?: string }

export const ACTIONS: Record<string, { label: string; risk: 'low' | 'medium' | 'high'; fields?: ActionField[] }> = {
  balance: { label: 'Balance enquiry', risk: 'low' },
  block_card: { label: 'Block card', risk: 'low' },
  report_fraud: { label: 'Report fraud', risk: 'low' },
  account_details: { label: 'Account details', risk: 'medium' },
  card_reissue: { label: 'Reissue card', risk: 'medium' },
  change_mobile: { label: 'Change registered mobile number', risk: 'high', fields: [{ key: 'new_mobile', label: 'New mobile', placeholder: '+91…' }] },
  add_payee: { label: 'Add a new payee', risk: 'high', fields: [{ key: 'payee', label: 'Payee UPI / account', placeholder: 'name@bank' }] },
  raise_limit: { label: 'Raise transfer limit', risk: 'high', fields: [{ key: 'limit', label: 'New limit (₹)', placeholder: '200000' }] },
  large_transfer: { label: 'Large transfer', risk: 'high', fields: [{ key: 'amount', label: 'Amount (₹)' }, { key: 'payee', label: 'To' }] },
}

export const REQ_LABEL: Record<string, string> = {
  standard_checks: 'Standard checks',
  liveness: 'Liveness check',
  app_approval: 'Approval in the app (passkey)',
  cooloff_24h: '24 h cool-off',
  fraud_desk: 'Fraud desk review',
  alert_customer: 'Customer alerted',
}

export const inr = (n: number) => '₹' + Math.round(n).toLocaleString('en-IN')
export const maskPhone = (p: string) => (p.length > 6 ? `${p.slice(0, 5)}••• ••${p.slice(-3)}` : p)
export const ago = (ts: number) => {
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts))
  return s < 60 ? `${s} s ago` : s < 3600 ? `${Math.floor(s / 60)} min ago` : `${Math.floor(s / 3600)} h ago`
}
export const clock = (secs: number) => `${String(Math.floor(secs / 60)).padStart(2, '0')}:${String(Math.floor(secs % 60)).padStart(2, '0')}`
