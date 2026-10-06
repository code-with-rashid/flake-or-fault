# Runner recipes

For each runner: how to get JUnit XML for `flakerun.py run --results`, how to run
one test alone (for `--isolated`), how to control order (for `polluter`), and how
to raise the failure rate when deflaking. Prefer the project's own wrapper script
(`npm test`, `make test`) and append these flags to it. Write reports under
`.flake/` so `--results ".flake/*.xml"` finds them.

Turn off retry features while measuring: they turn a 1-in-5 failure into a pass
and hide exactly what you are looking for (`jest.retryTimes`, Vitest `retry`,
`pytest-rerunfailures`/`--reruns`, Surefire `rerunFailingTestsCount`, Gradle
test-retry plugin, Playwright `retries`).

## Python: pytest

- JUnit: `pytest --junitxml=.flake/junit.xml -p no:cacheprovider`
- One test: `pytest "tests/test_cart.py::test_total"`
- Order: pytest runs node ids in the order given, so a `polluter` template is
  `pytest -p no:randomly {tests} --junitxml=.flake/o.xml` (drop `-p no:randomly`
  if pytest-randomly is not installed). List what runs before the victim with
  `pytest --collect-only -q`.
- Stress: shuffle with pytest-randomly (`--randomly-seed=<n>`, reuse a seed to
  reproduce), parallel with pytest-xdist (`-n 8`), repeat in one process with
  pytest-repeat (`--count=20`).
- Ids look like `tests.test_cart::test_total` (classname::name).

## JavaScript / TypeScript

**Vitest**
- JUnit: `npx vitest run --reporter=default --reporter=junit --outputFile.junit=.flake/junit.xml`
- One test: `npx vitest run tests/cart.test.ts -t "total"`
- Stress: `--sequence.shuffle --sequence.seed=<n>`, `--pool=threads`, raise `--maxWorkers`.

**Jest**
- JUnit needs the `jest-junit` reporter (`npm i -D jest-junit` if absent; ask
  before adding a dependency): `JEST_JUNIT_OUTPUT_DIR=.flake npx jest --ci --reporters=default --reporters=jest-junit`
  (with `flakerun.py run --env JEST_JUNIT_OUTPUT_DIR=.flake`).
- One test: `npx jest tests/cart.test.ts -t "total"`
- Stress: `--randomize --seed=<n>` (Jest 29.2+), `--maxWorkers=50%` vs `--runInBand`
  (a test that fails only in parallel shares state through files, ports, or a DB).

**node:test** (Node 20+)
- JUnit: `node --test --test-reporter=junit --test-reporter-destination=.flake/junit.xml`
  (add `--test-reporter=spec --test-reporter-destination=stdout` to keep console output).
- One test: `node --test --test-name-pattern="^total$" test/cart.test.mjs`
- Stress: `--test-randomize --test-random-seed=<n>` (recent Node), `--test-concurrency=<n>`.
- Ids look like `test/cart.test.mjs::cart > total` (file::describe > test).

**Playwright** (end-to-end)
- JUnit: `PLAYWRIGHT_JUNIT_OUTPUT_NAME=.flake/junit.xml npx playwright test --reporter=junit --retries=0`
- Repeat inside one run: `--repeat-each=10`; one test: `npx playwright test cart.spec.ts -g "total"`.

## Go

- No JUnit needed: `go test -json -count=1 ./...` with `flakerun.py run --format go-json`.
  `-count=1` matters: without it Go replays cached results and every run looks identical.
- One test: `go test -json -count=1 -run '^TestTotal$' ./cart`
- Stress: `-race`, `-shuffle=on` (prints the seed; reuse with `-shuffle=<seed>`),
  `-cpu=1,4,8`, `-count=50` inside one process.
- Ids look like `example.com/acme/cart::TestTotal`.

## JVM

**Maven (Surefire)**
- JUnit: written by default to `target/surefire-reports/TEST-*.xml`; run `mvn -q test`.
- One test: `mvn -q test -Dtest=CartTest#total`
- Order: `-Dsurefire.runOrder=random` (seed printed; `-Dsurefire.runOrder.random.seed=<n>`).

**Gradle**
- JUnit: `build/test-results/test/*.xml`; run `./gradlew test --rerun` (or
  `--rerun-tasks` on Gradle < 7.6) so the task is not skipped as up to date.
- One test: `./gradlew test --rerun --tests 'com.acme.CartTest.total'`

## .NET

- JUnit needs the `JunitXml.TestLogger` package in the test project:
  `dotnet test --logger "junit;LogFilePath=.flake/junit.xml"`.
- One test: `dotnet test --filter "FullyQualifiedName~CartTests.Total"`

## Rust

- `cargo test` has no stable JUnit output. Use cargo-nextest with a profile in
  `.config/nextest.toml`: `[profile.flake.junit]` then `path = "junit.xml"`, run
  `cargo nextest run --profile flake`, results in `target/nextest/flake/junit.xml`.
  Disable nextest's own `retries` for that profile.
- One test: `cargo nextest run --profile flake cart::tests::total`
- Without nextest, `flakerun.py` falls back to the exit code, which still works for
  a narrowed single-test command.

## Ruby, PHP

- RSpec: `rspec --format progress --format RspecJunitFormatter --out .flake/rspec.xml`
  (gem `rspec_junit_formatter`); one example: `rspec spec/cart_spec.rb:42`;
  order: `--order rand:<seed>` / `--order defined`; `rspec --bisect` finds polluters natively.
- PHPUnit: `vendor/bin/phpunit --log-junit .flake/junit.xml`; one test:
  `--filter 'CartTest::testTotal'`; order: `--order-by=random --random-order-seed=<n>`.

## Anything else

If the runner cannot write JUnit XML, narrow the command to a single test and let
`flakerun.py` use the exit code. You lose per-test detail, not the verdict.
