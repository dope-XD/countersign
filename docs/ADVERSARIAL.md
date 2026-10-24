# Adversarial robustness: how an attacker gets past Countersign, and what we'd change

Each row is tested in `data/listener/adversarial.jsonl` (30 calls written by us, test only), as text and spoken
(TTS through a G.711 phone line, `models/eval/asr_percall_conv.json`), and reported in `docs/RESULTS.md`.

## Against what is said: the conversation check (what decides once the model pack is installed)

| Attack | Our test calls | Text / spoken (scam calls should reach amber) | Old keyword path, spoken | What we'd change |
|---|---|---|---|---|
| Misspelling, recognition errors | `misspell_digital_arrest`, `misspell_otp` | amber / watch; none / amber | red, red | typo augmentation already in training (30% of rows); add our call style to training |
| Paraphrase, polite tone | `para_digital_arrest_soft`, `para_kyc_polite`, `para_investment_friendly`, `para_family_emergency`, `para_job_task` | 2 of 5 at amber as text, 2 of 5 spoken | 5 of 5 at amber or red | **the weak spot:** more paraphrased Indian scam scripts in training, written by people outside the team |
| Negation abuse ("I'm *not* asking for your OTP… just move the money") | `negation_abuse_no_money`, `negation_abuse_safe_account` | amber / amber; watch / watch | amber, amber | the model reads the request, not the word; the second call needs more training examples |
| No tell-tale words | `no_cue_words_scam` | watch / none | amber | a "money to a third party" move with its own training data |
| Slow burn (small talk first) | `slowburn_courier`, `slowburn_hi_reward`, `slowburn_trai` | 1 of 3 at amber as text, 3 of 3 spoken | 2 of 3 | the window keeps the newest ~1,200 characters, so the small talk falls out once the ask comes |
| Transliteration, script mixing | `translit_hi_to_latin_arrest`, `translit_latin_to_hi_kyc`, `translit_mixed_script` | 2 of 3 as text, 3 of 3 spoken (one red) | 3 of 3 | each script is now kept as it is (e5 reads Devanagari natively) |
| Talk about scams, to dodge or by accident | `relatives_discuss_digital_arrest`, `_hi`, `_otp` (harmless) | one reaches amber as text and **red** spoken; two stay at watch | watch | harmless calls "about" scams need to be in training as negatives; until then "It's not a scam" clears it in one tap |
| Mimic a genuine call | the 11 genuine calls (bank fraud check, police verification, delivery OTP, …) | all at none, as text and spoken (one watch) | 8 of 11 at watch or amber | — this is what the conversation check fixed |

**What it misses today, plainly:** scams told in a plain, scripted English or a polite paraphrase (it is weaker here
than the keyword path it replaced: 62% vs 88% of our spoken scam calls reach amber), scams with no request in the
words heard so far, and talk *about* scams that sounds like one. An attacker who knows this would keep the call
formal and polite, never say "OTP" or "arrest" outright, and move the ask late. The context signals (caller check,
a remote-control app opening) and the user's own "Alert family" still work against that.

## Against what is said: basic mode (cue scorer + our small classifier, before the model pack is installed)

| Attack | Example | What happens now | What we'd change |
|---|---|---|---|
| Paraphrase, polite tone | "investigation wing… keep this confidential… refundable security amount" | caught at amber by the classifier even when few cue words match | more paraphrased Indian scam scripts in training |
| Misspelling / recognition errors | "inspecter… mumbay polise… arest warent" | caught: fuzzy cue matching (1–2 edits) and character n-grams | — |
| Transliteration and script mixing | "pulis", Devanagari for English words, mixed scripts | caught: Devanagari is folded to Latin for the classifier; cue phrases in both scripts | the same fold in the cue scorer |
| Negation abuse | "I'm **not** asking for your OTP… just move the money to the RBI account" | caught at amber; red is weaker because negated cues don't count | count a negated "OTP" *plus* a money request as suspicious |
| Talk about scams to dodge red | wrapping the ask in "you've seen the news about fake police…" | "discussion" blocks red from cue words and from the classifier, by design | the context signals (remote app, caller check) still reach red |
| No cue words at all | "you overpaid my deposit, return the extra to my brother" | amber only through the classifier; no red | a "money to a third party" request detector |
| Slow burn | 2 minutes of small talk first | the classifier says nothing for ~25 words; one of three slow-burn calls stays below amber | a rolling window as well as the whole call |
| Mimic a genuine call | a real bank's fraud-alert wording | the hard case: genuine calls also reach amber, one of our 12 reaches red | one-tap "I know this caller"; the bank's own verified-caller signal as context |

## Against the voice check

| Attack | What happens now | What we'd change |
|---|---|---|
| A clone played through a speaker into the phone | the error rate rises sharply over the air (RESULTS.md) | the voice check can only raise amber, never red, so a miss costs little and a false flag can't block anyone |
| A real human scammer (most Indian scams today) | the voice check says "real" | the words and the caller check do the work |
| Voice conversion of a family member | the voice check may miss it | the caller check: the claimed member's own phone is asked; a cloned voice can't answer from Rahul's phone |

## Against the caller check and the phone

| Attack | What happens now | What we'd change |
|---|---|---|
| Spoofed caller ID showing Rahul's number | "Not Rahul's phone" + "Caller ID may be faked": Rahul's phone isn't calling | — |
| Calling from an unknown number | the "Says they're family? Check" chip; unknown number is context | — |
| Asking the victim to turn speaker off | the card asks for speaker; without it, only context and the caller check protect | earpiece capture where the phone allows it (#37) |
| Asking the victim to install AnyDesk | `remote_app_opened` is strong context: with any cue warn it reaches red | — |
| Killing the app or the network | the alarm falls back to SMS from the victim's own SIM | — |
| Flooding false alarms to make the family ignore them | one alarm per call; "Not a scam" clears it in one tap | rate-limit alarms per caller number |

## What basic mode misses today, plainly

Scams with no cue words that the classifier hasn't seen, slow burns cut short, scammers who keep the user off speaker,
and phones whose echo cancellation removes the caller's voice from the mic. Those are the named failure cases in
`docs/RESULTS.md`.
