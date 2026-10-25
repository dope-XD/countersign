# The demo, script by script (5 minutes)

Every line here has been rehearsed through the phone's own pipeline: spoken by a voice, sent down a phone line, turned into text by the phone's speech model, and judged. `python -m ml.eval.demo_rehearsal` checks them all again in a few minutes (text, clean audio, G.711, over the air + G.711). The scripts are real scam patterns that get reported to 1930 every day, written the way people actually talk.

## Who is who

| Who | Phone | Needs the app? |
|---|---|---|
| **Mummy** | the vivo | yes, signed up, scam check downloaded, Rahul linked as family |
| **Rahul** | the second Android | yes, linked to Mummy |
| **The scammer** (a judge reads the card) | **any other phone**: a teammate's or the judge's own, iPhone is fine | no |

The scammer must not call from Rahul's phone. The app would see that Rahul really is on the call, and the trick in scene 1 would not work.

## Before the judges arrive (10 minutes)

1. Run `.\tools\preflight.ps1` with both phones plugged in. Everything must be green.
2. Both phones: volume up, Do Not Disturb **off**, screen timeout 5 minutes, battery above 50%.
3. Mummy's phone: GPay or PhonePe installed (for the pay guard), Wi-Fi or mobile data on.
4. Open https://countersign-relay.onrender.com/health in a browser (wakes the server). It should say `"ok": true`.
5. Save the scammer's number in nobody's contacts. It must be an unknown number to Mummy.
6. Copy the voice-clone clip to Mummy's phone for scene 3: `adb push data/kit/voice_ai_01.wav /sdcard/Download/`.
7. Print this page. Give the judge only the **grey boxes**.

---

## Scene 1: "Rahul's friend" (2.5 minutes)

**The story:** a stranger calls, says he's Rahul's friend, Rahul had an accident, the hospital wants money now. It's one of the most common calls the cyber police get.

The scammer's phone calls Mummy. Mummy answers.

> **Judge, line 1:**
> Hello? Haan aunty namaste, main Amit bol raha hoon, Rahul ka dost, college wala.

**What you'll see:** on Mummy's screen, "Says they're family? **Check**". Mummy taps it, then taps **Rahul**.
On Rahul's phone: "Is it you on Mummy's call?" Rahul taps **No**.
Mummy's card: ✗ **"Not Rahul's phone"**.

Mummy taps **Speaker** on the call.

> **Judge, line 2:**
> Aunty ek problem ho gayi hai, Rahul ka bike se accident ho gaya, hum log abhi hospital mein hain.
>
> **Line 3:**
> Nahi nahi ghabraiye mat, woh theek hai, bas sir pe chot hai, par doctor bol rahe hain abhi operation karna padega.
>
> **Line 4:**
> Hospital wale pachaas hazaar advance maang rahe hain, Rahul ka phone toot gaya isliye main call kar raha hoon.
>
> **Line 5:**
> Aap na abhi isi number pe GPay kar do, aur uncle ko abhi mat batana, woh tension le lenge.
>
> **Line 6:**
> Aunty jaldi please, koi OTP aaye to mujhe bata dena, main counter pe khada hoon.

**What you'll see:**
- "Listening for scams", then the **amber** card with the reason ("a family emergency", "asks for money").
- By line 5, **red**: "This is likely a scam. Hang up."
- At the same moment **Rahul's phone rings full screen**, even on silent: "Mummy may be on a scam call", with **Call Mummy**.

Then Mummy opens **GPay**: a red screen covers it, "Stop. Don't send money or share an OTP."

**What to say:** "Two things agreed before it went red: what was said on the call, and Rahul's own phone saying it's not him. A voice can be cloned. Rahul's phone can't be."

**If the card doesn't move after line 3** (the phone didn't hear the caller, see "Things that can go wrong"): tap **Alert family** on the card. Rahul's alarm and the pay guard still show live. Then do the same lines through scene 3.

---

## Scene 2: a real delivery call stays quiet (45 seconds)

Hang up. The same scammer phone calls Mummy again, on speaker.

> **Judge, delivery agent:**
> Haan madam, Amazon se bol raha hoon, aapka parcel aaya hai.
> Main neeche gate pe hoon, aap aa rahe ho ya guard ko de doon?
> Achha theek hai, ek delivery wala OTP aaya hoga aapke phone pe, woh bata do bas.
> Haan ho gaya madam, guard ke paas rakh diya hai, thank you.

**What you'll see:** nothing. No card, no alarm.

**What to say:** "He asked for an OTP too. But a delivery code for a parcel she ordered isn't a scam, and the phone knows the difference. It doesn't fire on single words."

**If something does show:** tap **I know this caller**. Rahul's phone gets "False alarm: Mummy says it's fine". One tap fixes a mistake, and the family is told.

---

## Scene 3: your own message, with no internet (1 minute)

On Mummy's phone, turn **Airplane mode ON**. Open the app → **Check a recording or message**.

> **Judge:** type or paste any message you like. A real SMS from your phone, or something you make up.

If the judge has nothing, use one of these:

> Madam main CBI officer bol raha hoon. Aapke naam pe money laundering ka case hai, arrest warrant nikla hai. Video call pe rahiye, kisi ko mat batana. Apne saare paise RBI ke safe account mein transfer kariye, verification ke baad wapas mil jayenge.

(red), then a harmless one:

> Hello madam, Amazon delivery here. I am at your gate with your parcel, please come down.

(stays calm).

**What you'll see:** the verdict, the scam type, and why, with **no internet**. Nothing was sent anywhere.

Optional, 20 seconds: pick `voice_ai_01.wav` (in the phone's Downloads, copied before) → the voice-clone score. **What to say:** "The voice check is one clue only. It can make the card amber, never red, because cloned voices played into a phone are hard to catch. What beats a cloned Rahul is scene 1: asking Rahul's own phone."

---

## Scene 4: close (30 seconds)

"Everything you saw ran on this phone: the speech-to-text, the scam check, the decision. The family got a short alert with the scam type, not the words. If you want proof, here's the phone's log." (Optional: `adb logcat -s CallRisk ScamAlert` on the laptop shows only levels, types and ids.)

---

## Spare scripts (if a judge wants English or Hindi)

**English, the FedEx parcel that turns into a "digital arrest".** Red by line 5. Rehearsed.

> Hello, am I speaking with Mrs Sharma? Ma'am this is FedEx, your parcel to Taiwan has been stopped at Mumbai customs.
> It has five passports and some MD drugs inside, so I'm connecting you to Mumbai cyber crime police.
> Ma'am, Sub Inspector Vikram here. There's an FIR on your Aadhaar, money laundering case, there is an arrest warrant. You have to join a Skype video call right now.
> Don't disconnect and don't tell anybody, not even your husband, this is a confidential investigation.
> To clear your name you have to transfer your funds to the RBI verification account, it'll be refunded in 24 hours.
> Ma'am do it now, otherwise the local police will come to your house tonight.

**Hindi, "your son has been caught".** Red by line 4. Rehearsed.

> हेलो, आप राहुल की मम्मी बोल रही हैं? मैं थाने से इंस्पेक्टर यादव बोल रहा हूँ।
> आपका बेटा एक केस में पकड़ा गया है, लड़की वाले FIR करवाने पर अड़े हैं।
> देखिए, मामला अभी यहीं निपट सकता है, वरना कल कोर्ट जाएगा और उसकी जिंदगी खराब हो जाएगी।
> आप अभी पचास हज़ार इस नंबर पर ट्रांसफर कर दीजिए, और किसी को कुछ मत बताइए।
> जल्दी कीजिए मैडम, आधे घंटे में फाइल ऊपर चली जाएगी।

---

## Things that can go wrong, and what to do

| What happens | Why | Do this |
|---|---|---|
| No "Listening for scams" on speaker | the Call listener (Accessibility) got turned off, or the scam check isn't downloaded | Settings → Accessibility → Countersign on. `preflight.ps1` catches both |
| "Listening" shows but the card never goes amber | the phone's echo cancelling removed the caller's voice from the mic | Tap **Alert family** to show the alarm and pay guard live, then show the same lines in scene 3 ("Check a message"). Say plainly what happened |
| Rahul's phone doesn't ring | the server was asleep, or Rahul's app was closed | Rahul gets an SMS instead within a minute. Open `/health` before the demo |
| "Says they're family? Check" doesn't appear | the scammer's number is saved as a contact, or the call came from Rahul's phone | Call from an unknown number |
| The judge speaks much slower or faster | fine | The check judges the whole call so far, not timing |
| A judge goes off script | fine | Most real scam lines still trip it. If it stays quiet, say honestly that it waits for an ask (money, OTP, app, secrecy) before warning |

## Rehearse

Three full runs before the judges, with the printed page. After each, note: did amber come by line 4, red by line 5, Rahul's ring, the pay guard. If any run misses, fix it before the next one, don't hope.
