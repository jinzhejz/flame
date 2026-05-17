# RFE458: Simplify Application Deployment by `flmctl deploy`

GitHub issue: https://github.com/xflops/flame/issues/458

## Summary

Add a parameter-driven `flmctl deploy` command that accepts one local
application path, uploads a normalized package to Flame object cache, detects
the application command and installer when possible, and registers the
application through the existing application API.

The command does not add a new manifest section. It is intentionally centered
on one artifact parameter:

```bash
flmctl deploy --name <app-name> --application <path>
```

`--application` can be:

- an executable binary file
- a `.tar.gz` or `.tgz` package
- a directory

`flmctl deploy` classifies the path, normalizes it into a `.tar.gz` package,
uploads the package to object cache, sets `spec.url`, and renders
`ApplicationAttributes` from parameters plus detection results.

## 1. Motivation

**Background:**

Users currently deploy applications through a multi-step manual flow:

- build an application binary or package
- upload the artifact to object cache
- construct a `grpc://` or `grpcs://` package URL
- decide the right application command and installer
- write application YAML with `spec.url`, `spec.installer`, command,
  arguments, environment, and limits
- run `flmctl register`

That is too much ceremony for the common case. Flame already has the core
pieces: object-cache upload/download, application specs with `url` and
`installer`, and executor-manager package download for installer-backed
applications. The missing piece is one CLI command that wires those pieces
together from a local application path.

There is also a deployment correctness concern to handle while designing this:
executor managers currently cache application installation state by application
name, and package download skips existing filenames. If a user redeploys new
bytes under the same package filename, an executor can continue using stale
content. `flmctl deploy` should generate content-addressed object keys, and the
executor install cache should include the package URL in its identity.

**Target:**

`flmctl deploy` should make the common deployment flow one command:

- Accept a local application path through `--application`.
- Detect whether the path is a binary file, `.tar.gz` package, or directory.
- Detect `command` and `installer` when possible.
- Package or repackage the application into a normalized `.tar.gz`.
- Upload the package to Flame object cache.
- Register the application using CLI parameters plus detected values.
- Avoid introducing a `deploy` manifest section or another YAML schema.
- Avoid generic HTTP/file storage in this command.
- Keep the implementation compatible with existing application registration
  APIs.

Success criteria:

- A user can deploy a Python project directory with:

```bash
flmctl deploy --name image-classifier --application .
```

- A user can deploy an executable binary with:

```bash
flmctl deploy \
  --name candle-based-example \
  --application ./target/release/candle-based-example-service
```

- A user can deploy an existing tar package with:

```bash
flmctl deploy --name batch-worker --application ./dist/batch-worker.tar.gz
```

- The command uploads the normalized package to object cache and registers the
  application with `spec.url` set to the uploaded object-cache URL.
- Re-running deploy after changing the application bytes produces a different
  URL.

## 2. Function Specification

### User Model

`flmctl deploy` is a parameter-driven deployment command. It is not a YAML
replacement for `register`; it is the command users run when the application
can be described by CLI parameters and a local application path.

Required inputs:

- `--name <NAME>`
- `--application <PATH>`

`--application` is classified as:

| Input | Behavior |
|-------|----------|
| Executable file | Pack into `<app-name>.tar.gz` containing `bin/<filename>`, then default `command=<filename>` and `installer=binary`. |
| `.tar.gz` or `.tgz` file | Unpack to a temporary directory for detection, then repackage the detected root into a normalized `.tar.gz`. |
| Directory | Detect from the directory, then package the directory into a normalized `.tar.gz`. |

Generated output:

- detected application kind
- detected or overridden command
- detected or overridden installer
- object-cache key in the package namespace
- `grpc://` or `grpcs://` package URL
- registered application spec

### Detection Rules

Detection fills omitted values. Explicit CLI parameters take precedence over
detected values.

Command override:

- `--command <COMMAND>` overrides the detected command.
- repeated `--argument <ARG>` overrides detected arguments when `--command` is
  provided.

Installer override:

- `--installer <TYPE>` overrides the detected installer.
- Supported installer types for this design are `binary` and `python`.

Detection output:

```rust
struct DetectedApplication {
    installer: String,
    command: String,
    arguments: Vec<String>,
}
```

Executable file detection:

- A regular executable file is treated as a binary application.
- The package layout is normalized to:

```text
bin/<filename>
```

- Detected installer: `binary`
- Detected command: `<filename>`
- Detected arguments: `[]`

Directory and tarball detection:

1. If the detection root has a Python project marker, detect a Python
   application.
2. Otherwise, if it has an executable bundle marker, detect a binary
   application.
3. Otherwise, fail with a message asking the user to pass `--command` and
   `--installer`.

Python project markers:

- `pyproject.toml`
- `setup.py`
- `setup.cfg`

Python command detection:

1. If `pyproject.toml` has `[project.scripts]` and exactly one script, use that
   script name as the command.
2. If `[project.scripts]` contains a script whose name matches `--name`, use
   that script.
3. If a Python package matching the normalized application name has
   `__main__.py`, use `command=python` and `arguments=["-m", "<module>"]`.
4. If command detection is ambiguous, fail and ask the user to pass
   `--command` and `--argument`.

Detected installer for Python projects: `python`.

Binary bundle markers:

- `bin/<name>` where `<name>` matches `--name`
- exactly one executable file under `bin/`
- exactly one executable file at the root

Binary command detection:

- For `bin/<name>`, use command `<name>` because `BinaryInstaller` prepends the
  extracted `bin/` directory to `PATH`.
- For a root executable, use the executable filename.
- If multiple executable candidates exist, fail and ask the user to pass
  `--command`.

Detected installer for binary bundles: `binary`.

Tarball root handling:

- `flmctl deploy` unpacks `.tar.gz` and `.tgz` inputs into a temporary
  directory.
- If the tarball contains exactly one top-level directory, that directory is
  the detection root.
- Otherwise, the temporary extraction root is the detection root.
- After detection, `flmctl deploy` repackages the detection root into a
  normalized `.tar.gz` before upload. This keeps executor-side package layout
  consistent across binary files, tarballs, and directories.

### Object Cache URL

`flmctl deploy` uploads the normalized `.tar.gz` package to Flame object cache
using the current context's cache endpoint:

```yaml
cache:
  endpoint: grpc://flame-object-cache:9090
```

No cache endpoint CLI override is provided. Users select the target object
cache by selecting the current Flame context.

Object keys use the RFE429 package namespace:

```text
<application-name>/pkg/<filename>
```

Directory and tarball filenames are content-addressed:

```text
<application-name>-<sha256-16>.tar.gz
```

Executable-file archives are created as `<application-name>.tar.gz`, while the
object id remains content-addressed and still uses the same three-part object
key shape as FlamePy and object-cache:

```text
<application-name>/pkg/<application-name>-<sha256-16>.tar.gz
```

Generated URLs:

```text
grpc://flame-object-cache:9090/image-classifier/pkg/image-classifier-82e0f0d2d68f9341.tar.gz
grpcs://cache.example.com:9090/candle-based-example/pkg/candle-based-example-953bf914bd839f80.tar.gz
```

The object-cache upload uses the Rust SDK object helper API. The object is
stored as raw package bytes through the existing object-cache protocol, matching
the Python `upload_object()` behavior.

### CLI

New command:

```bash
flmctl deploy [OPTIONS]
```

Artifact and cache options:

| Option | Description |
|--------|-------------|
| `--name <NAME>` | Application name. Required. |
| `--application <PATH>` | Application path. Required. Can be an executable file, `.tar.gz`/`.tgz`, or directory. |
| `--dry-run` | Render the deploy plan without uploading or writing to the cluster. |
| `-o, --output <FORMAT>` | `summary`, `yaml`, or `json`. Default: `summary`. |

Application registration parameters:

| Option | Description |
|--------|-------------|
| `--shim <Host|Wasm>` | Application shim. Default: `Host`. |
| `--image <IMAGE>` | Optional runtime image. |
| `--description <TEXT>` | Application description. |
| `--label <LABEL>` | Application label. Repeatable. |
| `--command <COMMAND>` | Application command. Overrides detected command. |
| `--argument <ARG>` | Add one command argument. Repeatable. |
| `--env <NAME=VALUE>` | Add one environment variable. Repeatable. |
| `--working-directory <DIR>` | Runtime working directory. |
| `--max-instances <N>` | Application maximum instances. |
| `--delay-release <SECONDS>` | Application delay-release value. |
| `--installer <TYPE>` | Installer type. Overrides detected installer. |
| `--schema-input <SCHEMA>` | Optional input schema string. |
| `--schema-output <SCHEMA>` | Optional output schema string. |
| `--schema-common-data <SCHEMA>` | Optional common-data schema string. |

Dry-run behavior:

- validates CLI parameters
- validates and classifies the application path
- detects command and installer
- resolves the cache endpoint
- computes the package object key and target object-cache URL
- renders the application spec that would be sent
- does not upload bytes
- does not call the application API

Exit codes:

| Code | Meaning |
|------|---------|
| `0` | Success. |
| `1` | Invalid CLI arguments or context. |
| `2` | Application validation, detection, or packaging failed. |
| `3` | Object-cache upload failed. |
| `4` | Application API request failed. |

### Rendered Application Spec

The command builds `ApplicationAttributes` from parameters and detection
results.

Python directory example:

```bash
flmctl deploy --name image-classifier --application .
```

If the directory contains `pyproject.toml` with one project script named
`image-classifier`, `flmctl deploy` registers the equivalent of:

```yaml
metadata:
  name: image-classifier
spec:
  shim: Host
  command: image-classifier
  installer: python
  url: grpc://flame-object-cache:9090/image-classifier/pkg/image-classifier-82e0f0d2d68f9341.tar.gz
```

Executable file example:

```bash
flmctl deploy \
  --name candle-based-example \
  --application ./target/release/candle-based-example-service
```

`flmctl deploy` registers the equivalent of:

```yaml
metadata:
  name: candle-based-example
spec:
  shim: Host
  command: candle-based-example-service
  installer: binary
  url: grpc://flame-object-cache:9090/candle-based-example/pkg/candle-based-example-953bf914bd839f80.tar.gz
```

Tarball example with overrides:

```bash
flmctl deploy \
  --name image-classifier \
  --application ./dist/image-classifier.tar.gz \
  --installer python \
  --command python \
  --argument -m \
  --argument image_classifier.service
```

Explicit command and installer values override detection.

### Installer Behavior

`installer: python`

- Existing behavior from RFE420.
- Executor manager downloads and extracts the package, then runs the Python
  installer through `uv`.
- To support detected Python project scripts, `PythonInstaller` should prepend
  the app dependency `bin/` directory to `PATH` when it exists.

`installer: binary`

- New installer type for executable binaries and self-contained bundles.
- Executor manager downloads and extracts the package.
- No language package installation is run.
- Returned environment variables:
  - `FLAME_APP_DIR=<release>/src`
  - `PATH=<release>/src/bin:<release>/src:$PATH`
  - `LD_LIBRARY_PATH=<release>/src/libs:$LD_LIBRARY_PATH`

`flmctl deploy` must not register an uploaded package without an installer.
If `--installer` is omitted and detection cannot infer one, the command fails.

### API

No new session-manager API is required.

`flmctl deploy` uses the existing `register_application(name, attributes)`
API. If an application with the same name already exists, the command returns
the existing registration error. Users who need to change an existing
application continue to use the existing update flow.

`ApplicationSpec.url` stores the object-cache package URL.
`ApplicationSpec.installer` stores the selected or detected installer type.

### Scope

**In Scope:**

- `flmctl deploy` CLI command
- single `--application <PATH>` artifact input
- parameter-driven application registration
- directory detection and packaging
- tarball unpacking for detection and normalized repackaging
- executable file packaging into `.tar.gz`
- object-cache upload through `grpc://` and `grpcs://`
- content-addressed object-cache keys
- command and installer detection
- `binary` installer for executable binaries and self-contained artifacts
- executor install identity keyed by application name, installer, and URL
- dry-run output

**Out of Scope:**

- a new `deploy` section in application YAML
- generic `file://`, `http://`, or `https://` storage upload
- container image build/push
- package garbage collection in object cache
- rollback command
- multi-artifact application deployment
- signing or signature verification
- source builds; `--application` must point at runnable source/package content
  or an already-built binary

**Limitations:**

- The first implementation depends on an accessible Flame object cache.
- Binary-file deployment assumes the binary is already built for executor
  nodes.
- Detection is intentionally conservative. Ambiguous applications require
  explicit `--command`, `--argument`, or `--installer`.
- Updating an application does not affect sessions that are already bound.
- Package garbage collection remains a future operation.

### Feature Interaction

**Related Features:**

- `flmctl register`: remains the YAML registration command.
- `flmctl update`: remains the YAML update command.
- RFE420 application installer: deploy uses installer-backed package download.
- RFE429 cache upload/download: deploy uses the same object-cache key format
  and URL scheme.

**Compatibility:**

- Existing application YAML stays unchanged.
- Existing `flmctl register` and `flmctl update` behavior stays unchanged.
- Existing `installer: python` behavior stays unchanged, except for the
  additive `PATH` entry when Python scripts are installed.
- Existing applications without uploaded artifacts are unaffected.
- Existing applications with the same name are not modified by `flmctl deploy`.

**Breaking Changes:**

None for public control APIs or existing CLI commands.

## 3. Implementation Detail

### Architecture

```text
flmctl deploy
    |
    +-- parse CLI parameters
    +-- load current Flame context
    +-- resolve object-cache endpoint
    +-- classify --application path
    +-- unpack tarball if needed
    +-- detect command and installer
    +-- apply explicit CLI overrides
    +-- create normalized .tar.gz package
    +-- compute sha256 and package object key
    +-- upload package to object cache through flame-rs object helpers
    +-- build ApplicationAttributes
    +-- dry-run output or register application
```

Executor install path:

```text
executor binds a session
    |
    +-- receives ApplicationContext { name, url, installer }
    +-- build InstallKey { name, installer, url }
    +-- reuse matching install or install a new release
    +-- download package from object cache URL
    +-- extract to content-addressed release directory
    +-- run selected installer
    +-- return env vars to shim
```

### Components

`flmctl/src/main.rs`

- Add `Deploy(deploy::Options)` subcommand.

`flmctl/src/deploy.rs`

- Own CLI options and command orchestration.
- Build the deploy plan from parameters and detection results.
- Render `ApplicationAttributes`.
- Call `register_application`.

`flmctl/src/deploy/artifact.rs`

- Classify `--application` as executable file, tarball, or directory.
- Safely unpack `.tar.gz` and `.tgz` inputs for detection.
- Create normalized `.tar.gz` packages.
- Compute SHA-256 digests.
- Produce package filenames and object keys.

`flmctl/src/deploy/detect.rs`

- Detect Python project markers.
- Parse `pyproject.toml` for `[project.scripts]`.
- Detect executable bundle markers.
- Return `DetectedApplication`.

`sdk/rust/src/object.rs`

- Provide `upload_object_with_context` for package upload.
- Use object-cache `ObjectRef` metadata from the upload response.
- Share TLS handling with the current Flame context where possible.

`flmctl/src/deploy/render.rs`

- Merge CLI parameters with `DetectedApplication`.
- CLI values override detection.
- Convert the merged result into `ApplicationAttributes`.
- Validate command/installer combinations.

`executor_manager/src/appmgr/installer.rs`

- Add `InstallerType::Binary`.
- Accept `binary` in `FromStr`.
- Update supported-installer error text.

`executor_manager/src/appmgr/binary.rs`

- Implement `BinaryInstaller`.
- Return `FLAME_APP_DIR`, `PATH`, and `LD_LIBRARY_PATH`.
- Add the extracted package `bin/` directory to `PATH`.
- Add the extracted package `libs/` directory to `LD_LIBRARY_PATH`.
- Merge application-provided environment variables consistently with existing
  installer behavior.

`executor_manager/src/appmgr/python.rs`

- Preserve existing Python installer behavior.
- Add the app dependency `bin/` directory to `PATH` when present so detected
  `pyproject.toml` scripts can run by command name.

`executor_manager/src/appmgr/mod.rs`

- Change installed app identity from application name only to:

```rust
#[derive(Clone, Debug, Eq, PartialEq, Hash)]
struct InstallKey {
    app_name: String,
    installer: String,
    url: Option<String>,
}
```

- Use URL/content-addressed release paths:

```text
$FLAME_HOME/data/apps/<app-name>/releases/<url-digest>/src
$FLAME_HOME/data/apps/<app-name>/releases/<url-digest>/download/<filename>
```

- Keep the per-install lock so concurrent binds for the same release install
  once.

### Data Structures

Deploy plan:

```rust
#[derive(Debug, Clone)]
struct DeployPlan {
    app_name: String,
    cache_endpoint: CacheEndpoint,
    input: ApplicationInput,
    detected: DetectedApplication,
    application: ApplicationSpecParams,
    output: OutputFormat,
    dry_run: bool,
}

#[derive(Debug, Clone)]
struct ApplicationInput {
    original_path: PathBuf,
    kind: ApplicationInputKind,
    detection_root: PathBuf,
}

#[derive(Debug, Clone, Copy)]
enum ApplicationInputKind {
    ExecutableFile,
    TarGz,
    Directory,
}

#[derive(Debug, Clone)]
struct DetectedApplication {
    installer: String,
    command: String,
    arguments: Vec<String>,
}

```

Uploaded package:

```rust
#[derive(Debug, Clone)]
struct UploadedPackage {
    key: String,
    url: String,
    filename: String,
    sha256: String,
    local_path: PathBuf,
}
```

Application parameters:

```rust
#[derive(Debug, Clone)]
struct ApplicationSpecParams {
    shim: Option<Shim>,
    image: Option<String>,
    description: Option<String>,
    labels: Vec<String>,
    command: Option<String>,
    arguments: Vec<String>,
    environments: HashMap<String, String>,
    working_directory: Option<String>,
    max_instances: Option<u32>,
    delay_release: Option<Duration>,
    schema: Option<ApplicationSchema>,
    installer: Option<String>,
}
```

### Algorithms

**Deploy plan construction:**

1. Parse CLI parameters.
2. Validate `--name`.
3. Validate `--application`.
4. Load current `FlameContext`.
5. Resolve cache endpoint from context `cache.endpoint`.
6. Validate cache endpoint scheme is `grpc` or `grpcs`.
7. Classify the application input.
8. Detect command and installer.
9. Apply explicit CLI overrides.
10. Validate the merged command and installer.
11. Produce a `DeployPlan`.

**Application path classification:**

1. If the path is a directory, classify as `Directory`.
2. If the path is a `.tar.gz` or `.tgz` file, classify as `TarGz`.
3. If the path is a regular executable file, classify as `ExecutableFile`.
4. Otherwise, return `InvalidConfig`.

**Tarball handling:**

1. Unpack into a temporary directory.
2. Reject archive entries with absolute paths or `..` traversal.
3. Pick the single top-level directory as detection root when there is exactly
   one; otherwise use the temporary extraction root.
4. Detect command and installer from the detection root.
5. Repackage the detection root as a normalized `.tar.gz`.

**Directory handling:**

1. Detect command and installer from the directory.
2. Package the directory as a normalized `.tar.gz`.
3. Reject symlinks that resolve outside the directory.
4. Store only relative archive paths.

**Executable-file handling:**

1. Validate the file exists.
2. On Unix, validate at least one executable bit is set.
3. Create a normalized `<app-name>.tar.gz` containing `bin/<filename>`.
4. Preserve executable mode in the tar entry.
5. Detect `installer=binary`, `command=<filename>`, `arguments=[]`.

**Object cache upload:**

1. Compute SHA-256 over the normalized `.tar.gz` bytes.
2. For executable-file input, create archive `<app-name>.tar.gz` and upload it
   under object key `<app>/pkg/<app-name>-<sha256-16>.tar.gz`.
3. For directory and tarball input, build filename
   `<app-name>-<sha256-16>.tar.gz` and object key `<app>/pkg/<filename>`.
4. Upload package bytes through `flame-rs` object helpers.
5. Use raw bytes, not serde/cloudpickle encoding.
6. Return object-cache URL `<scheme>://<host>:<port>/<key>`.

**Application write:**

1. Build `ApplicationAttributes` from CLI parameters and detection results.
2. Set `url` to the uploaded package URL.
3. Set `installer` to the selected or detected installer.
4. Set `command` and `arguments` to explicit overrides or detected values.
5. If `--dry-run`, print the rendered result and return.
6. Call `register_application`.

### System Considerations

**Performance:**

- Hashing and upload should stream package bytes rather than reading large
  artifacts fully into memory.
- Tarball and directory inputs are normalized into one temporary `.tar.gz`
  before upload.
- Object-cache upload is client-side work and does not add control-plane load
  beyond the final application API call.

**Scalability:**

- Content-addressed keys avoid overwriting package objects.
- Repeated deploys of identical normalized bytes reuse the same key.
- Executor installation remains node-local.

**Reliability:**

- The application API call happens only after upload succeeds.
- A failed API call can leave an unused object-cache package; cleanup is out of
  scope.
- Executor install identity includes URL so a new deploy does not reuse an old
  in-memory install.

**Security:**

- `flmctl deploy` does not execute uploaded artifacts locally.
- Packaging must store relative archive paths only.
- Tarball unpacking and executor extraction must reject absolute paths and
  `..` traversal.
- Directory packaging must reject symlinks that escape the application root.
- `grpcs://` should honor current TLS configuration.

**Observability:**

- Summary output includes app name, input kind, detected installer, detected
  command, object key, URL, and digest.
- JSON output is suitable for CI.
- Dry-run output clearly marks that no upload happened.
- Executor logs include install key, package URL, release path, and installer
  type.

**Operational:**

- Object-cache package garbage collection is future work.
- Content-addressed package names make repeated deployments auditable.
- Existing applications are not mutated by `flmctl deploy`; registration
  conflict errors are surfaced directly.

### Dependencies

Potential `flmctl` dependencies:

- `tar` and `flate2` for package creation and tarball inspection
- `sha2` for package digests
- `toml` for `pyproject.toml` detection
- existing `flame-rs` object helper support for object-cache upload

Potential executor dependencies:

- No new archive dependencies are needed if existing `tar`, `flate2`, and
  `zip` usage remains.

### Verification Plan

Unit tests:

- CLI requires `--name`.
- CLI requires `--application`.
- cache endpoint resolution from context.
- missing cache endpoint returns an invalid-config error.
- cache endpoint rejects non-`grpc`/`grpcs` schemes.
- executable-file classification.
- `.tar.gz` and `.tgz` classification.
- directory classification.
- tarball unpack rejects path traversal.
- directory packaging rejects symlinks outside the root.
- executable file package layout and executable mode preservation.
- Python project detection from `pyproject.toml`.
- Python command detection from `[project.scripts]`.
- binary bundle detection from `bin/`.
- ambiguous detection asks for explicit command or installer.
- explicit `--command`, `--argument`, and `--installer` override detection.
- normalized package digest, filename, and object-key generation.
- rendered `ApplicationAttributes` contains uploaded URL and selected
  installer.
- application registration call path.
- `binary` installer environment variables.
- Python installer adds dependency `bin/` to `PATH` when present.
- executor install key changes when URL changes.

Integration tests:

- `flmctl deploy --dry-run -o yaml` renders expected application YAML without
  upload.
- `flmctl deploy --dry-run -o json` renders expected machine-readable plan.
- object-cache upload writes the normalized package to a local
  flame-object-cache when the test environment provides one.
- executor manager installs two different object-cache URLs for the same
  application name as two different releases.

Manual verification:

```bash
cargo fmt --all -- --check
cargo check -p flmctl
cargo test -p flmctl deploy
cargo test -p flame-executor-manager appmgr
git diff --check
```

## 4. Use Cases

### Example 1: Deploy a Python Project Directory

Command:

```bash
flmctl deploy --name image-classifier --application .
```

Workflow:

1. `flmctl` detects a Python project from `pyproject.toml`.
2. `flmctl` detects the command from `[project.scripts]`.
3. `flmctl` packages the directory as a normalized `.tar.gz`.
4. `flmctl` uploads it to object cache under
   `image-classifier/pkg/image-classifier-<sha>.tar.gz`.
5. `flmctl` registers `image-classifier` with `installer=python` and the
   generated `grpc://` URL.

Expected outcome:

- The application is registered without manual object-cache upload or YAML.

### Example 2: Deploy a Rust Binary File

Command:

```bash
flmctl deploy \
  --name candle-based-example \
  --application ./target/release/candle-based-example-service
```

Workflow:

1. `flmctl` detects an executable file.
2. `flmctl` creates `candle-based-example.tar.gz` containing
   `bin/candle-based-example-service`.
3. `flmctl` uploads the normalized package to object cache.
4. `flmctl` registers the application with `command:
   candle-based-example-service` and `installer: binary`.
5. Executor manager extracts the package, prepends the extracted `bin/`
   directory to `PATH`, and adds extracted `libs/` to `LD_LIBRARY_PATH`.

Expected outcome:

- A self-contained executable binary is deployable with one command.

### Example 3: Deploy an Existing Tarball

Command:

```bash
flmctl deploy \
  --name batch-worker \
  --application ./dist/batch-worker.tar.gz
```

Workflow:

1. `flmctl` unpacks the tarball into a temporary directory.
2. `flmctl` detects command and installer from the extracted package.
3. `flmctl` repackages the detected root as a normalized `.tar.gz`.
4. `flmctl` uploads the package to a content-addressed object-cache key.
5. `flmctl` registers the application with the generated URL.

Expected outcome:

- A tarball package is registered without manual object-cache URL construction.

### Example 4: Override Detection

Command:

```bash
flmctl deploy \
  --name image-classifier \
  --application ./dist/image-classifier.tar.gz \
  --installer python \
  --command python \
  --argument -m \
  --argument image_classifier.service
```

Workflow:

1. `flmctl` unpacks and inspects the tarball.
2. Explicit `--installer`, `--command`, and `--argument` values override
   detection.
3. `flmctl` uploads the normalized package and registers the application.

Expected outcome:

- Users can deploy ambiguous packages without writing YAML.

### Example 5: Dry Run

Command:

```bash
flmctl deploy \
  --name image-classifier \
  --application ./dist/image-classifier.tar.gz \
  --dry-run \
  -o yaml
```

Workflow:

1. `flmctl` validates parameters and classifies the application path.
2. `flmctl` detects command and installer.
3. `flmctl` computes the target object key and URL.
4. `flmctl` prints the application spec that would be registered.
5. No upload or application API write occurs.

Expected outcome:

- Users can review the deploy result before changing the cluster.

## 5. References

Related documents:

- [RFE420: Application Installer in Executor Manager](../RFE420-app-installer/FS.md)
- [RFE429: Support Upload/Download in flame-object-cache](../RFE429-cache-upload-download/FS.md)

Implementation references:

- `flmctl/src/main.rs`
- `flmctl/src/register.rs`
- `sdk/rust/src/apis/ctx.rs`
- `sdk/python/src/flamepy/core/cache.py`
- `executor_manager/src/appmgr/mod.rs`
- `executor_manager/src/appmgr/installer.rs`
- `executor_manager/src/appmgr/downloader.rs`
