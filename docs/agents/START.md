# Starting each laptop

Do this once per laptop. It takes about 20 minutes, mostly downloads.

## 1. Tools (B on the Mac, C on Windows #2)

- **Git and GitHub CLI.**
  - Mac: `brew install git gh`
  - Windows: `winget install Git.Git GitHub.cli`
  - Then `gh auth login` (GitHub.com, HTTPS, log in with a browser). Use your own GitHub account (`Reshaan-Nadar` or `slayrah444` are already collaborators), or the team's.
- **JDK 17+ and the Android SDK.** Install Android Studio: it brings a JDK and the SDK Manager. Then:
  - SDK Platform 36 and Build-Tools 36;
  - for C, also an emulator image (API 34+ with Google Play), plus `adb` on the PATH.
- **Claude desktop app** (or the `claude` CLI). Sign in with that laptop's Claude account.

## 2. Code

```bash
gh repo clone dope-XD/countersign
cd countersign
git config core.hooksPath .githooks
```

Make `android/local.properties`, which says where the SDK is (it's gitignored):

- Mac: `sdk.dir=/Users/<you>/Library/Android/sdk`
- Windows: `sdk.dir=C\:/Users/<you>/AppData/Local/Android/Sdk`

Check that it builds: `cd android && ./gradlew assembleDebug` (`.\gradlew assembleDebug` on Windows).

## 3. Start the agent

1. Open the Claude app's **Code** tab, choose the `countersign` folder, and start a new session.
2. Turn on **keep awake** in the app's settings. Keep the laptop plugged in with the lid open.
3. Paste the first message for your laptop:

   **Mac (B):**
   ```
   You are agent B (Android UI). Read CLAUDE.md, docs/agents/ui.md, docs/agents/PROTOCOL.md and docs/agents/CONTRACT.md. Then follow the protocol: comment on the Standup issue that B is online with your toolchain versions, and claim your first role:ui issue.
   ```

   **Windows #2 (C):**
   ```
   You are agent C (phone features and QA). Read CLAUDE.md, docs/agents/platform.md, docs/agents/PROTOCOL.md and docs/agents/CONTRACT.md. Then follow the protocol: comment on the Standup issue that C is online with your toolchain versions, and claim your first role:platform issue.
   ```

4. When it has replied, paste the `/loop 10m …` line for your role from `docs/agents/PROTOCOL.md`. From then on it checks GitHub every 10 minutes by itself.

## 4. The lead (A)

A runs on the GPU laptop and already has everything. It also runs the dev server (`RUNBOOK.md`) and its own `/loop`.

## Giving the agents new work

Tell **A** what you want, in plain words, on the GPU laptop. A splits it into issues for B and C (`CLAUDE.md`, "Agent A: turning the human's requests into work"), and their loops pick those up within 10 minutes.

You can still talk to B or C directly for anything that's only theirs, e.g. "B, make the shield bigger". If that creates new work, ask them to open an issue, so A sees it.
