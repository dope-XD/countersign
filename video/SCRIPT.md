# Countersign video: the voiceover

Read one scene per take, calmly, with a short pause before and after. Save each take as
`video/recorded/<scene>.m4a` (a phone voice memo is fine), then run `python video/tools/vo.py`.

## s01: The call

Mummy's phone rings. The man says he's from the CBI, and there's a parcel in her name with drugs in it.

## s02: The hour

He tells her to stay on the line and tell no one. Fifty-eight minutes later he asks her to move her savings, to clear her name. She does.

## s03: Our first try

Our first version listened for words like police and OTP. Then a real bank called, used the same words, and it went off. So we started again.

## s04: Countersign

This is Countersign. Everyone in the family installs it.

## s05: How it works

On speaker, her phone writes the call down by itself. A model we trained reads it as it goes and asks: is this caller doing what scammers do? Saying he's police. Telling her to keep quiet. The card turns amber and says why. If the caller claims to be Rahul, the app asks Rahul's phone. It says no.

## s06: Red

If it turns red, Rahul's phone rings full screen, or he gets an SMS if his app is off. If Mummy opens GPay, a red screen gets there first.

## s07: What we read

We read up before we built. Google and Samsung both run their scam checks on the phone. A 2026 study of eleven thousand real scam calls found small fine-tuned models scored 83, and chatbots at most 70. So we fine-tuned one on thirty-one thousand Indian bank calls. It runs on a six-gigabyte phone.

## s08: Measured

We tested it on calls it never trained on. Our old version flagged half the genuine calls. This one flags about two in a hundred. It catches 88 percent of the scams, a few fewer than before, and gets 28 of the 30 kit samples right.

## s09: Misses and mistakes

It isn't perfect. A scam read politely from a script in English can slip past it, and relatives talking about scams sometimes set it off. If it's wrong, two taps clear it and tell the family. Only suspicious calls reach our server, and the audio is dropped after the check. We keep one thing: a twenty-second encrypted clip of a confirmed scam, for thirty days.

## s10: End

Countersign. Catch the scam while it's still a call.
