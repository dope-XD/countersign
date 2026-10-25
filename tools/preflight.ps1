# Pre-flight for the demo (docs/DEMO_SCRIPT.md): every connected phone, read-only, green or red per line.
#   .\tools\preflight.ps1
# Needs adb (Android SDK platform-tools) and the phones plugged in with USB debugging on.
$ErrorActionPreference = "Continue"
$adb = (Get-Command adb -ErrorAction SilentlyContinue).Source
if (-not $adb) { $adb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe" }
$pkg = "app.countersign.bank"
$bad = 0

function Line($ok, $what, $fix) {
    if ($ok) { Write-Host "  [ok]  $what" -ForegroundColor Green }
    else { Write-Host "  [!!]  $what  ->  $fix" -ForegroundColor Red; $script:bad++ }
}

Write-Host "Server" -ForegroundColor Cyan
try {
    $h = Invoke-RestMethod -Uri "https://countersign-relay.onrender.com/health" -TimeoutSec 90
    Line ($h.ok -and $h.db -eq "postgres") "relay up, database connected" "open /health again in a minute; check Supabase"
} catch { Line $false "relay reachable" "it may be waking up: try again in a minute" }

$devices = & $adb devices | Select-String "\tdevice$" | ForEach-Object { ($_ -split "\t")[0] }
if (-not $devices) { Write-Host "No phone connected (USB debugging on?)" -ForegroundColor Red; exit 1 }

foreach ($d in $devices) {
    $model = (& $adb -s $d shell getprop ro.product.model).Trim()
    Write-Host "`n$model ($d)" -ForegroundColor Cyan
    $info = & $adb -s $d shell dumpsys package $pkg
    $installed = [bool]($info | Select-String "versionName")
    Line $installed "app installed" "adb -s $d install -r android/app/build/outputs/apk/debug/app-debug.apk"
    if (-not $installed) { continue }
    $updated = ($info | Select-String "lastUpdateTime" | Select-Object -First 1).ToString().Trim()
    Write-Host "        $updated"

    $pack = & $adb -s $d shell run-as $pkg cat files/models/pack.json 2>$null
    Line ([bool]($pack | Select-String '"conv"')) "scam check downloaded (pack v2, with the conversation model)" "app Settings -> Download the scam check, on Wi-Fi"

    $acc = & $adb -s $d shell settings get secure enabled_accessibility_services
    Line ([bool]($acc | Select-String $pkg)) "Call listener on (Accessibility)" "Settings -> Accessibility -> Countersign -> On"

    foreach ($p in "RECORD_AUDIO", "READ_PHONE_STATE", "POST_NOTIFICATIONS", "SEND_SMS", "CALL_PHONE") {
        $g = [bool]($info | Select-String "android.permission.$($p): granted=true")
        Line $g "permission $p" "finish the setup cards in the app"
    }
    $overlay = & $adb -s $d shell appops get $pkg SYSTEM_ALERT_WINDOW
    Line ([bool]($overlay | Select-String "allow")) "may draw over other apps (call card, pay guard)" "setup card 'Show over other apps'"

    $zen = (& $adb -s $d shell settings get global zen_mode).Trim()
    Line ($zen -eq "0") "Do Not Disturb off" "turn Do Not Disturb off"
    $idle = & $adb -s $d shell dumpsys deviceidle whitelist
    Line ([bool]($idle | Select-String $pkg)) "battery optimisation off for the app" "setup card 'Battery' or Settings -> Battery -> Countersign -> No restrictions"
    $m = & $adb -s $d shell dumpsys battery | Select-String "^\s*level:\s*(\d+)" | Select-Object -First 1
    $level = if ($m) { [int]$m.Matches[0].Groups[1].Value } else { -1 }
    Line ($level -ge 50) "battery $level%" "charge it"
}

if ($bad) { Write-Host "`n$bad thing(s) to fix before the demo." -ForegroundColor Red; exit 1 }
Write-Host "`nAll green. Go." -ForegroundColor Green
