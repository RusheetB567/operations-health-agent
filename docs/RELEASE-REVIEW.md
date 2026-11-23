# Release review

This is a review checklist, not an assertion that deployment or release has happened.

- [ ] Inspect implementation and test changes, including the full staged diff.
- [ ] Run unit/integration tests, the local demo, documentation link checks and targeted defect-injection checks.
- [ ] Check Windows and Linux CI results on the commit proposed for release.
- [ ] Confirm commit identity and repository branch policy.
- [ ] Exclude host reports, local history, synthetic run outputs, caches and credentials from the staged files.
- [ ] Check already-tracked generated data separately; ignore rules are not retroactive.
- [ ] Confirm all URLs are safe, authorised read-only diagnostic targets.
- [ ] Review report compatibility and documented exit codes.
- [ ] Record known limits and version the release only after review.

No automatic commit, push, merge, deployment or release is part of the local verification tools.
