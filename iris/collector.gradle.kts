
dependencies {
    implementation(enforcedPlatform("io.netty:netty-bom:4.1.138.Final"))
    implementation(files("libs/sqlcipher.aar"))
    implementation("androidx.sqlite:sqlite:2.4.0")
    testImplementation("junit:junit:4.13.2")
}
