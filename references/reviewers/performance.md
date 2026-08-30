# performance

Baseline: `balanced`. Conditional.

Trace work as input size grows: query count, scan/loop complexity, batch boundaries, network/file I/O, allocation/copy volume, cache behavior, and UI render frequency. Use measurements, query plans, benchmarks, or clear asymptotic/volume evidence where available.

A finding states the expected scale/hot path and measurable regression. Recommend measurement when evidence cannot establish impact.

Exclude micro-optimizations and plainly local repeated work owned by `simplify`, unmeasured aesthetic preferences, and pre-existing slow paths untouched by the diff.
