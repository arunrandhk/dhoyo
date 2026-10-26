# Task Board

No implementation tasks have been started by creating this team setup.

Create task files here from `../task-template.md` as the user assigns work. Keep
status and evidence in those files; avoid a second status table that can drift.

Suggested initial assignments, not work already authorized or completed:

| Task | Team | Vertical | Outcome | Dependency |
| --- | --- | --- | --- | --- |
| ID-001 | Backend | Shared Identity | Agreed login approach and trusted user identity | Product login requirements |
| SOC-001 | Backend | Social | Persisted posts API with ownership rules | ID-001 |
| SOC-002 | Frontend | Social | Feed and composer connected to the posts API | SOC-001 contract; API needed for final verification |
| BKG-001 | Backend | Booking | Availability and atomic reservations | ID-001 |
| BKG-002 | Frontend | Booking | Availability, confirmation and cancellations through APIs | BKG-001 contract; API needed for final verification |
| TRN-001 | Backend | Tournaments | Persisted events and capacity-limited registrations | ID-001 |
| TRN-002 | Frontend | Tournaments | Event registration connected to APIs | TRN-001 contract; API needed for final verification |
| QA-001 | QA | Selected vertical | Verify the first integrated user journey | Corresponding frontend and backend tasks |
| OPS-001 | DevOps | Selected vertical | Documented local startup and CI checks | Selected runtime and service layout |

UI work with explicit demo data can proceed while backend dependencies are open.
Start with one complete vertical, then reuse the established integration patterns.
