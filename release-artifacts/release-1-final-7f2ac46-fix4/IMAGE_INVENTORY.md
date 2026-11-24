# Image inventory - candidate 7f2ac46-fix4

Source commit: `7f2ac46` (parent `84046b2`), branch `release-1/p1-dispatch`.

| Role | Tag | Immutable ID | Rebuilt for this candidate |
|---|---|---|---|
| Worker | `last9-worker:release-1-final-7f2ac46-fix4` | `sha256:f96fac9f2d16a0b3141578111cc110313f6de5488dcc6f80868767fbfe224fbb` | **yes**, from `git archive 7f2ac46` |
| API | `last9-api:release-1-final-84046b2-fix3` | `sha256:78f7f987cf3bc5074e6f3aeb9b08c3816bf4e18d7ddb57b3b4772de21c6396bb` | no - no API source changed |
| Web | `last9-web:release-1-final-78fb0a7` | `sha256:6a6489dcc5d3d9ef76ef5c6cc0cc4ab11faa8fac376895a14f9974b0fd660ab1` | no - still built with `http://localhost:8000` |
| Beat | worker image + `python -m app.beat_guard` | `sha256:f96fac9f2d16a0b3141578111cc110313f6de5488dcc6f80868767fbfe224fbb` | inherits the worker image |

## Notes

- The worker image tag resolves to a **manifest list** (BuildKit attestations),
  so its ID is the index digest. Config digest:
  `sha256:4a3ea343a668f789e60451ae128a9e735807318c783ae7441b0f73ec9d8a1be3`.
- The retained `84046b2` worker image (`c36ac27f...`) and API image
  (`78f7f987...`) are untouched and still present for comparison and for the
  negative-control test.
- The previous candidate's tags `...-616a8d3-fix3` and `...-84046b2-fix3` still
  point at the same `84046b2` digests; nothing was retagged.
