plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

// The server the app talks to by default (the dev server in docs/agents/CONTRACT.md); the sign-up screen can change it.
val defaultServer = (findProperty("countersign.server") as String?) ?: "https://pseudoskeletal-yung-implausibly.ngrok-free.dev"
// -Pcountersign.fake=true: scripted data (FakeRepository) instead of the server.
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
    buildFeatures {
        buildConfig = true
        compose = true
    }
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
    implementation("androidx.compose.material:material-icons-core:1.7.8")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.biometric:biometric:1.1.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.zxing:core:3.5.4") // draws the family invite QR code
    implementation("com.google.android.gms:play-services-code-scanner:16.1.0") // scans it, without a camera permission

    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
}
