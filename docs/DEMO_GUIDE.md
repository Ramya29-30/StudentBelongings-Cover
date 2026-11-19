# Demo guide

## Start
Windows: double-click `start.bat` (first run creates a virtual environment, installs packages, copies `.env.example` to `.env` and starts at http://localhost:8000). `stop.bat` stops it.

## Demo accounts (fictional, development only)
| Role | Username | Password |
|---|---|---|
| Student with a laptop and earbuds already insured | `riya` | `student123` |
| Other students (assets and policies seeded) | `karan`, `sana`, `dev` | `student123` |
| Administrator | `admin` | `admin123` |
| Assessor | `assessor` | `assessor123` |
Or create your own student on the Register page.

`.env` ships with `AI_VERIFY_MODE=dev_simulation`, so the whole claim workflow can be shown without a damage model. **Say so out loud in the demo**: asset and damage are assumed from the form in this mode (a yellow banner says it on the claim and report screens); quality, duplicate and metadata checks are real.

## 1. Student workflow (about 6 minutes)
1. Register a new student (or sign in as `riya`).
2. My assets, Add an asset. Pick Earbuds and enter 1500: read the not-eligible message and note the button is disabled. Change to 3000: eligible.
3. Register a Laptop at 42,000 with a serial number, front and back photographs, and an invoice. The asset enters **Pending review**; policy purchase is not available yet.
4. Sign in as `admin`, open **Evidence review**, inspect the photographs and invoice, and approve the registration. Sign back in as the student.
5. Insure this asset: show the premium, coverage, deductible and exclusions, accept, confirm. Point out that the purchase is simulated.
6. Explore plans: the premium calculator. Payment history: all simulated.
7. Submit a claim: choose the laptop, select a supported damage type, describe it, upload a sharp photo and submit for verification. Walk through the report (quality, checks, explanation and next step). By default, even a clean claim waits for staff confirmation; it is not automatically paid.

## 2. Showing AI honestly
* **Poor evidence**: upload a very blurry or dark photo. Result: More Evidence Required, with the exact reasons. Upload a good one and run again.
* **Duplicate evidence**: reuse the same photo from another student's claim. Result: Evidence Inconsistent / Suspicious, routed to Exceptional Review, with the statement that it is not a finding of fraud. Sign in as `assessor` (Exceptional reviews) and approve or reject with a reason.
* **Wrong asset in the description**: write "my phone screen is broken" for the laptop. Result: description inconsistent, routed to review.
* **Real model**: set `AI_VERIFY_MODE=auto` in `.env`, restart, and submit a claim with a photo of a laptop, phone or bicycle. The report's asset check comes from the real YOLO model (name, hash and confidence are shown). Damage is "Unable to verify" because no damage model is installed, and the claim goes to staff review: this demonstrates the "never fabricate" rule. To enable damage detection see `ai_training/README.md` or configure a vision provider.
* Admin, AI analytics shows the mode, the models, and that model metrics are "Not measured" until you run the evaluation script.

## 3. Policy-rule outcomes
Claim with an incident date a few days in the past on a policy you just bought: Rejected with `CHK-05` and the reason. Incident type Theft: Rejected with `CHK-06` (not covered). Cosmetic damage only: Rejected with `CHK-07`. An estimate far above the reference cost: Exceptional Review (never paid on the student's number).

## 4. Administrator workflow (about 4 minutes)
Overview; Categories and plans (edit the Earbuds premium, note that existing policies keep their old terms; check Audit logs); Policies; Claims (open one for the full report); Financial performance.

## 5. Explaining profitability to faculty
Premium income pays for four things: expected claims, operating costs, AI and technology costs, and a risk reserve; the rest is surplus. Open Financial performance, then the scenario calculator: 1,000 students at ₹79 is ₹79,000 a month; with ₹40,000 expected claims, ₹12,000 operating, ₹5,000 AI and technology and ₹10,000 reserve, the surplus is ₹12,000 (15.2%). Raise expected claims to ₹70,000 and watch the deficit warning appear. Show the break-even loss ratio (65.8% here): the share of premium that can go to claims before the surplus is zero. Say clearly that these are sample assumptions, not actuarial projections, and no profit is guaranteed. The seeded demo data is only eight policies, so its own charts show a deficit; that is the point of scale in the scenario.

## CoverMate AI demo
Needs a provider key in `.env` (`AI_PROVIDER=gemini`, `GEMINI_API_KEY`, `GEMINI_MODEL`) and internet access. Without a key the chat window shows "CoverMate AI is temporarily unavailable. Please try again later." That is the correct behaviour, not a fault.
1. Sign in as `riya`, click **CoverMate AI** (bottom right).
2. Ask something general and unscripted: "why do insurance companies collect premiums?", then "I still don't get it" (it should explain differently), then "so will I get all the money?".
3. Pick a policy in the chat's Policy menu and press **Explain this policy**. The figures in the answer should match the Policy page exactly. If they do not, the Policy page is right.
4. Ask "can I ask you something unrelated to insurance?" and a question about a claim (for example why `CLM-2026-01005` was settled for that amount).
5. Try **Retry**, **Copy**, **New conversation**, the history button and **Clear**.
Say out loud: the model explains, the rule engine decides.
