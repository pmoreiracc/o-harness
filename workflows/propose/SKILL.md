---
name: propose
description: Run the explicitly configured consumer propose policy.
---
Resolve the project root. Require `.oh/project.json` to select `design_profile: consumer-v1`.
Read `.oh/policy/propose.md` from that consumer and follow it. If the policy is absent,
report the missing integration and use the neutral OH task workflow for ordinary work.
OH does not prescribe ADRs, roadmap formats, data models, or product invariants.
