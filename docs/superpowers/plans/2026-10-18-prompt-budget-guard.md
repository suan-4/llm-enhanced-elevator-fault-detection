# Prompt Budget Guard Implementation Plan

> **For agentic workers:** Use executing-plans inline, task by task, with TDD. No automatic production deployment, merge or push. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Reject unsafe/uncalibrated model inputs honestly, reduce duplicated facts, and expose real model participation without changing risk decisions or report templates.

**Architecture:** A local tokenizer and SHA-bound calibration profile enforce the final transmitted text budget; LLMService owns request construction and runtime success checks. Workflow retains grounded facts and fallback, persisting machine-readable status in existing provenance. The preview toolbar renders that status using current styles, outside report paper nodes.

**Tech Stack:** Existing Python/FastAPI/httpx, pinned tokenizers offline runtime, Vue3/TS/Vitest, isolated SQLite tests and Playwright candidate UI checks.

**Spec:** `docs/superpowers/specs/2026-10-17-prompt-budget-guard-design.md`.

**Execution rulings:** Already-approved A and current user's “下一步” authorize the scoped reversible implementation; no repeated approval of the same design. Use a task branch in the existing clean checkout, preserving main and previous performance work; no unrequested extra worktree. SDLC's scoped execution takes precedence over ceremony requiring repeated workspace/execution-choice questions. Board is disconnected initially: no fabricated calibration, board testing or release claims.

**Execution update (2026-10-18):** Board reconnected. Tasks 1–3 implemented with observed RED/GREEN tests. Task 4 isolated board and Chromium checks passed; code review finding fixed/reviewed. Final evidence: `docs/acceptance/2026-10-18-提示词保护验收.md`. No formal release, merge or push. Physical WebKit/touch and this candidate's export regression remain release gates, not claimed complete.

## Task 1: Offline tokenizer and verifiable budget

Files: `backend/app/services/prompt_budget.py`, `backend/tests/test_prompt_budget.py`, `backend/app/config.py`, `backend/tokenizer-requirements.txt`, `backend/app/data/tokenizer-source.json`, `tools/prepare_tokenizer.py`, `tools/calibrate_tokenizer.py`, `.gitignore`.

- [x] Write failing tests for exact local encoding, accepted boundary and one-token-over rejection, missing/corrupt files, SHA/profile/model mismatch, invalid numeric configuration and insufficient calibration evidence.
- [x] Run `.venv/Scripts/python.exe -X utf8 backend/tests/test_prompt_budget.py`, expect missing module/behavior FAIL; implement a lazy local-only `PromptBudget.check(text)->dict` and `verify_model_id(id)` interface. Missing assets/profile fail closed with typed `ModelInputError(code,message)`.
- [x] Use `4096 - 512 - 128 = 3456` text-token budget by default; encode actual final text with no truncation, `add_special_tokens=False`. Profile binds tokenizer SHA, model ID, context size and observed SDK/text differences within reserved overhead. Runtime GET `/v1/models` must match before inference.
- [x] Pin Qwen source revision and file hashes; download only tokenizer/license, never weights. Pin tokenizers distribution and retain offline wheel manifest. Preparation tool validates hashes and never creates a calibrated profile.
- [x] Calibration tool uses `/v1/models` and numeric SDK perf from small synthetic requests, all three report prompt shapes plus bilingual/digit/symbol probes. It writes a profile only when every probe finishes and all differences satisfy bounds. Default no profile if the board is absent; a toy unit fixture is not real calibration.

Example boundary test with real tiny tokenizer fixture:
```python
allowed = budget.check(text_at_limit)
self.assertEqual(allowed['input_tokens'], limit)
with self.assertRaisesRegex(ModelInputError, '预算'):
    budget.check(text_above_limit)
```

## Task 2: Request safety, grounded de-duplication, explicit fallback

Files: `backend/app/services/llm_service.py`, `backend/app/services/report_workflow.py`, `backend/tests/test_model_guard.py`, `backend/tests/test_expert_risk.py`, `backend/tests/test_performance.py`.

- [x] RED tests capture HTTP requests and prove unsafe inputs never POST; safe requests send `max_tokens=512`, count the same content sent, verify model identity and reject empty/SDK-error/non-finished results even with HTTP200.
- [x] Extract pure final-content builder; compact JSON, preserve matching original text and full candidates. Trace records blocked/rejected as error with controlled reason code, not completion latency success; missing SDK remains unavailable, never estimated.
- [x] RED grounded-prompt test checks canonical risk/measure appears once and all fact keys remain. Change overview data to `overview_facts` plus nonduplicate original free-text evidence only; no category/score/measure changes.
- [x] Persist `llm_status=success|degraded|not_requested` and `llm_error_code` alongside existing fields. Overview invalid JSON/unknown keys stays rule fallback; free-text risk matching failure still stops generation and preserves draft.
- [x] Run new tests plus all `backend/tests/test_*.py` as individual scripts (unittest discover alone omits script-style cases).

## Task 3: Existing-style preview status

Files: `web/src/domain/modelStatus.ts`, `.spec.ts`, `web/src/stores/report.ts`, `report.spec.ts`, `web/src/views/ReportView.vue`.

- [x] RED pure-domain/store tests distinguish successful overview, degraded reason, matching-only participation, not-requested, historical unknown and saved-preview/no-new-call.
- [x] Preserve nullable legacy model flag and controlled status/reason in GeneratedInfo; record fresh vs saved view. Render text in `.report-toolbar` existing `.notes`/`role=status`, not `.paper`; no CSS/branding/template changes.
- [x] Verify `npm test -- --run` and `npm run build`; compare login/template files unchanged.

## Task 4: Integration evidence and handoff

Files: `tools/acceptance/prompt_guard_acceptance.py`, `docs/acceptance/2026-10-18-提示词保护验收.md` and numeric artifacts when available.

- [x] Exercise local actual tokenizer assets, plus isolated DB workflow including many risks and extreme input; compare categories/scores/measures to original rules. Controlled transport fixtures are integration contracts, not real model success evidence.
- [x] Browser candidate on isolated local API: fresh and saved status, degradation explanation, no fabricated success; preserve screenshot/DOM evidence. Do not use production accounts/reports.
- [x] If ADB reconnects, calibrate against existing single model without restarting it or altering formal API/data; use isolated candidate for real generation. If absent, leave real calibration and board acceptance explicitly unverified and stop short of enabling a fabricated profile.
- [x] Run fresh tests/build/diff checks, request one independent read-only code review per review skill, address important findings. Record deployment requirements, dependency asset checksums, verified/unverified boundaries; commit locally only, retain branch.
