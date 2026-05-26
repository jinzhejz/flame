- [x] Review branch diff and identify Python-version regressions
- [x] Fix FLAME_PYTHON_VERSION propagation through flmenv.sh and flmexec
- [x] Make executor-manager Python dependency installation use the requested interpreter
- [x] Align runtime fallback behavior with installed Python SDK versions
- [x] Inspect PR 468 CI failures and fix root causes
- [x] Run targeted local verification
- [x] Document final results
- [x] Simplify Python runtime helper API
- [x] Re-run focused verification after simplification
- [x] Rename Python runtime resolver to `get_python_runtime`
- [x] Re-run focused verification after resolver rename
- [x] Remove host shim Python command assumptions
- [x] Re-run focused verification after host shim simplification
- [x] Rename private Python version helpers to domain terms
- [x] Merge host shim env expansion helpers
- [x] Keep Python runtime discovery out of public Rust SDK exports
- [x] Duplicate Python runtime constants in Rust SDK
- [x] Remove Rust SDK dependency on `common`
- [x] Fix Rust clippy placement issue
- [x] Split Python SDK lint and typecheck targets
- [x] Run Rust, Python, and shell build/lint/format verification

## Review

Implemented fixes:
- Export and propagate `FLAME_PYTHON_VERSION`.
- Resolve Python runtime from the requested value or latest installed Flame SDK.
- Pin executor-manager `uv pip install --target` to the same Python runtime.
- Include resolved Python version in Python app install cache keys.
- Keep host shim command handling generic; app definitions own command/argument semantics.
- Launch built-in `flmrun` through its declared `uv run --python python${FLAME_PYTHON_VERSION}` command and arguments.

PR 468 CI root cause:
- BareMetal Python Test timed out in `test_runner_with_function`.
- Logs showed the app package installed successfully, then Python worker processes exited as defunct with the task still pending.
- The likely cause was app dependencies installed by `uv pip install --target` under an interpreter chosen by uv, while the service launched with `python3`; after the PR installed Python 3.11 and 3.12 SDKs, those could diverge.

Verification:
- `cargo fmt --check`
- `cargo check -p common -p flmadm -p flame-executor-manager -p flmexec`
- `cargo test -p common python`
- `cargo test -p common default_flmrun_uses_env_selected_uv_python`
- `cargo test -p flmadm`
- `cargo test -p flame-executor-manager appmgr`
- `cargo test -p flame-executor-manager expand_command_args_from_launch_env`
- `cargo test -p flmexec script`
- `cargo clippy -p common -p flmadm -p flame-executor-manager -p flmexec -- -D warnings`
- `python3 -m py_compile sdk/python/src/flamepy/runner/runner.py`
- `git diff --check origin/main...HEAD`

Simplification follow-up:
- Collapsed the Python helper exports to `get_python_runtime` and `PythonRuntime`.
- Kept version normalization, installed-version discovery, and site-packages path construction private to `common::python`.
- Renamed private Python helper functions to `version_number` and `minor_version`.
- Removed the host shim Python command rewrite and made command/argument expansion read from the merged launch environment.
- Merged host shim env expansion into one helper with optional launch environment context.
- Kept `flmexec` on the Rust SDK boundary: it reads `FLAME_PYTHON_VERSION` through SDK constants and falls back to `3.12`.
- Duplicated Python runtime constants in `flame-rs` instead of re-exporting them from `common`.
- Removed the remaining `common` dependency from `flame-rs` by localizing the small URI host helper.
- Kept Python runtime discovery out of the public Rust SDK API.
- Updated the built-in `flmrun` app and its e2e assertion to declare the `uv run --python python${FLAME_PYTHON_VERSION}` runtime explicitly.
- Moved the host shim test module after all impl items to satisfy full-workspace clippy.
- Split Python SDK `lint` from `typecheck`; `lint` now covers Ruff format/check, while `typecheck` runs mypy explicitly.
- Verified shell scripts with `bash -n`; `shfmt` and `shellcheck` are not installed in this environment.
