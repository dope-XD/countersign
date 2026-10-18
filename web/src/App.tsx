import { Link, Route, Routes } from 'react-router-dom'
import Agent from './pages/Agent'
import Bank from './pages/Bank'
import Caller from './pages/Caller'
import Demo from './pages/Demo'
import FraudDesk from './pages/FraudDesk'
import Metrics from './pages/Metrics'
import Record from './pages/Record'
import StaffGate from './components/StaffGate'
import { Signature } from './components/ui'

function Home() {
  const links = [
    { to: '/call', title: 'Call the bank', sub: 'Softphone for any phone browser. Audio goes out as 8 kHz G.711.' },
    { to: '/agent', title: 'Agent console', sub: 'Voice Trust Card, policy steps, liveness check.' },
    { to: '/bank/rahul', title: "Rahul's bank app", sub: 'Passkey approvals, Family Circle replies.' },
    { to: '/bank/sunita', title: "Sunita's bank app", sub: 'UPI payment guard and pause screen.' },
    { to: '/fraud', title: 'Fraud desk', sub: 'Case queue, evidence clips, 1930 and DIP reports.' },
    { to: '/metrics', title: 'Metrics', sub: 'IndiaCall and benchmark results, misses included.' },
    { to: '/demo', title: 'Demo operator', sub: 'QR codes, scenario switches, what we store.' },
    { to: '/record', title: 'IndiaCall recorder', sub: 'Consented teammates record the test script.' },
  ]
  return (
    <main className="mx-auto max-w-4xl px-4 py-12">
      <Signature className="h-8 w-20 text-brand" />
      <h1 className="mt-4 text-5xl font-extrabold tracking-tight sm:text-6xl">Countersign</h1>
      <p className="mt-4 max-w-2xl text-lg">A voice can ask the bank for anything. The customer's own phone has to sign before anything risky happens.</p>
      <div className="mt-10 grid gap-3 sm:grid-cols-2">
        {links.map((l) => (
          <Link key={l.to} to={l.to} className="card block p-4 no-underline hover:border-brand">
            <div className="font-display text-lg font-bold text-ink">{l.title}</div>
            <div className="text-sm text-muted">{l.sub}</div>
          </Link>
        ))}
      </div>
      <p className="mt-10 text-xs text-muted">RAKSHAM 2026 · Problem statement 01 · Team losers. Prototype with mocked core banking, DoT FRI and SIM-swap feeds.</p>
    </main>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/call" element={<Caller />} />
      <Route path="/agent" element={<StaffGate><Agent /></StaffGate>} />
      <Route path="/bank/:customer" element={<Bank />} />
      <Route path="/fraud" element={<StaffGate><FraudDesk /></StaffGate>} />
      <Route path="/metrics" element={<StaffGate><Metrics /></StaffGate>} />
      <Route path="/demo" element={<StaffGate><Demo /></StaffGate>} />
      <Route path="/record" element={<StaffGate><Record /></StaffGate>} />
      <Route path="*" element={<Home />} />
    </Routes>
  )
}
