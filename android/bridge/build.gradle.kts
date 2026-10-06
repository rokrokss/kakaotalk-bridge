plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}
android {
    namespace = "dev.kakaotalkbridge.android"
    compileSdk = 35
    defaultConfig {
        // Kept from the first release: Android stores the enabled keyboard by application ID.
        applicationId = "dev.kakaocollector.bridge"
        minSdk = 30
        targetSdk = 35
        versionCode = 2
        versionName = "0.2.0"
    }
    signingConfigs {
        create("release") {
            val keyPath = System.getenv("BRIDGE_KEYSTORE")
            if (keyPath != null) {
                storeFile = file(keyPath)
                val password = file(System.getenv("BRIDGE_KEY_PASSWORD_FILE")).readText().trim()
                storePassword = password
                keyPassword = password
                keyAlias = "bridge"
            }
        }
    }
    buildTypes { getByName("release") { signingConfig = signingConfigs.getByName("release") } }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
}
