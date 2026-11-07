# QNX slog2info Export Parser

`parse_slog2info_line()` accepts the documented default five-column format:
logging time, buffer set/process context, buffer name, user-defined event code,
and message. It parses month/day/time components and can attach a caller-supplied
year; it never invents a timezone or year. The original clock text and parsed
components are both retained. Buffer `*` oldest-packet marker is preserved as
an unknown-field flag. Component name is derived from the buffer-set token.

Severity is `null`: this project has no authoritative mapping from event codes
to severity. Malformed records fail with a bounded error. Fixture data in tests
is synthetic; no native QNX device or log service was used.

Source format: [QNX slog2info documentation](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/s/slog2info.html).
