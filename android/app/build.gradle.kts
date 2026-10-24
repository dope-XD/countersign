import java.net.URI
import java.security.MessageDigest

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

// The server the app talks to by default: the relay on Render (render.yaml); the sign-up screen can change it.
val defaultServer = (findProperty("countersign.server") as String?) ?: "https://countersign-relay.onrender.com"
// -Pcountersign.fake=true: scripted data (FakeRepository) instead of the server.

// On-phone speech-to-text and VAD: sherpa-onnx's Android AAR with onnxruntime linked in statically (so it can't clash
// with onnxruntime-android, which runs the voice-clone model). Fetched once from its GitHub release and checked.
val sherpaVersion = "1.13.8"
val sherpaSha256 = "b22c3fc1b6a45666d28892bb2f7694beeb77a8362d7ebd77c1a5431ec9435471"
val sherpaAar = file("libs/sherpa-onnx-static-link-onnxruntime-$sherpaVersion.aar")
if (!sherpaAar.exists()) {
    sherpaAar.parentFile.mkdirs()
    val url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/v$sherpaVersion/${sherpaAar.name}"
    logger.lifecycle("Downloading $url")
    val tmp = File(sherpaAar.path + ".part")
    URI(url).toURL().openStream().use { input -> tmp.outputStream().use { input.copyTo(it) } }
    val sha = MessageDigest.getInstance("SHA-256").digest(tmp.readBytes()).joinToString("") { "%02x".format(it) }
    check(sha == sherpaSha256) { "sherpa-onnx AAR checksum mismatch: $sha" }
    tmp.renameTo(sherpaAar)
}
val fake = (findProperty("countersign.fake") as String?)?.toBoolean() ?: false

android {
    namespace = "app.countersign.bank"
    compileSdk = 36

    defaultConfig {
        applicationId = "app.countersign.bank"
        minSdk = 31 // TelephonyCallback, audio mode listeners, BiometricPrompt with a key that takes fingerprint or screen lock
        targetSdk = 36
        versionCode = 2
        versionName = "1.0"
        buildConfigField("String", "DEFAULT_SERVER", "\"$defaultServer\"")
        buildConfigField("boolean", "FAKE", "$fake")
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        // phones (arm64) and the emulator (x86_64); keeps the APK small
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }

    // One demo signing key in the repo, so every teammate's build installs over the others'.
    // Demo only: a real app is signed with a key that never leaves the bank.
    signingConfigs {
        create("demo") {
            storeFile = file("countersign-demo.keystore")
            storePassword = "countersign"
            keyAlias = "demo"
            keyPassword = "countersign"
        }
    }
    buildTypes {
        debug { signingConfig = signingConfigs.getByName("demo") }
        release {
            // shrunk for judges downloading it over mobile data (about 5 MB instead of 50)
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
            signingConfig = signingConfigs.getByName("demo")
        }
    }
    // English and Hindi under Settings → Apps → Language (Android 13+), and Hindi in every install
    androidResources { generateLocaleConfig = true }
    bundle { language { enableSplit = false } }
    buildFeatures {
        buildConfig = true
        compose = true
    }
    // only the ABIs we ship (both onnxruntime copies carry a 32-bit x86 library, which would clash)
    packaging { jniLibs { excludes += listOf("lib/x86/**", "lib/armeabi-v7a/**") } }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2026.06.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling") // B's English / Hindi / large-font @Previews
    implementation("androidx.compose.material:material-icons-core:1.7.8")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.biometric:biometric:1.1.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.zxing:core:3.5.4") // draws the family invite QR code
    implementation("com.google.android.gms:play-services-code-scanner:16.1.0") // scans it, without a camera permission
    implementation(files(sherpaAar)) // speech-to-text + VAD, on the phone
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.22.0") // the voice-clone model, on the phone

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303") // real org.json for JVM tests (ScamScorerTest); Android supplies it on the phone
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
}
