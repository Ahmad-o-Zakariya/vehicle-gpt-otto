# SOME/IP Adapter

**Status: BLOCKED — native COVESA vSomeIP service/client interaction not built.**
`vsomeip3` headers, libraries, and pkg-config metadata are absent. No system
package installation or privileged change was attempted. Boost/vSomeIP versions
and Service Discovery could therefore not be verified here.

A bounded asyncio Unix-domain JSON Lines bridge is implemented in
`src/vehicle_gpt/adapters/someip/bridge.py` to let downstream development use a
local bridge contract. Its project-local identifiers in `ProjectService` are
simulator identifiers only. The bridge is not SOME/IP and does not implement
Service Discovery, vSomeIP event groups, or network serialization.

After installing vSomeIP 3.x and Boost >=1.75 in an approved development image,
add isolated C++20 service/client programs and test discovery, availability,
subscription, typed events, and errors. Do not report the bridge test as a
SOME/IP test.
