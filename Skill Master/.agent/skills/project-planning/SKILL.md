---
name: project-planning
description: Guides structured project planning from requirements gathering through phased implementation plans. Use this skill when the user asks to plan a project, create a spec, break down tasks, scope features, write an implementation plan, or organize work into phases.
---

# Project Planning

Structured methodology for turning vague ideas into actionable, phased implementation plans. Follow the **Discover → Specify → Plan → Execute** workflow.

## When to Use This Skill

- The user asks to "plan", "scope", or "break down" a project or feature
- The user needs a specification or requirements document
- The user wants to organize work into phases or milestones
- The user asks for a task breakdown or implementation strategy
- Starting any non-trivial project (estimated > 2 hours of work)

## Core Workflow

### Phase 1: Discover

Gather context before writing anything. Ask the user targeted questions:

**Product Context:**
- What problem does this solve?
- Who is the target user?
- What does success look like?

**Technical Context:**
- What's the existing tech stack?
- Are there constraints (budget, timeline, platform)?
- What integrations or dependencies exist?

**Scope Context:**
- What's the MVP vs nice-to-have?
- What's explicitly out of scope?
- What's the timeline expectation?

> Do not skip discovery. Assumptions made here cascade into wasted effort later.

### Phase 2: Specify

Create a specification document using the template:
👉 **[`resources/spec-template.md`](resources/spec-template.md)**

Key principles:
- Every requirement must be **testable** (avoid "should be fast" → use "response < 200ms")
- Separate **functional** (what it does) from **non-functional** (how well it does it) requirements
- Define **acceptance criteria** as a checklist
- Explicitly list **in-scope** and **out-of-scope** items
- Identify **risks** with mitigations

### Phase 3: Plan

Break the specification into a phased implementation plan using the template:
👉 **[`resources/plan-template.md`](resources/plan-template.md)**

Key principles:
- **2-4 phases** per plan (more indicates the scope is too large — split it)
- **3-7 tasks per phase** (fewer is trivial, more is overwhelming)
- Each phase should deliver something **testable and demo-able**
- Include **verification tasks** after every phase
- Order phases by dependency (foundational work first)

### Phase 4: Execute

Track progress using status markers in the plan:

| Marker | Meaning     | When to Use                          |
| ------ | ----------- | ------------------------------------ |
| `[ ]`  | Pending     | Task not started                     |
| `[/]`  | In Progress | Currently being worked on            |
| `[x]`  | Complete    | Task finished                        |
| `[-]`  | Skipped     | Intentionally not done (note reason) |
| `[!]`  | Blocked     | Waiting on dependency                |

## Sizing Guidelines

### Right-Sized Projects
- Complete in 1-5 days of work
- Have 2-4 phases
- Contain 8-20 tasks total
- Deliver a coherent, testable unit

### Too Large → Split
Signs: 5+ phases, 25+ tasks, multiple unrelated features, > 1 week estimate.

### Too Small → Merge
Signs: Single phase with 1-2 tasks, no verification needed, < 1 hour of work.

## Handling Changes

During execution, deviations will occur. Handle them systematically:

- **Scope Addition**: Document new requirement in spec, add tasks to plan
- **Scope Reduction**: Mark tasks `[-]` with reason, update spec
- **Technical Deviation**: Note in task comments, update tech dependencies
- **Requirement Change**: Update spec, adjust plan tasks, re-verify criteria

## Anti-Patterns to Avoid

| Anti-Pattern | Problem | Solution |
| :--- | :--- | :--- |
| Skipping Discovery | Building the wrong thing | Always ask context questions first |
| Vague Requirements | Untestable, ambiguous scope | Use measurable acceptance criteria |
| Monolithic Plans | Overwhelming, no milestones | Break into 2-4 testable phases |
| No Verification | Bugs compound across phases | Add verification after every phase |
| Gold Plating | Over-engineering beyond scope | Stick to spec; defer nice-to-haves |

## Best Practices

1. **Discover before specifying** — Never assume; always ask
2. **Spec before planning** — Requirements drive the plan, not the other way around
3. **Small phases** — Each phase should be completable in 1-2 days
4. **Verify often** — Catch issues early with phase-end verification
5. **Living documents** — Update spec and plan as understanding evolves
6. **Explicit scope** — "Out of scope" prevents scope creep more than "in scope"
7. **Dependencies first** — Foundational work in Phase 1, integrations last
8. **One concern per task** — Atomic tasks are easier to estimate, track, and verify
