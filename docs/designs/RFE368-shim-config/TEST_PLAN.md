# Test Plan: Configure Shim in ExecutorManager Instead of Application

**Issue:** [xflops/flame#368](https://github.com/xflops/flame/issues/368)
**HLD Reference:** [FS.md](FS.md)
**Author:** QA
**Date:** 2026-03-10
**Status:** Draft
**Revision:** 2 (Enhanced coverage for backward compatibility and CLI changes)

## 1. Scope

### In Scope
- Deprecation of `shim` field in `ApplicationSpec` protobuf message
- Removal of `shim` from `ApplicationContext` protobuf message
- Updates to `common/src/apis.rs` removing shim from Application-related structs
- Executor-manager shim selection from `FlameExecutors.shim` configuration only
- CLI (`flmctl`) changes: removal of shim column from list/view commands
- CLI (`flmctl register`) deprecation warning for shim field in YAML
- Shim selection logic changes in `executor_manager/src/shims/mod.rs`
- Backward compatibility with existing applications and YAML files
- Wire compatibility with protobuf reserved fields

### Out of Scope
- Per-session or per-task shim configuration
- Supporting multiple shim types on the same executor-manager
- Dynamic shim switching at runtime
- Python SDK changes (deferred - see Note below)
- Rust SDK changes (deferred)

> **Note:** Existing E2E tests (`e2e/tests/test_application.py`) use `shim` in `ApplicationAttributes`. 
> These tests will need updates when SDK changes are implemented in a future phase.

## 2. Test Strategy

### Test Types
- [x] Functional Testing
- [x] Integration Testing
- [x] Regression Testing
- [x] Backward Compatibility Testing
- [ ] Performance Testing (not applicable)
- [ ] Security Testing (not applicable)

### Test Environment
- **Environment:** Docker Compose dev cluster / Local development
- **Components:** flame-session-manager, flame-executor-manager, flmctl
- **Dependencies:** SQLite database, gRPC services

## 3. Use Case Coverage

| Use Case | Test Scenarios | Priority |
|----------|----------------|----------|
| UC1: Application Registration (No Shim) | 3 scenarios | High |
| UC2: Application Registration (Deprecated Shim) | 3 scenarios | High |
| UC3: Executor-Manager Shim Configuration | 4 scenarios | High |
| UC4: CLI List/View Commands | 5 scenarios | Medium |
| UC5: Task Execution with Configured Shim | 3 scenarios | High |
| UC6: Backward Compatibility | 4 scenarios | High |
| UC7: Observability | 2 scenarios | Medium |

## 4. Test Scenarios

### UC1: Application Registration (No Shim)

| ID | Scenario | Type | Priority |
|----|----------|------|----------|
| TC-001 | Register application without shim field in YAML - succeeds | Functional | High |
| TC-002 | Register application with minimal spec (name, command only) | Functional | High |
| TC-003 | Register application with full spec (image, command, args, env) without shim | Functional | Medium |

### UC2: Application Registration (Deprecated Shim)

| ID | Scenario | Type | Priority |
|----|----------|------|----------|
| TC-004 | Register application with `shim: host` in YAML - shows deprecation warning | Functional | High |
| TC-005 | Register application with `shim: wasm` in YAML - shows deprecation warning, shim ignored | Functional | High |
| TC-006 | Deprecation warning message contains guidance to use executor-manager config | Functional | Medium |

### UC3: Executor-Manager Shim Configuration

| ID | Scenario | Type | Priority |
|----|----------|------|----------|
| TC-007 | Executor-manager with `executors.shim: host` - uses Host shim for all tasks | Integration | High |
| TC-008 | Executor-manager with `executors.shim: wasm` - uses Wasm shim for all tasks | Integration | High |
| TC-009 | Executor-manager with no shim config - defaults to Host shim | Edge Case | High |
| TC-010 | Executor-manager config change requires restart to take effect | Integration | Medium |

### UC4: CLI List/View Commands

| ID | Scenario | Type | Priority |
|----|----------|------|----------|
| TC-011 | `flmctl list application` - output does NOT contain SHIM column | Functional | High |
| TC-012 | `flmctl view application <name>` - output does NOT show shim field | Functional | High |
| TC-013 | `flmctl list application` - shows NAME, IMAGE, COMMAND columns correctly | Functional | Medium |
| TC-014 | `flmctl view application` - shows all other fields (description, image, command, args, env) | Functional | Medium |
| TC-015 | `flmctl list application` - column alignment and formatting is correct | Functional | Low |

### UC5: Task Execution with Configured Shim

| ID | Scenario | Type | Priority |
|----|----------|------|----------|
| TC-016 | Submit task to session - executor uses shim from executor-manager config, not from app | Integration | High |
| TC-017 | Application registered with `shim: wasm`, executor config `shim: host` - task runs with Host shim | Integration | High |
| TC-018 | Task execution logs show shim type from executor-manager config | Integration | Medium |

### UC6: Backward Compatibility

| ID | Scenario | Type | Priority |
|----|----------|------|----------|
| TC-019 | Existing applications in database (with shim) - continue to work after upgrade | Regression | High |
| TC-020 | Old YAML files with shim field - can still be registered with warning | Regression | High |
| TC-021 | Protobuf wire compatibility - old clients can communicate with new server | Regression | High |
| TC-022 | Protobuf wire compatibility - new clients can communicate with old server (reserved fields) | Regression | High |

### UC7: Observability

| ID | Scenario | Type | Priority |
|----|----------|------|----------|
| TC-023 | Executor-manager startup logs show configured shim type | Functional | Medium |
| TC-024 | Task execution logs indicate which shim is being used | Functional | Medium |

## 5. Test Data Requirements

| Data Type | Description | Source |
|-----------|-------------|--------|
| Application YAML (no shim) | Valid application spec without shim field | Create new test fixture |
| Application YAML (with shim) | Legacy application spec with shim field | Create new test fixture |
| Executor-manager config (host) | flame-cluster.yaml with `executors.shim: host` | Modify existing config |
| Executor-manager config (wasm) | flame-cluster.yaml with `executors.shim: wasm` | Modify existing config |
| Executor-manager config (no shim) | flame-cluster.yaml without `executors.shim` | Modify existing config |
| Pre-existing database | SQLite DB with applications containing shim field | Create migration test fixture |

### Sample Test Data

**Application YAML (No Shim) - `test-app-no-shim.yaml`:**
```yaml
metadata:
  name: test-app-no-shim
spec:
  image: python:3.11
  command: python
  arguments: ["-c", "print('hello')"]
```

**Application YAML (Deprecated Shim) - `test-app-with-shim.yaml`:**
```yaml
metadata:
  name: test-app-with-shim
spec:
  shim: host  # Deprecated field
  image: python:3.11
  command: python
  arguments: ["-c", "print('hello')"]
```

**Application YAML (Wasm Shim - Deprecated) - `test-app-wasm-shim.yaml`:**
```yaml
metadata:
  name: test-app-wasm-shim
spec:
  shim: wasm  # Deprecated field - will be ignored
  image: python:3.11
  command: python
  arguments: ["-c", "print('hello')"]
```

## 6. Dependencies & Risks

### Dependencies
- Docker Compose environment or local development setup
- flame-session-manager service running
- flame-executor-manager service running
- flmctl CLI built and available

### Risks
| Risk | Impact | Mitigation | Test Coverage |
|------|--------|------------|---------------|
| Protobuf changes break existing clients | High | Test with reserved fields, verify wire compatibility | TC-021, TC-022 |
| CLI output format change breaks scripts | Medium | Document output format changes in release notes | TC-011, TC-012, TC-015 |
| Executor-manager config not read correctly | High | Add unit tests for config parsing | TC-007, TC-008, TC-009 |
| Existing applications fail after upgrade | High | Test database migration scenarios | TC-019 |
| Deprecation warning not visible to users | Medium | Verify warning goes to stderr | TC-004, TC-005, TC-006 |

## 7. Schedule

| Phase | Start | End | Status |
|-------|-------|-----|--------|
| Test Plan Review | TBD | TBD | Draft |
| Test Execution (CI) | TBD | TBD | Pending |
| Defect Resolution | TBD | TBD | Pending |

## 8. Exit Criteria

- [ ] All high-priority test cases executed via CI
- [ ] No critical or high severity defects open
- [ ] All use cases from HLD validated
- [ ] CLI output format verified (no SHIM column)
- [ ] Deprecation warning verified for legacy YAML files
- [ ] Deprecation warning contains guidance message
- [ ] Executor-manager shim selection from config verified
- [ ] Backward compatibility verified (existing apps, old YAML files)
- [ ] Wire compatibility verified (protobuf reserved fields)
- [ ] Startup logging verified (shim type displayed)
- [ ] Test report submitted

## 9. Test Execution Notes

### Pre-requisites
1. Rebuild cluster after code changes: `docker compose build && docker compose up -d`
2. Verify services are healthy: `docker compose ps`
3. Clear any existing test applications: `flmctl delete application <name>`

### Verification Commands
```bash
# Verify CLI output format (TC-011, TC-013)
flmctl list application

# Verify application registration without shim (TC-001)
flmctl register application -f test-app-no-shim.yaml

# Verify deprecation warning and guidance message (TC-004, TC-006)
flmctl register application -f test-app-with-shim.yaml 2>&1 | grep -i "deprecated"
flmctl register application -f test-app-with-shim.yaml 2>&1 | grep -i "executor-manager"

# Verify view command (TC-012, TC-014)
flmctl view application test-app-no-shim

# Verify startup logs show shim type (TC-023)
docker logs flame-executor-manager 2>&1 | grep -i "shim"

# Verify task execution uses correct shim (TC-016, TC-018)
# Submit task and check executor-manager logs for shim type
```

### Backward Compatibility Testing (TC-019, TC-021, TC-022)
```bash
# 1. Create a database backup with existing applications (pre-upgrade)
# 2. Apply code changes and rebuild
# 3. Verify existing applications still work
# 4. Verify tasks execute with executor-manager's configured shim

# For wire compatibility:
# 1. Start old server version
# 2. Use new client to register application
# 3. Verify no errors (reserved fields handled gracefully)
```

## 10. Traceability Matrix

| HLD Section | Test Cases |
|-------------|------------|
| API Changes (ApplicationSpec) | TC-001, TC-002, TC-003, TC-004, TC-005, TC-006 |
| API Changes (ApplicationContext) | TC-016, TC-017, TC-018 |
| CLI Changes (list/view) | TC-011, TC-012, TC-013, TC-014, TC-015 |
| CLI Changes (register warning) | TC-004, TC-005, TC-006, TC-020 |
| Executor-Manager Shim Selection | TC-007, TC-008, TC-009, TC-010, TC-016, TC-017 |
| Backward Compatibility (Phase 1) | TC-019, TC-020, TC-021, TC-022 |
| Observability | TC-023, TC-024 |
| Use Case 1 (Basic Registration) | TC-001, TC-002, TC-003 |
| Use Case 2 (Migration from Old Config) | TC-004, TC-005, TC-006, TC-020 |
| Use Case 3 (Different Shim Types) | TC-007, TC-008, TC-017 |

## 11. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1 | 2026-03-10 | QA | Initial test plan |
| 2 | 2026-03-10 | QA | Enhanced coverage: added TC-006 (deprecation guidance), TC-010 (restart requirement), TC-015 (formatting), TC-018 (execution logs), TC-021/TC-022 (wire compatibility), TC-023/TC-024 (observability); renumbered test cases; added UC7 (Observability); updated exit criteria |
