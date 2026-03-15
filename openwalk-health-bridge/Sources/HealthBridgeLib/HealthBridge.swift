import Foundation
import HealthKit

/// Core HealthKit bridge — handles authorization and provides the health store.
public class HealthBridge {
    public let store = HKHealthStore()

    private let typesToWrite: Set<HKSampleType> = [
        HKQuantityType(.stepCount),
        HKQuantityType(.distanceWalkingRunning),
        HKQuantityType(.activeEnergyBurned),
        HKWorkoutType.workoutType()
    ]

    public init() {}

    // MARK: - Authorization

    /// Request HealthKit write authorization. Throws BridgeError on failure.
    public func requestAuthorization() async throws {
        guard HKHealthStore.isHealthDataAvailable() else {
            throw BridgeError.authError(
                "HealthKit not available on this device/OS version. Requires macOS 14+."
            )
        }

        try await store.requestAuthorization(toShare: typesToWrite, read: [])

        // Verify authorization was granted for all types
        for type in typesToWrite {
            let status = store.authorizationStatus(for: type)
            guard status == .sharingAuthorized else {
                throw BridgeError.authError(
                    "HealthKit authorization denied for \(type.identifier). "
                    + "Please enable access in System Settings > Privacy & Security > Health."
                )
            }
        }
    }
}
