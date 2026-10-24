// Keeps the relay awake: every 10 minutes, ask its /health (docs/DEPLOY.md).
// Render's free plan sleeps after 15 idle minutes and takes about a minute to wake;
// /health also queries the database, so Supabase's free plan never pauses for inactivity.

const RELAY = "https://countersign-relay.onrender.com/health";

export default {
  async scheduled(_event, _env, ctx) {
    ctx.waitUntil(ping());
  },

  // A ping by hand: `npx wrangler dev`, then open http://localhost:8787 (the deployed Worker has no public address).
  async fetch() {
    const result = await ping();
    return Response.json(result, { status: result.ok ? 200 : 502 });
  },
};

async function ping() {
  const started = Date.now();
  try {
    const r = await fetch(RELAY, { signal: AbortSignal.timeout(90_000), headers: { "user-agent": "countersign-keepalive" } });
    const result = { ok: r.ok, status: r.status, ms: Date.now() - started, body: await r.text() };
    console.log(JSON.stringify(result));
    return result;
  } catch (e) {
    const result = { ok: false, error: String(e), ms: Date.now() - started };
    console.error(JSON.stringify(result));
    return result;
  }
}
