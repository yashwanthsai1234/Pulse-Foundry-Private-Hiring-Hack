

## Build a Single Source of Truth

_Participant Challenge Brief_

---

## The Situation

Pulse Foundry works with established businesses across many industries. Almost all of them share the same problem: their information is scattered across systems, spreadsheets, inboxes, and documents that don't agree with each other. Nobody has one place to go for a trusted answer, and that makes it hard to fix anything else.

## Your Challenge

Build a central source of truth for a business, and show us how it would solve that business's problems.

## The Business

**Harborview Care Group** is a fictional company that runs two skilled nursing facilities, **Bayside** and **Riverdale**, with 10 employees. Even at this size, its information lives in separate systems for HR, payroll, scheduling, and licensing, and those systems don't always agree.

## The Problems

Here is how the company describes its biggest headaches:

> "Hospitals send us patient referrals, and by the time we get through them, the patient has often gone somewhere else."

> "Every quarter, reporting our staffing numbers to the state takes someone weeks, and we're never fully confident in them."

> "Licenses, certifications, and vendor paperwork expire, and we usually find out too late."

## What We Expect

Build the source of truth. How you design it, what you store, and what you build it with is up to you. It should be something this company could rely on, and something Pulse Foundry could reuse for a client in a completely different industry.

At a minimum, when data is ingested, your system should surface anything in it that is wrong, inconsistent, or needs a human to look at.

Then show us how your source of truth would help solve the problems above. You don't need to build the applications that solve them, but your explanation should be grounded in what you actually built.

## About the Data

You won't receive the company's data during the build. At judging, we'll hand you the real files and you'll ingest them into your source of truth live. Here is what they will look like.

### 1. HR roster (CSV)

One row per employee record, exported from the HR system.

| employee_id | first_name | last_name | job_title | facility | phone | license_number | license_expiration | hire_date |
|---|---|---|---|---|---|---|---|---|
| E201 | Sofia | Reyes | Registered Nurse | Harborview Bayside | 718-555-0201 | RN-551203 | 2027-05-31 | 2020-03-02 |
| E202 | Marcus | Bell | Certified Nursing Assistant | Harborview Riverdale | 347-555-0202 | CNA-771045 | 2026-12-31 | 2022-09-12 |

### 2. Payroll (CSV)

One row per employee per weekly pay period, exported from the payroll system.

| payroll_id | employee_name | job_code | facility_code | period_start | period_end | hours_paid |
|---|---|---|---|---|---|---|
| P-3001 | REYES, SOFIA | RN | BYS | 2026-09-14 | 2026-09-20 | 36 |
| P-3002 | BELL, MARCUS | CNA | RVD | 2026-09-14 | 2026-09-20 | 40 |

### 3. Licenses (CSV)

One row per license or certification, from the licensing verification service.

| license_number | name_on_license | license_type | expiration_date | last_verified |
|---|---|---|---|---|
| RN-551203 | REYES, SOFIA | RN | 2027-05-31 | 2026-09-01 |
| CNA-771045 | BELL, MARCUS | CNA | 2026-12-31 | 2026-09-01 |

### 4. Staff schedule (PDF)

A printed weekly schedule, one page per facility, as posted at the nurses' station. Each page has a table with one row per staff member and one column per day. Cells show the shift or `OFF`. A note at the bottom of each page gives shift lengths.

| Staff | Role | Mon 09/14 | Tue 09/15 | Wed 09/16 | Thu 09/17 | Fri 09/18 | Sat 09/19 | Sun 09/20 |
|---|---|---|---|---|---|---|---|---|
| Sofia Reyes | RN | 7a-3p | 7a-3p | OFF | 7a-7p | OFF | 7a-3p | OFF |
| Marc Bell | CNA | 3p-11p | OFF | 3p-11p | 3p-11p | 3p-11p | 3p-11p | OFF |

_Shifts: 7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours._

The rows above are examples only. The real files will have the same structure, but different and more numerous records. Expect the data to be messy: the same person, facility, or license may be written differently in each system, and the systems will not always agree.

## What to Submit

- Your code
- A short written summary of your key decisions and why you made them

### How to Submit

Submissions are made on Pulse, not DevPost.

1. Go to the [Pulse Foundry Private Hiring Hack page](https://pulsefoundry.ai/hackathons/6ac17ad8073be40e3dbbb08b).
2. Log in with the same email you used to register for the event.
3. Submit your project.

## The Judging Session

At judging, we'll give you the company's real files in the formats above. You'll ingest them into your source of truth live and show us what your system flags.

You'll also present what you built and explain how it would help solve the company's problems. Be ready to defend your decisions.
