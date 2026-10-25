# Countersign: the 5 minute demo

Okay, so this is the whole demo on a few pages. Print it, give the judge the grey boxes, keep the rest for us.

Every line here is tested. We had a voice say it, sent it down a fake phone line, let the phone's own speech model write it down, and checked what the app does with it. Run `python -m ml.eval.demo_rehearsal` and it does all that again in a few minutes. The calls are the kind people actually report to 1930 every day, and they're written the way people really talk, not like a textbook.

## Who's who

| Who | Which phone | App? |
|---|---|---|
| **Mummy** | the vivo | yes: signed up, scam check downloaded, Rahul added as family |
| **Rahul** | the other Android | yes: linked to Mummy |
| **The scammer** (the judge reads the lines) | **any other phone**: yours, a teammate's, the judge's own. iPhone also fine | no |

Just don't call from Rahul's phone. The app would see that Rahul really is on the call, and the whole trick in scene 1 falls flat.

## 10 minutes before

1. Plug both phones in and run `.\tools\preflight.ps1`. Wait till it's all green.
2. Both phones: volume full, Do Not Disturb off, screen timeout 5 min, battery above 50%.
3. Mummy's phone has GPay or PhonePe (for the pay guard) and internet.
4. Open https://countersign-relay.onrender.com/health once in a browser, it wakes the server up. Should say `"ok": true`.
5. The scammer's number should NOT be saved in Mummy's contacts.
6. Copy the AI voice clip for scene 3: `adb push data/kit/voice_ai_01.wav /sdcard/Download/`
7. Don't force-stop or reinstall the app after this. On the vivo it switches the Call listener off. If you had to, run the pre-flight again.

---

## Scene 1: "Aunty, Rahul ka accident ho gaya" (2.5 min)

**What's going on:** some guy calls Mummy from a new number, says he's Rahul's friend, Rahul's had an accident, hospital wants money right now. Super common one.

Scammer's phone calls Mummy. Mummy picks up.

> **Judge (line 1):**
> Hello? Haan aunty namaste... main Amit bol raha hoon, Rahul ka dost. College wala, pehchana?

**You'll see:** Mummy's screen shows "Says they're family? **Check**". Mummy taps it, then taps **Rahul**.
Rahul's phone pops up: "Is it you on Mummy's call?". Rahul taps **No**.
Mummy's card goes ✗ **"Not Rahul's phone"**.

Now Mummy puts the call **on speaker**.

> **Judge (line 2):**
> Aunty ek problem ho gayi hai... Rahul ka bike se accident ho gaya, hum log abhi hospital mein hain.
>
> **(line 3):**
> Nahi nahi aunty, ghabraiye mat, woh theek hai. Bas sir pe chot lagi hai, par doctor bol rahe hain abhi operation karna padega.
>
> **(line 4):**
> Hospital wale pachaas hazaar advance maang rahe hain. Rahul ka phone toot gaya na, isliye main call kar raha hoon.
>
> **(line 5):**
> Aap na abhi isi number pe GPay kar do. Aur uncle ko abhi mat batana please, woh tension le lenge.
>
> **(line 6):**
> Aunty jaldi karo please... koi OTP aaye toh mujhe bata dena, main counter pe hi khada hoon.

**You'll see:**

- The card is already **yellow** from Rahul's "No" ("not your family's phone"). On speaker it also says "Listening for scams".
- As he keeps talking, more reasons show up ("a family emergency", "asks for money").
- By line 5 at the latest it goes **red**: "This is likely a scam. Hang up."
- Same moment, **Rahul's phone rings full screen**, even on silent: "Mummy may be on a scam call" with **Call Mummy**.

Then Mummy opens **GPay**. A red screen comes on top: "Stop. Don't send money or share an OTP."

**What we say:** "See, two different things agreed before it went red. What the caller said, and Rahul's own phone saying it's not him. You can clone a voice. You can't clone Rahul's phone."

**If the card isn't moving by line 3:** the phone probably can't hear the caller (see the table at the end). Just tap **Alert family** on the card, so Rahul's alarm and the pay guard still happen live, and do these same lines in scene 3.

---

## Scene 2: a real delivery guy, nothing happens (45 sec)

Cut the call. Same phone calls Mummy again, on speaker.

> **Judge (as the delivery guy):**
> Haan madam, Amazon se... aapka parcel aaya hai.
> Main neeche gate pe khada hoon. Aap aa rahe ho ya guard ko de doon?
> Achha theek hai. Ek OTP aaya hoga delivery wala, woh bata do bas.
> Haan ho gaya madam, guard bhaiya ke paas rakh diya. Thank you!

**You'll see:** nothing. No card, no alarm, nothing.

**What we say:** "He also asked for an OTP. But it's the delivery code for a parcel she ordered, that's normal. It doesn't just jump on words."

**If something does pop up:** tap **I know this caller**. Rahul gets "False alarm: Mummy says it's fine". One tap, and the family knows.

---

## Scene 3: try your own message, no internet (1 min)

Mummy's phone: turn **Airplane mode ON**. Open the app, go to **Check a recording or message**.

> **Judge:** type anything you want. Some SMS you got, something your relative forwarded, or just make one up.

Nothing in mind? Use this one:

> Madam main CBI officer bol raha hoon. Aapke naam pe money laundering ka case hai, arrest warrant nikla hai. Video call pe rahiye, kisi ko mat batana. Apne saare paise RBI ke safe account mein transfer kariye, verification ke baad wapas mil jayenge.

(goes red) and then a normal one:

> Hello madam, Amazon delivery here. I am at your gate with your parcel, please come down.

(stays calm)

**You'll see:** the answer, what kind of scam, and why. Airplane mode is on the whole time, so nothing left the phone.

Got 20 more seconds? Pick `voice_ai_01.wav` from Downloads. It shows how likely the voice is AI-made. **What we say:** "This is only one clue for us. It can make the card yellow, never red by itself, because a cloned voice played into a phone is honestly hard to catch. What actually beats a cloned Rahul is scene 1: just ask Rahul's phone."

---

## Scene 4: wrap up (30 sec)

"Everything you just saw ran on this phone. The speech-to-text, the scam check, the decision. The family only got a short alert with the type of scam, not what was said." Want proof? On the laptop, `adb logcat -s CallRisk ScamAlert` shows just levels, types and ids, no words.

---

## Extra scripts (if the judge wants English or Hindi)

**English: the FedEx parcel that turns into "digital arrest".** Goes red by line 5. Tested.

> Hello, am I speaking to Mrs Sharma? Ma'am I'm calling from FedEx, your parcel to Taiwan is held at Mumbai customs.
> Ma'am it has five passports and some MD drugs inside. I'm connecting you to Mumbai cyber crime, please hold.
> Hello ma'am, Sub Inspector Vikram this side. There's an FIR on your Aadhaar, money laundering case, arrest warrant is there. You have to come on Skype video call right now.
> Don't cut the call, and don't tell anybody, not even your husband. This is a confidential investigation.
> To clear your name you have to transfer your funds to the RBI verification account. It'll be refunded in 24 hours.
> Ma'am please do it now, otherwise local police will come to your house tonight only.

**Hindi: "aapka beta pakda gaya hai".** Goes red by line 4. Tested.

> हेलो, आप राहुल की मम्मी बोल रही हैं? मैं थाने से इंस्पेक्टर यादव बोल रहा हूँ।
> आपका बेटा एक केस में पकड़ा गया है, लड़की वाले FIR करवाने पर अड़े हैं।
> देखिए, मामला अभी यहीं निपट सकता है, वरना कल कोर्ट जाएगा और उसकी जिंदगी खराब हो जाएगी।
> आप अभी पचास हज़ार इस नंबर पर ट्रांसफर कर दीजिए, और किसी को कुछ मत बताइए।
> जल्दी कीजिए मैडम, आधे घंटे में फाइल ऊपर चली जाएगी।

---

## If something goes wrong

| What happened | Probably why | Do this |
|---|---|---|
| No "Listening for scams" on speaker | Call listener got switched off, or the scam check isn't downloaded | Settings → Accessibility → Countersign → On. The pre-flight catches both |
| "Listening" is there but no yellow card | the phone's echo cancelling removed the caller's voice | Tap **Alert family** (alarm + pay guard still live), then show the lines in scene 3. Just say what happened, it's fine |
| Rahul's phone doesn't ring | server was sleeping, or Rahul's app got closed | An SMS still reaches Rahul in a minute. Open `/health` before starting |
| No "Says they're family? Check" | the number is saved in contacts, or the call came from Rahul's phone | Call from an unknown number |
| Judge reads really slow or really fast | doesn't matter | It looks at the whole call so far, not the timing |
| Judge goes off script | that's okay | Most real scam lines still set it off. If it stays quiet, be honest: it waits till someone asks for money, an OTP, an app, or secrecy |

## Practice

Do three full runs before the judges come, with the printed pages. After each one check: yellow by line 4? red by line 5? Rahul's phone rang? pay guard showed? If a run goes wrong, fix it before the next one. Don't just hope it works on stage.
