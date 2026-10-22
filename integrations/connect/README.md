# Amazon Connect spike (Workstream C, item 1)

This spike is for the RAKSHAM finale. It proves that we can take a real Amazon Connect call, read both audio legs out of Kinesis Video Streams (KVS) as 8 kHz PCM, and measure how far behind the live call that audio reaches the laptop.

**The engine now takes Connect calls itself** (`engine/ingest/connect.py`). Once the spike below has worked, point the Lambda's `ENGINE_URL` at the engine instead of `receiver.py`, and start the engine with:

```powershell
$env:COUNTERSIGN_CONNECT_SECRET = "<the Lambda's CONNECT_HMAC_SECRET>"
$env:COUNTERSIGN_CONNECT_AWS_PROFILE = "countersign-kvs"   # or the usual AWS_* variables
.un.ps1
```

Each call shows up on `/agent` tagged "Amazon Connect", with how far behind the call its audio is. The agent talks in the CCP and works the Voice Trust Card, requests and liveness check in `/agent`. For caller-ID matching, add a **Set contact attributes** block that saves the customer's number as user-defined `cli` (`$.CustomerEndpoint.Address`); `lang` (e.g. `hi-IN`) picks the liveness language. Web calling has no number, so set `cli` by hand for the demo.

```
caller (web calling widget) ──► Connect (ap-southeast-1) ──► Start media streaming ──► KVS stream (MKV, 2 tracks)
                                   │                                                       │ GetMedia
                                   └─► Invoke Lambda (lambda_start.py) ──HMAC POST──► receiver.py / engine ──► kvs_dump.py
agent (CCP in browser) ◄── queue ◄─┘
```

| File | What it is |
| --- | --- |
| `mkv.py` | Minimal streaming EBML/MKV reader (pure stdlib). It yields track entries, cluster timecodes, SimpleBlocks and SimpleTags. It is written to move into `engine/ingest/` unchanged. |
| `kvs_dump.py` | `GetDataEndpoint` + `GetMedia` → one WAV per track (8 kHz s16le) plus `fragments.json`, which holds KVS producer/server timestamps against laptop arrival time for each fragment. |
| `lambda_start.py` | Lambda for the contact flow. It POSTs `{contactId, streamArn, startFragment, startTimestamp, attributes, sentAt}` to `$ENGINE_URL/api/ingest/connect/start` with `X-Countersign-Signature: sha256=<HMAC-SHA256 of the raw body>`. Stdlib only. |
| `receiver.py` | Stands in for that engine endpoint during the spike. It checks the signature and starts `kvs_dump` for the contact straight away, while the call is still live. It can also serve the widget test page. |
| `tests/` | Synthetic-MKV tests for the reader and dumper, plus signing/handler tests for the Lambda. |

Cost: Connect, KVS and Lambda are all pay per use. The plan budgets about US$10–30 for the whole spike plus the finale. Set the budget alarm in step 0 **before** anything else. Prices: [Connect pricing](https://aws.amazon.com/connect/pricing/), [KVS pricing](https://aws.amazon.com/kinesis/video-streams/pricing/).

Use region **Asia Pacific (Singapore) `ap-southeast-1`** for everything. Connect is not offered in Mumbai. Singapore has live media streaming, the communications widget and in-app/web calling ([feature availability by Region](https://docs.aws.amazon.com/connect/latest/adminguide/regions.html)).

---

## 0. Budget alarm (do this first)

1. Open the Billing and Cost Management console, go to **Budgets**, and choose **Create budget**.
2. Choose **Use a template (simplified)**, then **Monthly cost budget**.
3. Name it `countersign-connect-spike`, set the amount to **30 USD**, and add the team's email addresses as recipients. Choose **Create budget**.
4. Optional but useful: edit the budget (**Template settings → Custom**) and add a second alert at **actual > 10 USD**. That way you hear about a runaway cost early.

Budgets is an alarm, not a spending cap. Its data refreshes a few times a day, so the teardown in step 9 still matters.
Docs: [Creating a budget](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-create.html), [Using a budget template](https://docs.aws.amazon.com/cost-management/latest/userguide/budget-templates.html).

## 1. Create the Connect instance

1. In the console, switch the region to **Asia Pacific (Singapore)**. Open Amazon Connect and choose **Create instance**.
2. Identity: **Store users in Amazon Connect**. Choose an instance alias such as `countersign-raksham`. The agent URLs become `https://countersign-raksham.my.connect.aws/`.
3. Add an administrator (you).
4. Telephony: allow **incoming calls**. Outbound calls are not needed. You do **not** need to claim a phone number, because web calling does not use one.
5. Keep the default data storage and create the instance. It takes a minute or two.

Docs: [Create an instance](https://docs.aws.amazon.com/connect/latest/adminguide/amazon-connect-instances.html).

## 2. Enable live media streaming (1 h retention, KMS)

1. Connect console → your instance alias → **Data storage** → **Live media streaming** → **Edit** → **Enable live media streaming**.
2. **Prefix**: `countersign`. Stream names start with this prefix, and the IAM policy in step 7 relies on it.
3. **Encryption**: choose the AWS managed key **`aws/kinesisvideo`**. That is the simplest choice, because the laptop then needs no KMS permission of its own. A customer managed key also works, but it has to be in `ap-southeast-1`, and the consumer then needs `kms:Decrypt` on it (see step 7). Do not pick `aws/connect` or another service's managed key, because Connect rejects them.
4. **Data retention period**: **1 hour**. Do not use "No data retention": that keeps data for only 5 minutes, which is too short to re-pull a call.
5. **Save** under Live media streaming, then **Save** at the bottom of the page.

Connect creates and reuses KVS streams by itself, one per active call. Don't delete or modify them.
Docs: [Enable live media streaming](https://docs.aws.amazon.com/connect/latest/adminguide/enable-live-media-streams.html), [Plan for live media streaming](https://docs.aws.amazon.com/connect/latest/adminguide/plan-live-media-streams.html) (8 kHz, one track per direction), [KVS and KMS](https://docs.aws.amazon.com/kinesisvideostreams/latest/dg/how-kms.html).

## 3. Deploy the Lambda

1. Generate the shared secret once and keep it in your password manager. The receiver/engine needs the same value:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Open the Lambda console (Singapore) and choose **Create function** → **Author from scratch**. Name it `countersign-connect-start`, runtime **Python 3.12** (any 3.11+ works), and accept the default execution role.
3. Upload the code with either option:
   - Zip it: `Compress-Archive integrations\connect\lambda_start.py lambda_start.zip`, then **Upload from → .zip file**.
   - Or paste it: in the inline editor, create `lambda_start.py`, paste the file in and **Deploy**.
4. **Runtime settings → Edit → Handler**: `lambda_start.handler`.
5. **Configuration → General configuration → Timeout**: **5 s**. The flow block waits at most 8 s.
6. **Configuration → Environment variables**:
   | Key | Value |
   | --- | --- |
   | `ENGINE_URL` | the HTTPS URL of the receiver/engine, e.g. `https://<your-static-domain>.ngrok-free.app` (no trailing path) |
   | `CONNECT_HMAC_SECRET` | the secret from step 3.1 |
   | `ENGINE_TIMEOUT_S` | optional, default `3` |
7. Add the function to the instance: Connect console → instance → **Flows** → **AWS Lambda** → pick `countersign-connect-start` → **Add Lambda Function**. This also grants Connect permission to invoke it.

The function never raises. It returns `{"countersign": "ok" | "no_stream" | "error" | "not_configured", "status": ...}`, so the flow continues to the queue whatever happens. Its CloudWatch log group shows what it sent.
Docs: [Grant Connect access to Lambda functions](https://docs.aws.amazon.com/connect/latest/adminguide/connect-lambda-functions.html) (event format, 8 s limit, flat string-map response), [Lambda environment variables](https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html), [Python handler](https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html).

## 4. Contact flow

Open the admin website (`https://<alias>.my.connect.aws/`), go to **Routing → Flows → Create flow**, name it `countersign-inbound` (type: inbound flow), and build:

1. **Set logging behavior**: Enable. Flow logs go to CloudWatch, which helps when something misroutes.
2. **Set contact attributes**: namespace **User defined**, e.g. `bank` = `demo` and `scenario` = `spike`. These arrive in the Lambda payload as `attributes`.
3. **Start media streaming**: tick **From the customer** and **To the customer**. Connect **Error** straight to step 6, so a streaming failure never blocks the caller.
4. **Invoke AWS Lambda function**: select `countersign-connect-start`, **Timeout** 5 s, **Response validation** STRING_MAP. Connect both **Success** and **Error** onward.
5. Optional: **Set contact attributes**: save the External value `countersign` as user-defined `countersign_status`, so the outcome shows up in the contact record.
6. **Set working queue**: `BasicQueue`.
7. **Transfer to queue**. Connect **At capacity** and **Error** to **Disconnect / hang up**.

**Save** and **Publish**. There is no **Stop media streaming** block: streaming runs until the contact ends, and it covers the agent leg after the transfer too.
The Lambda reads `Details.ContactData.MediaStreams.Customer.Audio.{StreamARN, StartFragmentNumber, StartTimestamp}`. `StartTimestamp` is in epoch ms.
Docs: [Start media streaming block](https://docs.aws.amazon.com/connect/latest/adminguide/start-media-streaming.html), [Example flow for testing live media streaming](https://docs.aws.amazon.com/connect/latest/adminguide/use-media-streams-blocks.html), [Media streaming contact attributes](https://docs.aws.amazon.com/connect/latest/adminguide/media-streaming-attributes.html), [Invoke AWS Lambda function block](https://docs.aws.amazon.com/connect/latest/adminguide/invoke-lambda-function-block.html), [Set contact attributes](https://docs.aws.amazon.com/connect/latest/adminguide/set-contact-attributes.html), [Set working queue](https://docs.aws.amazon.com/connect/latest/adminguide/set-working-queue.html), [Transfer to queue](https://docs.aws.amazon.com/connect/latest/adminguide/transfer-to-queue.html), [Set logging behavior](https://docs.aws.amazon.com/connect/latest/adminguide/set-logging-behavior.html).

## 5. Web calling widget on an allowed domain

1. Admin website → **Channels → Communication widgets → Add communication widget**. Name it `countersign-web-call`.
2. Under **Communications options**, turn on **Web calling** (leave video and screen share off) and choose `countersign-inbound` as its flow. **Save and continue**, set the styling, then **Save and continue** again.
3. **Domains**: add the exact HTTPS origin that will host the page, e.g. `https://<your-static-domain>.ngrok-free.app`. The protocol must match exactly, and subdomains are included automatically. Keep the ngrok free plan's static domain so this entry never changes.
4. Security: **No** (no JWT) is fine for the spike.
5. Copy the generated `<script>` snippet into `data/runtime/connect/widget.html` (that folder is gitignored), inside a minimal page:
   ```html
   <!doctype html><html><head><meta charset="utf-8"><title>Countersign test call</title></head>
   <body><h1>Countersign test call</h1><!-- paste the widget snippet here --></body></html>
   ```
6. `receiver.py --widget-page data/runtime/connect/widget.html` serves it at `/` on the same tunnel as the Lambda endpoint (step 8). On the free plan, ngrok shows a one-time "Visit site" warning in the browser; click through it. The caller's browser has to allow microphone access.

Docs: [Configure an out-of-the-box communication widget](https://docs.aws.amazon.com/connect/latest/adminguide/config-com-widget1.html), [Allowed-domain rules and snippet](https://docs.aws.amazon.com/connect/latest/adminguide/add-chat-to-website.html), [Supported browsers](https://docs.aws.amazon.com/connect/latest/adminguide/connect-supported-browsers.html).

## 6. Agent CCP

1. The admin user already has the **Basic Routing Profile**, which serves `BasicQueue`, so it can take the test call. For a separate agent, go to **Users → Add new users** with the **Agent** security profile and **Basic Routing Profile**.
2. On a second laptop or browser profile, open `https://<alias>.my.connect.aws/ccp-v2/` in Chrome, Edge or Firefox, allow the microphone, and set the status to **Available**.

Docs: [Launch the CCP](https://docs.aws.amazon.com/connect/latest/adminguide/launch-ccp.html).

## 7. IAM for the laptop consumer

Create an IAM user (or an Identity Center permission set) named `countersign-kvs-reader`, with access keys stored as an AWS CLI profile (`aws configure --profile countersign-kvs`) and **only** this policy. Replace `<ACCOUNT_ID>`, and change the `countersign` prefix if you used a different one in step 2:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadConnectCallAudio",
      "Effect": "Allow",
      "Action": ["kinesisvideo:GetDataEndpoint", "kinesisvideo:GetMedia"],
      "Resource": "arn:aws:kinesisvideo:ap-southeast-1:<ACCOUNT_ID>:stream/countersign*/*"
    }
  ]
}
```

If step 2 used a **customer managed** KMS key, add this statement as well:

```json
{ "Sid": "DecryptCallAudio", "Effect": "Allow", "Action": "kms:Decrypt",
  "Resource": "arn:aws:kms:ap-southeast-1:<ACCOUNT_ID>:key/<KEY_ID>" }
```

Diagnosing failures:
- `GetMedia` fails with `AccessDenied` / `NotAuthorizedException`: check the stream ARN the Lambda logged. If its name does not start with the prefix, widen `Resource` to `stream/*/*` for the spike.
- KVS error tag `4500` ("access denied for the stream's KMS key"): the KMS statement is missing.

Docs: [Controlling access to KVS with IAM](https://docs.aws.amazon.com/kinesisvideostreams/latest/dg/how-iam.html), [GetDataEndpoint](https://docs.aws.amazon.com/kinesisvideostreams/latest/APIReference/API_GetDataEndpoint.html), [GetMedia](https://docs.aws.amazon.com/kinesisvideostreams/latest/APIReference/API_dataplane_GetMedia.html) (tags, error codes 4500–4506, limit of 5 calls/s per stream).

## 8. Run the spike against a test call

Run everything from the repo root in PowerShell, with the project venv:

```powershell
.venv\Scripts\python.exe -m pip install -r integrations\connect\requirements.txt
```

1. Sync the laptop clock, because the lag numbers compare it with AWS clocks. Check the offset first; `w32tm /resync` needs an admin shell:
   ```powershell
   w32tm /stripchart /computer:time.aws.com /samples:3 /dataonly
   ```
2. Start the receiver with the same secret as the Lambda:
   ```powershell
   $env:CONNECT_HMAC_SECRET = "<secret>"; .venv\Scripts\python.exe -m integrations.connect.receiver --run --profile countersign-kvs --widget-page data\runtime\connect\widget.html
   ```
3. In another terminal, start the tunnel. `ENGINE_URL` on the Lambda must be this URL:
   ```bash
   ngrok http --url=<your-static-domain>.ngrok-free.app 8787
   ```
   Older ngrok v3 builds call the flag `--domain`.
4. Agent: CCP set to **Available**. Caller: open `https://<your-static-domain>.ngrok-free.app/`, start a web call, and talk for 1–2 minutes. The agent should accept the call and speak too, so both tracks get audio. Then hang up.
5. When the flow hits the Lambda, the receiver logs `contact <id> ...` and launches `kvs_dump` for that contact. Output lands in `data/runtime/connect/<contactId>/`:
   - `AUDIO_FROM_CUSTOMER.wav` and `AUDIO_TO_CUSTOMER.wav`. Listen to both.
   - `fragments.json`: per fragment, `producer_timestamp`, `server_timestamp`, `arrival_first` and `arrival_last`, plus derived values: `server_minus_producer_ms` (Connect → KVS), `arrival_minus_producer_ms`, and `last_sample_lag_ms`, the delay from the last sample spoken in a fragment to its last byte on the laptop. `last_sample_lag_ms` is the delay the engine would add. Medians and p95 are in `summary`.
   - `stream.mkv`: the raw bytes, kept as the recorded test fixture for `engine/ingest/` later.

**Without the receiver.** The Lambda's CloudWatch log has one line per call with the contact ID, stream ARN and start fragment. Copy them into:
```powershell
.venv\Scripts\python.exe -m integrations.connect.kvs_dump --profile countersign-kvs --stream-arn <StreamARN> --start-fragment <StartFragmentNumber> --contact-id <ContactId> --save-mkv
```
Run that within the 1 h retention window. A pull after the call has ended shows the format correctly, but its lag numbers are meaningless: only a pull during the live call measures lag.

**Replay offline.** No AWS and no boto3 are needed:
```powershell
.venv\Scripts\python.exe -m integrations.connect.kvs_dump --from-file data\runtime\connect\<contactId>\stream.mkv --out data\runtime\connect\replay
```

`kvs_dump` stops at end of stream, after `--idle-timeout` seconds of silence (default 10), at `--max-seconds` (default 900), on Ctrl+C, or when a fragment's `ContactId` tag no longer matches `--contact-id`. The last case matters because Connect reuses a stream for the next call. Each stop still writes the outputs.

### What the spike has to answer (write the answers into the plan)

- [ ] Track entries: codec ID (`A_PCM/INT/LIT` or `/BIG`? `kvs_dump` byte-swaps BIG), sampling frequency, channels and bit depth for both `AUDIO_FROM_CUSTOMER` and `AUDIO_TO_CUSTOMER`.
- [ ] Is every fragment a fresh EBML header + Segment, and does each fragment carry the `ContactId` tag? `fragments.json` → `tags`.
- [ ] Format of `AWS_KINESISVIDEO_PRODUCER_TIMESTAMP` / `SERVER_TIMESTAMP` (seconds with decimals, or ms?). The parser accepts both; record which one it is.
- [ ] `FRAGMENT_NUMBER` with the Lambda's `StartFragmentNumber`: does the first fragment returned equal it, or is it the next one (the API doc says "after")? Compare against `summary.first_fragment_number`. If audio is missing at the start, the engine should use `PRODUCER_TIMESTAMP` with `StartTimestamp` instead.
- [ ] Fragment duration (`summary.fragment_audio_ms`) and live lag (`last_sample_lag_ms` median/p95). These numbers go on `/metrics`.
- [ ] Gaps per track (`tracks[].gaps_over_20ms`): is there silence suppression, or does the customer track carry hold audio?
- [ ] What GetMedia does after hang-up: does it close (`end of stream`) or go quiet (`idle`)?

## 9. Teardown after the finale

1. Instance → **Data storage → Live media streaming → Edit**: disable it. KVS data expires after the 1 h retention.
2. Delete the communication widget, then the instance (Connect console → select the instance → **Remove**).
3. Delete the Lambda `countersign-connect-start` and its log group, plus the `countersign-kvs-reader` user and its access keys.
4. Keep the budget until the next bill closes.

## Tests

The repo's default `pytest` run only collects `engine/tests` (`testpaths` in `pyproject.toml`), so run these explicitly:

```powershell
.venv\Scripts\python.exe -m pytest integrations/connect -q
```
```powershell
.venv\Scripts\python.exe -m ruff check integrations
```

## References

- Connect: [Set up live media streaming](https://docs.aws.amazon.com/connect/latest/adminguide/customer-voice-streams.html) and its sub-pages linked above; [connect-kvs-consumer-demo](https://github.com/amazon-connect/connect-kvs-consumer-demo), AWS's Java consumer (the track names and the 8 kHz signed 16-bit PCM come from it).
- KVS: [GetMedia](https://docs.aws.amazon.com/kinesisvideostreams/latest/APIReference/API_dataplane_GetMedia.html), [StartSelector](https://docs.aws.amazon.com/kinesisvideostreams/latest/APIReference/API_dataplane_StartSelector.html), [quotas](https://docs.aws.amazon.com/kinesisvideostreams/latest/dg/limits.html).
- Matroska: [element IDs](https://www.matroska.org/technical/elements.html), [RFC 8794 (EBML)](https://www.rfc-editor.org/rfc/rfc8794).
