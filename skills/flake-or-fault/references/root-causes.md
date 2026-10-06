# Why tests flake, and the fix that actually holds

Read the failing assertion and the test together, then match the signal below.
Each entry gives the tell, the real fix, and the tempting non-fix. If none fits,
capture more per-run detail (`flakerun.py run --keep-output`) and compare a
failing run's output with a passing one.

## Shared state between tests (order dependence)

- **Tell:** `order-dependent` verdict; fails only after certain tests; fails under
  shuffle, passes in file order.
- **Usual sources:** module-level globals and singletons, caches, class
  attributes, environment variables, `os.chdir`, monkeypatches not undone, mocks
  not restored, database rows not rolled back, files left in a shared directory,
  registered event handlers, feature flags toggled in one test.
- **Fix:** make the polluter clean up (fixture teardown, `afterEach` restore,
  transaction rollback, `monkeypatch`/`vi.restoreAllMocks`), or make the victim
  set up everything it relies on. Fix both if both are wrong.
- **Non-fix:** pinning the test order.

## Waiting on time instead of on a condition

- **Tell:** timeouts, "element not found", "expected 1 call, got 0"; worse under
  CPU load or in CI; code under test is async, a thread, a subprocess, a UI.
- **Fix:** wait for the observable condition (await the promise, poll for the
  state with a deadline, use the framework's auto-waiting locator, join the
  thread, use an event or channel). Make the code under test expose a way to
  know it is done if it has none.
- **Non-fix:** `sleep`, a bigger timeout, a retry.

## Real races in the code under test

- **Tell:** Go `-race` reports; failures only with parallelism; results depend
  on which goroutine/thread/promise finishes first; lost updates; double sends.
- **Fix:** this is a product bug. Fix the synchronisation (lock, atomic,
  ordered await, idempotency key), keep the test, and say so in the report.
- **Non-fix:** serialising the test so the race cannot show.

## The clock and the calendar

- **Tell:** fails near midnight, month end, DST changes, New Year, or in a CI
  machine's timezone; asserts on "today"; durations compared exactly.
- **Fix:** inject or freeze the clock (fake timers, `freezegun`/`time-machine`,
  a `Clock` parameter); construct dates in an explicit timezone; compare
  durations with a tolerance only where the code genuinely has one.
- **Non-fix:** skipping the test at certain times.

## Randomness and unordered data

- **Tell:** different values per run; failures disappear with a fixed seed;
  assertions on the order of a set, dict/map iteration, `Promise.all` side
  effects, DB rows without `ORDER BY`, directory listings, concurrent output.
- **Fix:** seed generators in tests and log the seed; sort before comparing or
  compare as sets; add `ORDER BY` where the product needs an order (that one is
  a product bug).
- **Non-fix:** retrying until the lucky order appears.

## External services and the network

- **Tell:** connection errors, rate limits (429), DNS failures, slow third-party
  responses; correlates with time of day or CI region.
- **Fix:** stub the boundary (recorded responses, a local fake, testcontainers
  with a readiness check) and keep one clearly-labelled contract test that is
  allowed to hit the real service outside the main suite.
- **Non-fix:** retrying the request in the test.

## Shared resources between parallel workers

- **Tell:** fails only in parallel; "address already in use"; two tests write
  the same temp file, DB schema, queue, or cache key.
- **Fix:** per-test or per-worker resources: port 0 and read the bound port,
  `tmp_path`/`mkdtemp`, a schema or DB per worker, unique keys.
- **Non-fix:** forcing the whole suite to run serially.

## Leaks and exhaustion

- **Tell:** fails late in long runs only; "too many open files"; memory grows;
  slower each run; only after many tests in the same process.
- **Fix:** close what you open (files, sockets, DB connections, browser pages,
  servers), stop timers and intervals, and shut down pools in teardown.

## Environment differences (passes locally, fails in CI)

- **Tell:** never fails locally, often in CI or the reverse.
- **Check:** timezone and locale, CPU count (parallelism), filesystem case
  sensitivity and path separators, line endings, available memory, tool and
  dependency versions (lockfile honoured?), env vars set locally but not in CI,
  network access. Reproduce by matching the one that differs (`TZ=UTC`,
  `LANG=C`, `-n 2`, the CI container image).

## Floating point and tolerances

- **Tell:** off by a tiny amount, platform-dependent, order-of-summation
  dependent.
- **Fix:** compare with an explicit, justified tolerance; avoid relying on the
  order of parallel reductions.

## When the test is simply wrong

A test that asserts on incidental details (log wording, exact timing, mock call
counts that depend on scheduling) can be legitimately rewritten to assert on the
behaviour that matters. Say why the old assertion was wrong; do not just relax it.
