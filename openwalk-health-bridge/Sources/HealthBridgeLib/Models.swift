import Foundation

// MARK: - Input Models

/// Represents a 60-second chunk of session data for incremental HealthKit sync.
public struct ChunkData: Codable {
    public let sessionId: Int
    public let chunkIndex: Int
    public let start: String
    public let end: String
    public let steps: Int
    public let distanceMiles: Double
    public let calories: Int

    public var startDate: Date {
        parseISO8601(start)
    }

    public var endDate: Date {
        parseISO8601(end)
    }

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case chunkIndex = "chunk_index"
        case start, end, steps
        case distanceMiles = "distance_miles"
        case calories
    }
}

/// Represents a complete session summary for HealthKit workout creation.
public struct WorkoutData: Codable {
    public let sessionId: Int
    public let start: String
    public let end: String
    public let durationSeconds: Int
    public let totalSteps: Int
    public let totalDistanceMiles: Double
    public let totalCalories: Int

    public var startDate: Date {
        parseISO8601(start)
    }

    public var endDate: Date {
        parseISO8601(end)
    }

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case start, end
        case durationSeconds = "duration_seconds"
        case totalSteps = "total_steps"
        case totalDistanceMiles = "total_distance_miles"
        case totalCalories = "total_calories"
    }
}

// MARK: - Output Models

/// Result from writing a chunk to HealthKit.
public struct ChunkResult: Codable {
    public let stepsUUID: String
    public let distanceUUID: String
    public let caloriesUUID: String
    public let wasExisting: Bool

    public init(stepsUUID: String, distanceUUID: String, caloriesUUID: String, wasExisting: Bool) {
        self.stepsUUID = stepsUUID
        self.distanceUUID = distanceUUID
        self.caloriesUUID = caloriesUUID
        self.wasExisting = wasExisting
    }

    enum CodingKeys: String, CodingKey {
        case stepsUUID = "steps_uuid"
        case distanceUUID = "distance_uuid"
        case caloriesUUID = "calories_uuid"
        case wasExisting = "was_existing"
    }

    public func toJSON() -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        let data = try! encoder.encode(self)
        return String(data: data, encoding: .utf8)!
    }
}

/// Result from writing a workout to HealthKit.
public struct WorkoutResult: Codable {
    public let workoutUUID: String
    public let wasExisting: Bool

    public init(workoutUUID: String, wasExisting: Bool) {
        self.workoutUUID = workoutUUID
        self.wasExisting = wasExisting
    }

    enum CodingKeys: String, CodingKey {
        case workoutUUID = "workout_uuid"
        case wasExisting = "was_existing"
    }

    public func toJSON() -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        let data = try! encoder.encode(self)
        return String(data: data, encoding: .utf8)!
    }
}

// MARK: - Errors

/// Bridge error with exit code mapping.
public struct BridgeError: Error, CustomStringConvertible {
    public let code: Int
    public let message: String

    public var exitCode: Int32 { Int32(code) }

    public var description: String {
        "Error: \(message)"
    }

    public static func authError(_ message: String) -> BridgeError {
        BridgeError(code: 1, message: message)
    }

    public static func validationError(_ message: String) -> BridgeError {
        BridgeError(code: 2, message: message)
    }

    public static func writeError(_ message: String) -> BridgeError {
        BridgeError(code: 3, message: message)
    }
}

// MARK: - JSON Loading

public func loadChunkJSON(from path: String) throws -> ChunkData {
    guard FileManager.default.fileExists(atPath: path) else {
        throw BridgeError.validationError("Chunk JSON file not found: \(path)")
    }

    let data = try Data(contentsOf: URL(fileURLWithPath: path))
    let decoder = JSONDecoder()

    do {
        let chunk = try decoder.decode(ChunkData.self, from: data)

        guard chunk.steps >= 0 else {
            throw BridgeError.validationError("Steps must be non-negative")
        }
        guard chunk.distanceMiles >= 0 else {
            throw BridgeError.validationError("Distance must be non-negative")
        }
        guard chunk.calories >= 0 else {
            throw BridgeError.validationError("Calories must be non-negative")
        }
        guard chunk.startDate < chunk.endDate else {
            throw BridgeError.validationError("Chunk start must be before end")
        }

        return chunk
    } catch let error as BridgeError {
        throw error
    } catch {
        throw BridgeError.validationError("Invalid chunk JSON: \(error.localizedDescription)")
    }
}

public func loadWorkoutJSON(from path: String) throws -> WorkoutData {
    guard FileManager.default.fileExists(atPath: path) else {
        throw BridgeError.validationError("Workout JSON file not found: \(path)")
    }

    let data = try Data(contentsOf: URL(fileURLWithPath: path))
    let decoder = JSONDecoder()

    do {
        let workout = try decoder.decode(WorkoutData.self, from: data)

        guard workout.durationSeconds > 0 else {
            throw BridgeError.validationError("Duration must be positive")
        }
        guard workout.totalSteps >= 0 else {
            throw BridgeError.validationError("Total steps must be non-negative")
        }
        guard workout.startDate < workout.endDate else {
            throw BridgeError.validationError("Workout start must be before end")
        }

        return workout
    } catch let error as BridgeError {
        throw error
    } catch {
        throw BridgeError.validationError("Invalid workout JSON: \(error.localizedDescription)")
    }
}

// MARK: - Date Parsing

/// Parse an ISO 8601 timestamp string to a Date.
public func parseISO8601(_ string: String) -> Date {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

    if let date = formatter.date(from: string) {
        return date
    }

    // Try without fractional seconds
    formatter.formatOptions = [.withInternetDateTime]
    if let date = formatter.date(from: string) {
        return date
    }

    fatalError("Invalid ISO 8601 date: \(string)")
}
