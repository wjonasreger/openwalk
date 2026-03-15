import Foundation
import HealthKit

/// Writes a session summary workout record to HealthKit.
public enum WorkoutWriter {

    /// Write workout data to HealthKit. Returns UUID of created (or existing) workout.
    public static func writeWorkout(bridge: HealthBridge, data: WorkoutData) async throws -> WorkoutResult {
        // Check for duplicate first
        if let existingUUID = try await Deduplication.findExistingWorkout(
            store: bridge.store,
            sessionId: data.sessionId,
            startDate: data.startDate,
            endDate: data.endDate
        ) {
            return WorkoutResult(
                workoutUUID: existingUUID,
                wasExisting: true
            )
        }

        // Build and save workout using HKWorkoutBuilder
        let workoutUUID = try await buildAndSaveWorkout(store: bridge.store, data: data)

        return WorkoutResult(
            workoutUUID: workoutUUID,
            wasExisting: false
        )
    }

    private static func buildAndSaveWorkout(
        store: HKHealthStore,
        data: WorkoutData
    ) async throws -> String {
        let config = HKWorkoutConfiguration()
        config.activityType = .walking
        config.locationType = .indoor

        let builder = HKWorkoutBuilder(healthStore: store, configuration: config, device: nil)

        do {
            try await builder.beginCollection(at: data.startDate)

            // Add quantity samples for the workout
            let metadata: [String: Any] = [
                "OpenWalkSessionId": data.sessionId,
                "OpenWalkSource": "OpenWalk via InMovement Unsit BLE",
                HKMetadataKeyWasUserEntered: false
            ]

            let steps = HKQuantitySample(
                type: HKQuantityType(.stepCount),
                quantity: HKQuantity(unit: .count(), doubleValue: Double(data.totalSteps)),
                start: data.startDate,
                end: data.endDate,
                metadata: metadata
            )

            let distance = HKQuantitySample(
                type: HKQuantityType(.distanceWalkingRunning),
                quantity: HKQuantity(unit: .mile(), doubleValue: data.totalDistanceMiles),
                start: data.startDate,
                end: data.endDate,
                metadata: metadata
            )

            let calories = HKQuantitySample(
                type: HKQuantityType(.activeEnergyBurned),
                quantity: HKQuantity(unit: .kilocalorie(), doubleValue: Double(data.totalCalories)),
                start: data.startDate,
                end: data.endDate,
                metadata: metadata
            )

            try await builder.addSamples([steps, distance, calories])
            try await builder.addMetadata(metadata)
            try await builder.endCollection(at: data.endDate)

            guard let workout = try await builder.finishWorkout() else {
                throw BridgeError.writeError("HKWorkoutBuilder.finishWorkout() returned nil")
            }

            return workout.uuid.uuidString
        } catch let error as BridgeError {
            throw error
        } catch {
            throw BridgeError.writeError(
                "HealthKit workout write failed: \(error.localizedDescription)"
            )
        }
    }
}
