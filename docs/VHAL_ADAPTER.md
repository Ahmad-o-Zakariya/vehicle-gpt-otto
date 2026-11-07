# VHAL Property Simulator

The local in-memory simulator exposes two AOSP property definitions from the
Android 16 `VehicleProperty.aidl` source: `PERF_VEHICLE_SPEED` (`0x11600207`,
float, m/s, READ, CONTINUOUS, GLOBAL) and `PERF_ODOMETER` (`0x11600204`, float,
km, READ, CONTINUOUS, GLOBAL). IDs and property metadata are kept in
`configs/vhal_properties.json`.

The simulator supports reads, timestamped updates, unavailable/invalid/error
states and async subscriptions. Timestamps use a monotonic nanosecond clock by
default. Simulator values have synthetic provenance. Real-vehicle property
availability is unverified, and this has not been tested against an AAOS
emulator or Android VHAL service.

Source: [AOSP VehicleProperty.aidl](https://android.googlesource.com/platform/hardware/interfaces/%2B/refs/heads/android16-release/automotive/vehicle/aidl_property/android/hardware/automotive/vehicle/VehicleProperty.aidl).
