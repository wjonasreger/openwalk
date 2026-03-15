import Foundation
import HealthKit

/// Writes a 60-second chunk of session data to HealthKit as three quantity samples.
public enum ChunkWriter {

    /// Write chunk data to HealthKit. Returns UUIDs of created (or existing) samples.
    public static func writeChunk(bridge: HealthBridge, data: ChunkData) async throws -> ChunkResult {
        // Check for duplicate first
        if let existing = try await Deduplication.findExistingChunk(
            store: bridge.store,
            sessionId: data.sessionId,
            chunkIndex: data.chunkIndex,
            startDate: data.startDate,
            endDate: data.endDate
        ) {
            return ChunkResult(
                stepsUUID: existing["steps"] ?? "",
                distanceUUID: existing["distance"] ?? "",
                caloriesUUID: existing["calories"] ?? "",
                wasExisting: true
            )
        }

        // Create samples
        let samples = createSamples(from: data)

        // Write to HealthKit
        do {
            try await bridge.store.save(samples)
        } catch {
            throw BridgeError.writeError("HealthKit write failed: \(error.localizedDescription)")
        }

        return ChunkResult(
            stepsUUID: samples[0].uuid.uuidString,
            distanceUUID: samples[1].uuid.uuidString,
            caloriesUUID: samples[2].uuid.uuidString,
            wasExisting: false
        )
    }

    private static func createSamples(from data: ChunkData) -> [HKQuantitySample] {
        let metadata: [String: Any] = [
            "OpenWalkSessionId": data.sessionId,
            "OpenWalkChunkIndex": data.chunkIndex,
            HKMetadataKeyWasUserEntered: false
        ]

        let steps = HKQuantitySample(
            type: HKQuantityType(.stepCount),
            quantity: HKQuantity(unit: .count(), doubleValue: Double(data.steps)),
            start: data.startDate,
            end: data.endDate,
            metadata: metadata
        )

        let distance = HKQuantitySample(
            type: HKQuantityType(.distanceWalkingRunning),
            quantity: HKQuantity(unit: .mile(), doubleValue: data.distanceMiles),
            start: data.startDate,
            end: data.endDate,
            metadata: metadata
        )

        let calories = HKQuantitySample(
            type: HKQuantityType(.activeEnergyBurned),
            quantity: HKQuantity(unit: .kilocalorie(), doubleValue: Double(data.calories)),
            start: data.startDate,
            end: data.endDate,
            metadata: metadata
        )

        return [steps, distance, calories]
    }
}
