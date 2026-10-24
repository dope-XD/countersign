plugins {
    id("com.android.application") version "9.3.3" apply false
    // AGP 9 compiles Kotlin itself (built-in Kotlin 2.2.10); the Compose compiler plugin must match that version.
    id("org.jetbrains.kotlin.plugin.compose") version "2.2.10" apply false
}
