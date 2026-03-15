// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "openwalk-health-bridge",
    platforms: [
        .macOS(.v14)
    ],
    targets: [
        .target(
            name: "HealthBridgeLib",
            path: "Sources/HealthBridgeLib"
        ),
        .executableTarget(
            name: "openwalk-health-bridge",
            dependencies: ["HealthBridgeLib"],
            path: "Sources/CLI"
        ),
        // Tests require full Xcode.app (Command Line Tools don't ship XCTest/Testing).
        // Uncomment when Xcode is installed:
        // .testTarget(
        //     name: "HealthBridgeTests",
        //     dependencies: ["HealthBridgeLib"],
        //     path: "Tests"
        // ),
    ]
)
