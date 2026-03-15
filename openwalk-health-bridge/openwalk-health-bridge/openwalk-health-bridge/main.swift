import Foundation
import HealthKit

// Synchronous entry point — only enters async when needed to avoid
// Swift's top-level async run loop preventing exit().

let args = CommandLine.arguments

guard args.count >= 2 else {
    printUsage()
    Foundation.exit(2)
}

let command = args[1]

switch command {
case "--help", "-h":
    printUsage()
    Foundation.exit(0)

case "--version", "-v":
    print("openwalk-health-bridge 1.0.0")
    Foundation.exit(0)

case "write-chunk":
    guard args.count == 3 else {
        fputs("Error: write-chunk requires a JSON file path\n", stderr)
        Foundation.exit(2)
    }
    runAsync { await handleWriteChunk(jsonPath: args[2]) }

case "write-workout":
    guard args.count == 3 else {
        fputs("Error: write-workout requires a JSON file path\n", stderr)
        Foundation.exit(2)
    }
    runAsync { await handleWriteWorkout(jsonPath: args[2]) }

default:
    fputs("Error: Unknown command '\(command)'\n", stderr)
    printUsage()
    Foundation.exit(2)
}

// Run an async block on the main run loop, then exit.
func runAsync(_ block: @escaping () async -> Void) -> Never {
    Task {
        await block()
    }
    RunLoop.main.run()
    Foundation.exit(0)  // unreachable, but satisfies Never
}

func handleWriteChunk(jsonPath: String) async {
    do {
        let chunk = try loadChunkJSON(from: jsonPath)
        let bridge = HealthBridge()
        try await bridge.requestAuthorization()
        let result = try await ChunkWriter.writeChunk(bridge: bridge, data: chunk)
        print(result.toJSON())
        Foundation.exit(0)
    } catch let error as BridgeError {
        fputs("\(error.description)\n", stderr)
        Foundation.exit(error.exitCode)
    } catch {
        fputs("Error: \(error.localizedDescription)\n", stderr)
        Foundation.exit(3)
    }
}

func handleWriteWorkout(jsonPath: String) async {
    do {
        let workout = try loadWorkoutJSON(from: jsonPath)
        let bridge = HealthBridge()
        try await bridge.requestAuthorization()
        let result = try await WorkoutWriter.writeWorkout(bridge: bridge, data: workout)
        print(result.toJSON())
        Foundation.exit(0)
    } catch let error as BridgeError {
        fputs("\(error.description)\n", stderr)
        Foundation.exit(error.exitCode)
    } catch {
        fputs("Error: \(error.localizedDescription)\n", stderr)
        Foundation.exit(3)
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
