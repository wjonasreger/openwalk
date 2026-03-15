import Foundation
import HealthKit

/// Deduplication logic — checks HealthKit for existing samples before writing.
public enum Deduplication {

    /// Check if a chunk has already been written to HealthKit.
    /// Returns a dictionary of UUIDs if found, nil otherwise.
    public static func findExistingChunk(
        store: HKHealthStore,
        sessionId: Int,
        chunkIndex: Int,
        startDate: Date,
        endDate: Date
    ) async throws -> [String: String]? {
        let predicate = NSCompoundPredicate(andPredicateWithSubpredicates: [
            HKQuery.predicateForSamples(
                withStart: startDate,
                end: endDate,
                options: .strictStartDate
            ),
            HKQuery.predicateForObjects(
                withMetadataKey: "OpenWalkSessionId",
                allowedValues: [sessionId as NSNumber]
            )
        ])

        let stepsType = HKQuantityType(.stepCount)
        let samples = try await querySamples(store: store, type: stepsType, predicate: predicate)

        // Look for a sample with matching chunk index
        for sample in samples {
            if let meta = sample.metadata,
               let existingChunkIndex = meta["OpenWalkChunkIndex"] as? Int,
               existingChunkIndex == chunkIndex {
                // Found duplicate — fetch all three UUIDs
                return try await fetchChunkUUIDs(
                    store: store,
                    sessionId: sessionId,
                    chunkIndex: chunkIndex,
                    startDate: startDate,
                    endDate: endDate
                )
            }
        }

        return nil
    }

    /// Check if a workout has already been written to HealthKit.
    /// Returns the workout UUID if found, nil otherwise.
    public static func findExistingWorkout(
        store: HKHealthStore,
        sessionId: Int,
        startDate: Date,
        endDate: Date
    ) async throws -> String? {
        let predicate = NSCompoundPredicate(andPredicateWithSubpredicates: [
            HKQuery.predicateForSamples(
                withStart: startDate,
                end: endDate,
                options: .strictStartDate
            ),
            HKQuery.predicateForObjects(
                withMetadataKey: "OpenWalkSessionId",
                allowedValues: [sessionId as NSNumber]
            )
        ])

        let workouts = try await queryWorkouts(store: store, predicate: predicate)

        for workout in workouts {
            if let meta = workout.metadata,
               let existingSessionId = meta["OpenWalkSessionId"] as? Int,
               existingSessionId == sessionId {
                return workout.uuid.uuidString
            }
        }

        return nil
    }

    // MARK: - Query Helpers

    private static func querySamples(
        store: HKHealthStore,
        type: HKQuantityType,
        predicate: NSPredicate
    ) async throws -> [HKQuantitySample] {
        try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(
                sampleType: type,
                predicate: predicate,
                limit: HKObjectQueryNoLimit,
                sortDescriptors: nil
            ) { _, samples, error in
                if let error = error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: samples as? [HKQuantitySample] ?? [])
                }
            }
            store.execute(query)
        }
    }

    private static func queryWorkouts(
        store: HKHealthStore,
        predicate: NSPredicate
    ) async throws -> [HKWorkout] {
        try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(
                sampleType: HKWorkoutType.workoutType(),
                predicate: predicate,
                limit: HKObjectQueryNoLimit,
                sortDescriptors: nil
            ) { _, samples, error in
                if let error = error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: samples as? [HKWorkout] ?? [])
                }
            }
            store.execute(query)
        }
    }

    private static func fetchChunkUUIDs(
        store: HKHealthStore,
        sessionId: Int,
        chunkIndex: Int,
        startDate: Date,
        endDate: Date
    ) async throws -> [String: String] {
        let predicate = NSCompoundPredicate(andPredicateWithSubpredicates: [
            HKQuery.predicateForSamples(
                withStart: startDate,
                end: endDate,
                options: .strictStartDate
            ),
            HKQuery.predicateForObjects(
                withMetadataKey: "OpenWalkSessionId",
                allowedValues: [sessionId as NSNumber]
            )
        ])

        var uuids: [String: String] = [:]

        let types: [(String, HKQuantityType)] = [
            ("steps", HKQuantityType(.stepCount)),
            ("distance", HKQuantityType(.distanceWalkingRunning)),
            ("calories", HKQuantityType(.activeEnergyBurned))
        ]

        for (key, type) in types {
            let samples = try await querySamples(store: store, type: type, predicate: predicate)
            if let sample = samples.first(where: { sample in
                sample.metadata?["OpenWalkChunkIndex"] as? Int == chunkIndex
            }) {
                uuids[key] = sample.uuid.uuidString
            }
        }

        return uuids
    }
}
