import Testing
@testable import HealthBridgeLib

// MARK: - ChunkData JSON Parsing

@Test func chunkDataDecoding() throws {
    let json = """
    {
        "session_id": 47,
        "chunk_index": 3,
        "start": "2026-02-16T10:33:00Z",
        "end": "2026-02-16T10:34:00Z",
        "steps": 87,
        "distance_miles": 0.04,
        "calories": 4
    }
    """

    let data = json.data(using: .utf8)!
    let chunk = try JSONDecoder().decode(ChunkData.self, from: data)

    #expect(chunk.sessionId == 47)
    #expect(chunk.chunkIndex == 3)
    #expect(chunk.steps == 87)
    #expect(abs(chunk.distanceMiles - 0.04) < 0.001)
    #expect(chunk.calories == 4)
    #expect(chunk.start == "2026-02-16T10:33:00Z")
    #expect(chunk.end == "2026-02-16T10:34:00Z")
}

@Test func chunkDataDateParsing() throws {
    let json = """
    {
        "session_id": 1,
        "chunk_index": 0,
        "start": "2026-02-16T10:33:00Z",
        "end": "2026-02-16T10:34:00Z",
        "steps": 10,
        "distance_miles": 0.01,
        "calories": 1
    }
    """

    let data = json.data(using: .utf8)!
    let chunk = try JSONDecoder().decode(ChunkData.self, from: data)

    #expect(chunk.startDate < chunk.endDate)
}

@Test func chunkDataInvalidJSON() {
    let json = """
    {"session_id": "not_a_number"}
    """

    let data = json.data(using: .utf8)!
    #expect(throws: (any Error).self) {
        try JSONDecoder().decode(ChunkData.self, from: data)
    }
}

@Test func chunkDataMissingFields() {
    let json = """
    {"session_id": 1, "chunk_index": 0}
    """

    let data = json.data(using: .utf8)!
    #expect(throws: (any Error).self) {
        try JSONDecoder().decode(ChunkData.self, from: data)
    }
}

// MARK: - WorkoutData JSON Parsing

@Test func workoutDataDecoding() throws {
    let json = """
    {
        "session_id": 47,
        "start": "2026-02-16T10:30:00Z",
        "end": "2026-02-16T11:42:34Z",
        "duration_seconds": 4354,
        "total_steps": 4821,
        "total_distance_miles": 1.92,
        "total_calories": 186
    }
    """

    let data = json.data(using: .utf8)!
    let workout = try JSONDecoder().decode(WorkoutData.self, from: data)

    #expect(workout.sessionId == 47)
    #expect(workout.durationSeconds == 4354)
    #expect(workout.totalSteps == 4821)
    #expect(abs(workout.totalDistanceMiles - 1.92) < 0.001)
    #expect(workout.totalCalories == 186)
}

@Test func workoutDataDateParsing() throws {
    let json = """
    {
        "session_id": 1,
        "start": "2026-02-16T10:30:00Z",
        "end": "2026-02-16T11:42:34Z",
        "duration_seconds": 300,
        "total_steps": 100,
        "total_distance_miles": 0.5,
        "total_calories": 10
    }
    """

    let data = json.data(using: .utf8)!
    let workout = try JSONDecoder().decode(WorkoutData.self, from: data)

    #expect(workout.startDate < workout.endDate)
}

@Test func workoutDataInvalidJSON() {
    let json = """
    {"session_id": "not_a_number"}
    """

    let data = json.data(using: .utf8)!
    #expect(throws: (any Error).self) {
        try JSONDecoder().decode(WorkoutData.self, from: data)
    }
}

// MARK: - Result Encoding

@Test func chunkResultEncoding() throws {
    let result = ChunkResult(
        stepsUUID: "ABC-123",
        distanceUUID: "DEF-456",
        caloriesUUID: "GHI-789",
        wasExisting: false
    )

    let json = result.toJSON()
    let data = json.data(using: .utf8)!
    let decoded = try JSONDecoder().decode(ChunkResult.self, from: data)

    #expect(decoded.stepsUUID == "ABC-123")
    #expect(decoded.distanceUUID == "DEF-456")
    #expect(decoded.caloriesUUID == "GHI-789")
    #expect(decoded.wasExisting == false)
}

@Test func chunkResultExistingFlag() {
    let result = ChunkResult(
        stepsUUID: "ABC-123",
        distanceUUID: "DEF-456",
        caloriesUUID: "GHI-789",
        wasExisting: true
    )

    let json = result.toJSON()
    #expect(json.contains("\"was_existing\":true"))
}

@Test func workoutResultEncoding() throws {
    let result = WorkoutResult(
        workoutUUID: "WORKOUT-UUID-123",
        wasExisting: false
    )

    let json = result.toJSON()
    let data = json.data(using: .utf8)!
    let decoded = try JSONDecoder().decode(WorkoutResult.self, from: data)

    #expect(decoded.workoutUUID == "WORKOUT-UUID-123")
    #expect(decoded.wasExisting == false)
}

// MARK: - BridgeError

@Test func bridgeErrorCodes() {
    let auth = BridgeError.authError("denied")
    #expect(auth.code == 1)
    #expect(auth.exitCode == 1)

    let validation = BridgeError.validationError("bad data")
    #expect(validation.code == 2)

    let write = BridgeError.writeError("failed")
    #expect(write.code == 3)
}

@Test func bridgeErrorDescription() {
    let error = BridgeError.authError("HealthKit denied")
    #expect(error.description == "Error: HealthKit denied")
}

// MARK: - ISO8601 Parsing

@Test func parseISO8601WithZ() {
    let date = parseISO8601("2026-02-16T10:30:00Z")
    let calendar = Calendar(identifier: .gregorian)
    let components = calendar.dateComponents(in: TimeZone(identifier: "UTC")!, from: date)

    #expect(components.year == 2026)
    #expect(components.month == 2)
    #expect(components.day == 16)
    #expect(components.hour == 10)
    #expect(components.minute == 30)
    #expect(components.second == 0)
}

@Test func parseISO8601WithFractionalSeconds() {
    let date = parseISO8601("2026-02-16T10:30:00.500Z")
    let calendar = Calendar(identifier: .gregorian)
    let components = calendar.dateComponents(in: TimeZone(identifier: "UTC")!, from: date)
    #expect(components.year == 2026)
}
