# LexLocal — Document Index

This index records the authority and current delivery status of the LexLocal
document set. When documents conflict, the more specific approved document
governs within its authority area.

| File | Status | Authority area |
|---|---|---|
| `01_PROJECT_CHARTER.md` | Preliminary | Initial project direction |
| `02_SCOPE_AND_MVP.md` | Approved | Binding product and first-release scope |
| `03_USER_FLOWS_AND_STATES.md` | Approved | User-visible behavior and state transitions |
| `04_SYSTEM_ARCHITECTURE.md` | Approved | Technical architecture and implementation boundaries |
| `05_DATA_MODEL.md` | Approved; initial DDL supplied | Persistent data model and database invariants |
| `06_SECURITY_DESIGN.md` | Approved | Cryptography, key lifecycle, locking, recovery, and secure deletion |
| `07_TEST_AND_EVALUATION_PLAN.md` | Approved | Test strategy, evaluation datasets, thresholds, and release evidence |

## Authority Order

1. `02_SCOPE_AND_MVP.md` defines what the first release must include.
2. `03_USER_FLOWS_AND_STATES.md` defines approved user-visible behavior.
3. `04_SYSTEM_ARCHITECTURE.md` defines technical structure within that scope.
4. `05_DATA_MODEL.md` defines persistence and database invariants.
5. `06_SECURITY_DESIGN.md` defines security mechanisms and cryptographic rules.
6. `07_TEST_AND_EVALUATION_PLAN.md` defines verification and release evidence
   without reducing earlier requirements.

The preliminary charter is retained for project context but does not override
later approved decisions.
