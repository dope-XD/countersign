# Demo script (about 6 minutes)

Setup: laptop shows `/agent` (left half) and `/fraud` (right half). Phone A is Rahul's (`/bank/rahul`, passkey bound). Phone B is Sunita's (`/bank/sunita`). Phone C is the caller (`/call`). `/demo` is open in another tab. Press **Reset demo world** first.

Who plays whom: Pushkar is the attacker and the agent "Meera". Reshaan is "Rahul" and holds Phone A. Sarah narrates and holds Phone B.

## Scene 1: the clone calls the bank (2 min)

1. Phone C: Calling from **Unknown number**, Voice source **Microphone** with the laptop's Voicemeeter cable selected, which is fed by Seed-VC converting Pushkar's voice into Reshaan's. (Fallback: **Play a recording** with `data/indiacall/clones/xtts/reshaan/O01.wav`.) Tap **Call**.
2. Agent console: **Answer**. Pick **Rahul Sharma**, choose **Change registered mobile number**, type a new number, **Log request**.
3. The clone speaks the opening line. Within about 8 s the card turns **AMBER** with `CLI_MISMATCH` (and usually `SYN_ARTIFACT_MED/HIGH`).
4. **Start liveness check**. Meera reads the challenge aloud. The clone answers late or in a flat voice, and the card turns **RED** with `RESP_LAG` or `SYN_ARTIFACT_HIGH`.
5. Point out: **Override** is greyed out ("not available on RED"). The checklist now needs app approval, a 24 h cool-off and the fraud desk.
6. Click **Send app approval**. Phone A buzzes: "Did you ask us to: Change registered mobile number?". Reshaan taps **No, this wasn't me**.
7. Fraud desk (right half): the case appears with tier, reasons, timeline and an encrypted 20 s clip. Play it (it logs the play), then **Confirm fraud**. NCRP/1930 and DoT DIP reports appear.

Line to say: *"The clone had the voice and the KYC. It never had Rahul's phone."*

## Scene 2: the real Rahul makes the same request (1 min)

1. Reshaan calls from Phone C with **Rahul's registered number** and his own voice.
2. Answer, identify, same request. The card stays **GREEN**.
3. **Standard checks → Passed**, **Send app approval**. Phone A: **Yes, approve with passkey**, then fingerprint.
4. **Make the change** turns blue. Click it. Done in about 40 seconds, with no voice test.

Line: *"Genuine customers get one tap on their own phone. That's the whole cost."*

## Scene 3: Sunita and the WhatsApp call (1.5 min)

1. `/demo`: **Set "Sunita was on a call 2 min ago"**.
2. Phone B: **Pay by UPI** → `quickhelp.relief@okaxis` → ₹50000 → **Pay**.
3. The pause screen appears: "We've paused this ₹50,000 payment for a moment". Read out the reasons.
4. Optional: **Check a voice note**, then pick the clone voice note (V01). The result says "strong signs of a computer-made voice".
5. **Ask Rahul on his phone**. Phone A shows "Did you ask Mum for ₹50,000?". Reshaan taps **No, I didn't ask**.
6. Phone B: **Payment cancelled**, with a pre-filled 1930 report and a **Call 1930** button. The fraud desk gets the case.

Line: *"Sunita trusts Rahul more than any warning. So the check goes to Rahul."*

## Scene 4: the numbers (1 min)

Open `/metrics`. Walk the target table top to bottom, then scroll to **Every miss**. Say which misses still didn't get through (app approval blocked them) and why.

Then `/demo` → **What Countersign holds right now**: 0 voiceprints, 0 transcripts, audio only for the RED case, encrypted.

## Likely judge questions

- *"What if the attacker SIM-swaps?"* → `/demo` **Simulate SIM swap**, then try to bind a new phone on `/bank/rahul`. Enrolment is refused for 7 days, and calls show `SIM_SWAP_RECENT`.
- *"What if the detector is wrong?"* → It only changes how much checking happens. Risky changes always need the passkey, even on GREEN.
- *"Speech impairment?"* → In the request card: **Customer declines voice check** swaps liveness for app approval and never fails anyone.
- *"Is the detector any good on phone audio?"* → `/metrics` benchmark table across G.711 / AMR-NB / Opus, compared with the published numbers.
