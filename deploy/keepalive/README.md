# Relay keep-alive (Cloudflare Worker)

Calls `https://countersign-relay.onrender.com/health` every 10 minutes, so:

- Render's free plan never puts the relay to sleep (it sleeps after 15 idle minutes and takes about a minute to wake);
- Supabase's free plan never pauses the database (it pauses after 7 days without database activity, and only a click in its dashboard brings it back). `/health` runs a query, so every ping counts.

It uses 144 of the free plan's 100,000 requests a day.

## Deploy (once, from this folder)

```bash
npx wrangler login
```

```bash
npx wrangler deploy
```

Check it: Cloudflare dashboard → **Workers & Pages** → **countersign-keepalive** → **Logs**. You should see `{"ok":true,"status":200,...}` every 10 minutes. You can also open the Worker's `*.workers.dev` address to run a ping by hand.

If the relay ever moves, change `RELAY` in `worker.js` and deploy again.
