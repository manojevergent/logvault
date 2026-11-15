
### Additional unchecked items for 7f2ac46-fix4

- [ ] Confirm the worker image digest
      (`sha256:f96fac9f…f224fbb`) and that it was built from `git archive 7f2ac46`
- [ ] Reproduce the 13 ownership tests, and confirm 4 of them fail on the
      `84046b2` worker image
- [ ] Confirm all three fenced `save()` sites gate the completion event, the
      failure event and the failure alert on the write result
- [ ] Confirm `release-1-final-7f2ac46-fix4/0034_job_dispatch_outbox.py`
      contains `LOCK TABLE ... ACCESS EXCLUSIVE` (the `fix3` package did not)
- [ ] Verify `checksums.sha256` and its self-hash independently
- [ ] Confirm GB-08 (Last9), GB-01 (independent reviewer) and GB-05 (web URL)
      remain open
- [ ] Confirm no reviewer name, date, signature or checkbox was filled by the
      author

**No independent human review has been completed. This package is prepared for a
separate reviewer, not approved by one.**
