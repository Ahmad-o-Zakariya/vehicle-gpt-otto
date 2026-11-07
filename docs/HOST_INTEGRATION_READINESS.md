# Host integration readiness

All observations below come from the Codex Linux workspace execution context. Sandbox permissions may differ from the user's physical host; do not infer that the physical host itself lacks these facilities.

| Integration | Status | Evidence | Minimum unblock |
|---|---|---|---|
| CAN DBC and python-can virtual transport | VERIFIED SIMULATION | 100 sampled source frame comparisons; Hypothesis round trips; virtual bus transmit/receive tests pass. | None for simulation. |
| SocketCAN/vcan | HOST BLOCKED | `ip link show` and `ip link show type can` fail `Cannot open netlink socket: Operation not permitted`; `socketcan_available("vcan0")` false. No `sudo`, module load, or interface change attempted. | Run in host context with CAN/vcan kernel support and permission to create/configure a vcan interface; then test actual transmit/receive. |
| SOME/IP JSONL bridge | VERIFIED SIMULATION | Bounded Unix socket request/response and malformed JSON payload are tested. It is explicitly not a vSomeIP implementation. | None for Python bridge. |
| Native vSomeIP | HOST BLOCKED | `g++` 15.2 and CMake 4.2.3 exist; C++20 syntax compile passes. `native/` source absent, Boost headers and vSomeIP headers/library/pkg-config absent; `cmake -S native` reports missing source directory. | Add isolated native C++20 client/service implementation and install/use Boost plus COVESA vSomeIP in a native build environment; exercise discovery and events. |
| AOSP VHAL simulator | VERIFIED SIMULATION | Property definitions and in-memory read/update/status/subscription tests pass. | None for simulator. |
| Real Android VHAL | HOST BLOCKED | `adb` and Android SDK/emulator not present. No large image downloaded. | Existing Android Automotive emulator or device with compatible VHAL AIDL. |
| QNX slog2info parser | VERIFIED SIMULATION | Documented five-column fixture, malformed-line and provenance tests pass. Fixture is marked synthetic. | None for parser. |
| Native/live QNX logs | NOT TESTED | No `slog2info`, `qcc`, QNX tools or actual slog2info export found in workspace. | Provide genuine QNX export/toolchain; keep raw log privacy and licensing controls. |
| GPU/SLM | CPU PASS; GPU BLOCKED | llama.cpp build 12180 and the hash-verified pinned GGUF ran in CPU-only mode. Five actual SLM API case studies produced validated plans and verified TRACE results. `nvidia-smi` could not communicate with the NVIDIA driver and no `/dev/nvidia*` was visible, so RTX 3050 offload, VRAM and GPU latency were not verified. | SLM inference is functionally verified on CPU. Target GPU validation remains incomplete; do not report GPU performance. |

The pinned candidate and observed GGUF hash are documented in `configs/model_candidate.json` and `docs/SLM_PLANNER.md`. The user-provided target host report names an RTX 3050 4 GB, but the Codex execution context could not access its driver/device; no target GPU offload or physical-host performance conclusion is made.
