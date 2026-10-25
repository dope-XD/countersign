# The voiceover for ElevenLabs

Made by `python video/tools/vo.py` from `video/script.json`; edit that file, not this one.

## Settings

- **Model:** Eleven v3 (or v4). It reads the `[tags]` as directions and handles Indian English and the
  pauses (`...`) well. These models ignore `<break>` tags, so the v3/v4 text below has none.
- **Voice:** one Indian English narrator for every scene: calm, warm, 30 to 45 years old. In the Voice
  Library, search "Indian English narration" and pick one that sounds like a person explaining to family,
  not an announcer.
- **Stability:** Natural. **Speed:** 1.0 (0.95 if it rushes). Keep the same voice and settings for all ten.
- **Pronunciation:** add `elevenlabs/pronunciation.pls` (Pronunciation dictionaries) so CBI, OTP, SMS and
  GPay are read as letters.
- **Output:** MP3 44.1 kHz 192 kbps, or WAV if your plan allows.

## How to generate

Best: **one generation per scene**. Paste each block below, generate, pick the best of 2 or 3 takes, and
download it as `s01.mp3` … `s10.mp3` (the same text is in `elevenlabs/s01.txt` …). Put the files in
`video/recorded/` and send them to me (or run `npm run build`).

Also fine: **one take of everything** with Multilingual v2: paste `elevenlabs/full_multilingual_v2.txt`
(it has `<break time="2.5s" />` between scenes), save it as `video/recorded/full.mp3`, and the build
cuts it into scenes at those pauses.

If a take says a tag out loud, regenerate it; if it keeps happening, delete the tag.

### s01: The call

```text
[quiet, serious, like telling a true story] Mummy's phone rings. The man says he's from the CBI, and there's a parcel in her name with drugs in it.
```

### s02: The hour

```text
[slow, heavy] He tells her to stay on the line and tell no one. Fifty-eight minutes later he asks her to move her savings, to clear her name. ... She does.
```

### s03: Our first try

```text
[plain, a little rueful] Our first version listened for words like police and OTP. Then a real bank called, used the same words, and it went off. ... So we started again.
```

### s04: Countersign

```text
[warm, brighter, a small smile] This is Countersign. Everyone in the family installs it.
```

### s05: How it works

```text
[clear, calm, explaining] On speaker, her phone writes the call down by itself. A model we trained reads it as it goes and asks: is this caller doing what scammers do? ... Saying he's police. Telling her to keep quiet. The card turns amber and says why. If the caller claims to be Rahul, the app asks Rahul's phone. ... It says no.
```

### s06: Red

```text
[urgent but steady] If it turns red, Rahul's phone rings full screen, or he gets an SMS if his app is off. If Mummy opens GPay, a red screen gets there first.
```

### s07: What we read

```text
[confident, conversational] We read up before we built. Google and Samsung both run their scam checks on the phone. A twenty twenty-six study of eleven thousand real scam calls found small fine-tuned models scored eighty-three, and chatbots at most seventy. So we fine-tuned one on thirty-one thousand Indian bank calls. It runs on a six-gigabyte phone.
```

### s08: Measured

```text
[measured, quietly proud] We tested it on calls it never trained on. Our old version flagged half the genuine calls. This one flags about two in a hundred. It catches eighty-eight percent of the scams, a few fewer than before, and gets twenty-eight of the thirty kit samples right.
```

### s09: Misses and mistakes

```text
[honest, plain] It isn't perfect. A scam read politely from a script in English can slip past it, and relatives talking about scams sometimes set it off. [reassuring] If it's wrong, two taps clear it and tell the family. Only suspicious calls reach our server, and the audio is dropped after the check. ... [firm] We keep one thing: a twenty-second encrypted clip of a confirmed scam, for thirty days.
```

### s10: End

```text
[warm, slow, final] Countersign. ... Catch the scam while it's still a call.
```
