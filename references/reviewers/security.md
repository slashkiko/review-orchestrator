# security

Baseline: `deep` for high-risk trust-boundary changes; otherwise use the smallest available tier justified by scope.

Trace attacker-controlled sources through validation and authorization to sensitive sinks. Check authentication context, object/tenant ownership, policy registration/defaults, injection/deserialization, path/URL handling, cryptographic or credential use, outbound requests, and security-relevant error behavior.

A finding must state attacker capability, reachable path, violated security property, and impact. Check repository-specific middleware and defaults rather than assuming a framework is fail-open or fail-closed.

Exclude secrets merely present in text (`sensitive-data` owns exposure), general data corruption, dependency advisories without evidence, speculative threat models, and pre-existing weaknesses not made reachable by the diff.
