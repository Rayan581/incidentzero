# AI Assistance Declaration

**Name:** Rayan  
**Roll Number:** 23I-0018

---

## Tools used

- Antigravity IDE (Google DeepMind) — AI coding assistant used during implementation

---

## What I used them for

- **Architecture exploration**: Used the AI assistant to help navigate the starter code structure and understand the relationships between components (engine, registry, controller, planner, policies).
- **Code scaffolding**: The assistant generated initial implementations for `RetryPolicy`, `LoopGuard`, `ReplanPolicy`, and the controller pipeline based on the `TODO(A1)` markers and test specifications.
- **Test design**: Suggested test cases covering edge cases (stale world, approval denial, exponential backoff timing), which I then reviewed and adapted to match the actual simulator behavior.
- **Debugging**: When `test_plan_revision_fallback_on_model_error` failed due to `RuntimeError` not being caught, the assistant identified that `ScriptedModelClient` raises a plain `RuntimeError` rather than a `TransientModelError`, leading to the broadened exception handler.

---

## Two suggestions I rejected or changed

1. **Using `tenacity` for retry logic**: The assistant initially suggested wrapping retries with the `tenacity` library (which is in `requirements.txt`). I rejected this in favor of a manual implementation because (a) `tenacity` is a high-level framework that would obscure what `RetryPolicy.call_model()` does, (b) the assignment grader tests the precise behavior of `RetryPolicy` directly, and (c) using a raw loop makes the exponential backoff timing transparent and directly testable with the injected `sleeper` callable.

2. **Broad `except Exception` in all model call wrappers**: The assistant originally suggested catching all exceptions everywhere in the controller for maximum robustness. I narrowed most of these to specific exception types (`TransientModelError`, `PermanentModelError`, `BudgetExceeded`) except in the `Planner.create/revise` fallback paths, where broad catching makes sense because any failure mode (including `ScriptedModelClient`'s `RuntimeError` in tests) should trigger the fallback plan rather than crash the agent.

---

## One AI-generated or AI-assisted bug I personally diagnosed

**Symptom**: `test_plan_revision_fallback_on_model_error` failed with `RuntimeError: No scripted structured output remains.` even though the test was specifically designed to verify the fallback behavior when the model call fails.

**Cause**: The initial `Planner.revise()` implementation caught `(TransientModelError, PermanentModelError, KeyError, TypeError, ValueError)` but not `RuntimeError`. When `ScriptedModelClient.structured()` has an empty queue, it raises a plain `RuntimeError` — which is not a model error type, it's a test infrastructure artifact. The except clause did not catch it, so the fallback was never reached.

**Fix**: Broadened the except clause to `except Exception` in both `create()` and `revise()` fallback paths, with an explanatory comment. This correctly activates the fallback for any error that prevents plan generation, including test infrastructure errors, without hiding bugs in the controller itself (where exception handling is more specific).

---

## Code ownership statement

I can explain every submitted component, its failure behavior, and the trade-offs I chose. I understand that the TA may ask me to modify the code during viva.

**Signature:** Rayan (23I-0018)
