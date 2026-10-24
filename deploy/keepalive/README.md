# Relay keep-alive (Cloudflare Worker)

Calls `https://countersign-relay.onrender.com/health` every 10 minutes, so:

- Render's free plan never puts the relay to sleep (it sleeps after 15 idle minutes and takes about a minute to wake);
- Supabase's free plan never pauses the database (it pauses after 7 days without database activity, and only a click in its dashboard brings it back). `/health` runs a query, so every ping counts.

It uses 144 of the free plan's 100,000 requests a day.

## Deploy (once, from this folder)

First open **Workers & Pages** once in the Cloudflare dashboard. That creates the account's workers.dev subdomain, and
until it exists Cloudflare refuses the schedule (403, code 10063). The Worker itself has no public address
(`workers_dev: false`).

```bash
npx wrangler login
```

```bash
npx wrangler deploy
```

Check it: Cloudflare dashboard → **Workers & Pages** → **countersign-keepalive** → **Logs**. You should see `{"ok":true,"status":200,...}` every 10 minutes.

To run one ping by hand, run `npx wrangler dev` in this folder and open http://localhost:8787.

If the relay ever moves, change `RELAY` in `worker.js` and deploy again.
