plugins {
    id("com.android.application")
}

// The bank server the app opens by default; the setup screen can change it.
val defaultServer = (findProperty("countersign.server") as String?) ?: "https://countersign-demo.ngrok-free.app"

android {
    namespace = "app.countersign.bank"
    compileSdk = 36

    defaultConfig {
        applicationId = "app.countersign.bank"
        minSdk = 31 // TelephonyCallback and AudioManager mode listeners
        targetSdk = 36
        versionCode = 1
        versionName = "0.1"
        buildConfigField("String", "DEFAULT_SERVER", "\"$defaultServer\"")
    }

    // One demo signing key in the repo, so every teammate's build has the same certificate
    // fingerprint and the engine's assetlinks.json (COUNTERSIGN_ANDROID_CERT_SHA256) matches it.
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
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("demo")
        }
    }
    buildFeatures { buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("com.google.androidbrowserhelper:androidbrowserhelper:2.7.4")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
}
