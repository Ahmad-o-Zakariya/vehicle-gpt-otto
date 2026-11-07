# CAN Adapter

`configs/verified_comma2k19.dbc` contains only the selected and previously
verified Toyota RAV4 segment mappings in `configs/comma2k19_dbc.yaml` and
[`can_mapping.md`](can_mapping.md): 0x025 steering and 0x0AA wheel speeds.
No new CAN IDs or bit layouts are claimed. Unknown IDs, bad frame type/length,
missing or flagged values, and wheel speeds outside the configured plausible
range are rejected. Timestamp ordering, vehicle/trip identity, provenance,
quality, units, and source/replay time are carried alongside the frame because
CAN payloads do not encode those fields.

Wheel-speed quantization is 0.01 km/h, at most 0.001389 m/s error. Steering
uses signed Motorola fields with 1.5-degree and 0.1-degree factors. Property
based tests cover signed and unsigned representable ranges. A sample of 100
real raw comma2k19 frames is also decoded through this DBC and compared with
the existing independent decoder at 1e-9 tolerance.

`replay_virtual()` uses two python-can virtual buses and is a development
transport only. A SocketCAN adapter path is exposed through python-can, but
`ip link` returns `Operation not permitted` in this execution environment;
therefore no `vcan0` end-to-end run is claimed. On a host with permission:

```sh
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set up vcan0
```

Then run the real SocketCAN integration check separately from virtual tests.
Do not modify the supplied DBC/source data.
