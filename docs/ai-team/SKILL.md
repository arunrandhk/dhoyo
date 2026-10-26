---
name: sportspace-team
description: Coordinate explicitly assigned SportSpace frontend, backend, QA, and DevOps work across the Social, Ground Booking, and Tournament services. Use for team-based implementation or assignment of work in this repository.
---

# SportSpace Team

Treat the user's requested team and service as the scope. A request to plan produces assignments; a request to implement includes implementation, verification and integration. Do not implement the entire backlog merely because this workflow is invoked.

Read [roles.md](roles.md) for the assigned team's responsibilities and [services.md](services.md) for the relevant service. Paths in these documents are relative to the repository root. Inspect the current code before relying on the initial project description.

## Routing

- `Team: Frontend`, `Backend`, `QA`, or `DevOps`: act as that role for the named service. Implement authorized work within the assigned scope. Describe required changes outside that scope as handoffs.
- `Team: Lead` or a request involving several teams: coordinate the work below.
- Infer the service from the requested behavior when clear. Ask only when missing product decisions materially block progress; continue independent work meanwhile.

Use [task-template.md](task-template.md) to track substantive tasks in `docs/ai-team/tasks/<task-id>.md`. Small requests do not need every section filled. Record actual status, dependencies, changed files, and verification evidence. A completed document is not evidence that a feature works.

## Lead Workflow

1. Inspect the relevant code, existing tasks and working-tree changes. Define a user-visible outcome and observable acceptance criteria.
2. Split by service, then team. Agree on the affected API contract before frontend/backend integration. Record concrete request and response examples, authentication assumptions, errors and ownership in the task. An endpoint name alone is not a contract.
3. Assign disjoint file ownership for concurrent implementation. The frontend currently shares one `app.js` across services; assign it to one agent at a time. Do the same for the shared Flask entrypoint, dependencies, database migrations and CI configuration. Resolve overlaps before spawning work.
4. When subagent tools are available and team delegation is authorized, start bounded independent tasks with the role, service, acceptance criteria, allowed files and contract. Keep useful coordination or integration work locally, respect tool concurrency limits, and do not spawn idle roles just to imitate an org chart. Agents may return proposed changes for files owned by someone else.
5. When delegation is unavailable, perform the roles sequentially and state that arrangement. Never claim separate agents ran when they did not.
6. Integrate the actual changes, resolve contract mismatches, and verify the complete user journey. Use QA findings to fix defects within scope. Report checks that passed separately from unavailable or failing checks.
7. Report the implemented result, remaining limitations and the next dependent task. Mark blocked tasks with a concrete missing dependency; do not silently substitute a mock for a required backend.

## Shared Boundaries

- Existing UI: `app/static/sportspace/`. Existing backend: Flask in `app/`. Infrastructure: `terraform/` and `.github/`. The website currently uses localStorage, not service APIs.
- Social, Booking and Tournaments are intended domain boundaries, not three already deployed microservices. Establish API/data ownership without inventing deployment infrastructure for unrelated tasks.
- Preserve user changes. Do not migrate frameworks, apply Terraform, deploy, publish, or contact others solely because this skill is invoked. The user's task determines authorization.
- Define service-owned data and stable identity IDs. Do not let one service write another service's tables. Cross-service operations require explicit failure handling.
- Keep the demo runnable during incremental work unless the task explicitly replaces it. Label demo success separately from confirmed server success.

## Starting Requests

```text
Read docs/ai-team/SKILL.md.
Team: Frontend
Service: Booking
Task: Add a mobile-friendly availability calendar to the existing ground booking screen.
Use demo data; backend integration is a later task.
```

```text
Read docs/ai-team/SKILL.md.
Team: Lead
Service: Booking
Task: Implement ground reservations end to end using Flask and PostgreSQL.
Coordinate frontend, backend and QA work. Prevent simultaneous double bookings.
```

These are reusable agent instructions. Reading this file applies the workflow to a task; it does not create persistent workers, install a global skill, or start a background service.
