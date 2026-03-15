import Foundation
import HealthKit
import HealthBridgeLib

// Top-level async entry point for the CLI executable.

let args = CommandLine.arguments

guard args.count >= 2 else {
    printUsage()
    exit(2)
}

let command = args[1]

switch command {
case "write-chunk":
    guard args.count == 3 else {
        fputs("Error: write-chunk requires a JSON file path\n", stderr)
        exit(2)
    }
    await handleWriteChunk(jsonPath: args[2])

case "write-workout":
    guard args.count == 3 else {
        fputs("Error: write-workout requires a JSON file path\n", stderr)
        exit(2)
    }
    await handleWriteWorkout(jsonPath: args[2])

case "--help", "-h":
    printUsage()
    exit(0)

case "--version", "-v":
    print("openwalk-health-bridge 1.0.0")
    exit(0)

default:
    fputs("Error: Unknown command '\(command)'\n", stderr)
    printUsage()
    exit(2)
}

func handleWriteChunk(jsonPath: String) async {
    do {
        let chunk = try loadChunkJSON(from: jsonPath)
        let bridge = HealthBridge()
        try await bridge.requestAuthorization()
        let result = try await ChunkWriter.writeChunk(bridge: bridge, data: chunk)
        print(result.toJSON())
        exit(0)
    } catch let error as BridgeError {
        fputs("\(error.description)\n", stderr)
        exit(error.exitCode)
    } catch {
        fputs("Error: \(error.localizedDescription)\n", stderr)
        exit(3)
    }
}

func handleWriteWorkout(jsonPath: String) async {
    do {
        let workout = try loadWorkoutJSON(from: jsonPath)
        let bridge = HealthBridge()
        try await bridge.requestAuthorization()
        let result = try await WorkoutWriter.writeWorkout(bridge: bridge, data: workout)
        print(result.toJSON())
        exit(0)
    } catch let error as BridgeError {
        fputs("\(error.description)\n", stderr)
        exit(error.exitCode)
    } catch {
        fputs("Error: \(error.localizedDescription)\n", stderr)
        exit(3)
    }
}

func printUsage() {
    print("""
    OpenWalk HealthKit Bridge

    Usage:
      openwalk-health-bridge <command> <json-file-path>

    Commands:
      write-chunk   Write incremental chunk data (steps, distance, calories)
      write-workout Write session summary workout record

    Options:
      --help, -h    Show this help message
      --version, -v Show version number

    Exit Codes:
      0  Success
      1  Authorization error
      2  Data validation error
      3  Write failure
    """)
}
