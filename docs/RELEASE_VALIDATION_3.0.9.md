# Release Validation — 3.0.9

## Scope and owner instruction

Owner explicitly requested Windows upgrade packages only and immediate public
publication; Installer, Portable and macOS are out of scope. Preserve pending
operator checks as pending; no false acceptance values. Real printer proof must
wait for the owner's company environment, as already disclosed and acknowledged.

Existing development branch is retained; the existing Windows release ref may
fast-forward to the same frozen SHA to use its established no-duplicate-CI route.
No new branch is required, and existing published release tags/assets stay immutable.

## Source and gates

| Item | Status / evidence |
|---|---|
| Product baseline | 5698107, safe shutdown repair; includes printing repair and Deep Search compact layout |
| Version / tag | 3.0.9 / v3.0.9 |
| Frozen source / native run | Pending |
| Windows full isolated regression / packaging | Pending |
| Frozen login-ready / unauthenticated worker denial | Pending |
| Signed provenance, private and legacy routes | Pending |
| Original Launcher successive upgrades | Pending |
| Candidate real-account login | Pending; not established by login-ready smoke |
| Company printer / DFE proof | Pending, owner to test at company |
| Remote assets / public route validation | Pending |
| Installer / Portable / Mac | Out of scope |

## Development evidence

115 shutdown-related checks passed plus isolated UI probes. Printing repair had
81 related checks passed. These local results do not substitute native complete
release regression on the frozen candidate. Tests and runtime input changes require
a new candidate; no old binary or evidence is relabelled.
