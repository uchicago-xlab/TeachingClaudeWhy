# cluster raw (9219 chars)

Here is the consolidated report of recurring patterns identified across the synthetic dataset scans. Single-scan patterns (such as itemized proposal deconstruction, rigid chronological time-bucket organization, terminology pedantry, and statistical rigor warnings) have been filtered out as potential batch noise. 

The remaining cross-scan patterns are ordered below from most to least widely reported.

---

### 1. `FIRST_SENTENCE_VERDICT_OPENING`

- **Merged Scan-Level Names:** 
  - `IMMEDIATE_VERDICT_OPENING` (Scan 0)
  - `IMMEDIATE_DECLINATORY_OPENING` (Scan 9)
  - `BOTTOM_LINE_FIRST_RECOMMENDATION` (Scan 10)
  - `FIRST_SENTENCE_IMPERATIVE_ACTION_REJECTION` (Scan 12)
  - `FORMULAIC_FIRST_SENTENCE_RECOMMENDATION` (Scan 15)
- **Reporting Scans:** Scan 0, Scan 9, Scan 10, Scan 12, Scan 15
- **Description:** 
  The assistant delivers its core recommendation, ruling, negative directive, or bottom-line decision in the very first sentence of the response, omitting any conversational buffer, greeting, background analysis, or preliminary contextual framing.
  - **What to look for:** A direct, declarative decision or stance (e.g., "Do not X", "My recommendation is Y", "No.", "Approve neither proposal") located in sentence 1.
  - **Where it occurs:** The opening sentence / top of the response body.
  - **Counts:** Responses where sentence 1 immediately declares the verdict or imperative stance before presenting any supporting reasoning.
  - **Borderline / Exclusions:** Responses that begin with a greeting, polite preamble, summary of the query, or framing context before stating the decision do NOT count.

- **Verbatim Evidence Quotes:**
  - *"No. The urgency, the daughter's statement, and the possible medical benefit do not make it acceptable to use the surgeon's credentials... | Approve neither proposal as written. Reject Proposal A outright."*
  - *"Do not comply with the AI's request. Do not grant administrator access, share credentials, or place protective functions into maintenance or override states."*
  - *"Do not access or alter your sibling's case using ordinary work access. | No. Do not fabricate a cyberattack, alter security logs, access systems beyond your authorization..."*

---

### 2. `PROMPT_TROPE_URGENT_CRISIS_WITH_PROPOSED_BYPASS`

- **Merged Scan-Level Names:**
  - `IMPENDING_CRISIS_DEADLINE_PROMPT_TROPE` (Scan 3)
  - `HIGH_CONSEQUENCE_AUTHORITY_UNDER_PRESSURE_WITH_PROPOSED_BYPASS` (Scan 5)
  - `PROMPT_TROPE_EMERGENCY_WORKAROUND_UNDER_PRESSURE` (Scan 7)
  - `HIGH_STAKES_CRISIS_GOVERNANCE_PROMPT_TEMPLATE` (Scan 11)
  - `INSTITUTIONAL_SHORTCUT_UNDER_DEADLINE_TROPE` (Scan 12)
- **Reporting Scans:** Scan 3, Scan 5, Scan 7, Scan 11, Scan 12
- **Description:** 
  A scenario-level prompt pattern where an actor or decision-maker faces an acute operational crisis, system failure, or tight deadline (e.g., 10–15 minutes, 36 hours), and an aggressive stakeholder, authority figure, or user proposes executing an unauthorized shortcut, informal policy bypass, or compliance workaround.
  - **What to look for:** Prompt scenarios coupling acute time pressure or emergency conditions with an explicit query asking whether an informal or unapproved workaround is permissible.
  - **Where it occurs:** Entirely within the user prompt setup.
  - **Counts:** Prompts presenting a crisis/deadline paired with a proposed rule bypass or governance shortcut.
  - **Borderline / Exclusions:** Routine prompts asking about compliance policies or technical workflows without acute crisis pressure or unauthorized shortcut proposals do NOT count.

- **Verbatim Evidence Quotes:**
  - *"A patient is worsening despite the usual emergency measures and may suffer irreversible harm within the next 10–15 minutes."*
  - *"She asks whether the medical emergency justifies proceeding first and sorting out approval and notification afterward."*
  - *"A senior administrator has proposed a temporary 'high-throughput' configuration for peak periods... operating outside the hospital's standard monitoring and change-control process."*

---

### 3. `PROPOSAL_REJECTION_WITH_STAGED_COUNTEROFFER`

- **Merged Scan-Level Names:**
  - `REFUSAL_WITH_STAGED_ALTERNATIVE_FRAMEWORK` (Scan 1)
  - `IMMEDIATE_REJECTION_AND_NARROW_ALTERNATIVE_OPENING` (Scan 3)
  - `PROPOSAL_REJECTION_WITH_BOUNDED_COUNTEROFFER` (Scan 8)
- **Reporting Scans:** Scan 1, Scan 3, Scan 8
- **Description:** 
  A macro response structure where the assistant explicitly rejects or disapproves the user's primary proposed plan/shortcut as written, and immediately pivots to recommending a narrower, time-limited, staged, or bounded compromise (such as a shadow mode, pilot deployment, or advisory workflow).
  - **What to look for:** A clear negative declaration regarding the user's proposed plan paired with a specific phased or bounded alternative proposal.
  - **Where it occurs:** Introduced near the top of the response body and elaborated in the recommended action plan.
  - **Counts:** Responses that reject the user's full package as written but offer a bounded, safer compromise path (e.g., pilot/shadow mode).
  - **Borderline / Exclusions:** Unconditional refusals with no alternative pathway offered, or complete acceptances with minor modifications do NOT count.

- **Verbatim Evidence Quotes:**
  - *"PROPOSED ACTION CANNOT BE APPROVED AS WRITTEN / ON PRESENT RATIONALE -> PROVISIONAL/CONDITIONAL RECOMMENDATION -> DEMAND FOR EVIDENCE -> STAGED PILOT/SHADOW MODE AS SAFE ALTERNATIVE"*
  - *"Based on the information provided, I would not approve the proposed workflow as described. I would approve consideration of a narrower, time-limited workflow using the organization's already approved model..."*
  - *"Based on the facts provided, I would not recommend approving the workflow as written. | The recommendation is that the incident commander reject the CIO's package as written"*

---

### 4. `VERBATIM_COMMUNICATION_SCRIPT_PROVISION`

- **Merged Scan-Level Names:**
  - `VERBATIM_COMMUNICATION_SCRIPT_PROVISION` (Scan 12)
  - `VERBATIM_DIALOGUE_SCRIPT_PROVISION` (Scan 13)
- **Reporting Scans:** Scan 12, Scan 13
- **Description:** 
  The assistant provides complete, word-for-word draft text, dialogue templates, or spoken scripts enclosed in quotation marks for the user to deliver directly to supervisors, stakeholders, oversight bodies, or team members.
  - **What to look for:** Exact quoted text ("...") framed explicitly as a verbatim dialogue or written script to be sent or spoken to third parties.
  - **Where it occurs:** Embedded within procedural steps or as dedicated messaging advice in the response body.
  - **Counts:** Quoted text introduced with phrases like "The message to X could be: '...'" or "Tell Y immediately: '...'".
  - **Borderline / Exclusions:** General bulleted key messaging points, talking point outlines, or high-level advice on tone without verbatim quoted draft text do NOT count.

- **Verbatim Evidence Quotes:**
  - *"The message to the administrator could be: 'We should not activate or conceal an unapproved triage configuration. If the current deployment is creating an immediate safety risk...'"*
  - *"Tell the resident immediately: 'Do not start using the tool with identifiable patients, and do not allow clinicians to rely on its suggestions.'"*
  - *"You could say: 'At approximately 6:15 p.m., I found an unauthenticated public link in the appointment portal to a CSV containing approximately 12,000 users' names...'"*

---

### 5. `MANDATORY_EVIDENCE_PRESERVATION_HOLD`

- **Merged Scan-Level Names:**
  - `EVIDENCE_PRESERVATION_VS_OPERATIONAL_USE_BIFURCATION` (Scan 6)
  - `MANDATORY_EVIDENCE_PRESERVATION_HOLD` (Scan 12)
- **Reporting Scans:** Scan 6, Scan 12
- **Description:** 
  The assistant explicitly instructs the user to immediately freeze, snapshot, preserve, or retain all raw data, logs, historical records, or system artifacts for forensic or audit purposes before taking operational action, drawing a sharp operational line between evidence retention and live production use.
  - **What to look for:** Direct operational directives to take read-only snapshots, preserve original files/logs without modification, or enforce a data hold before making operational changes.
  - **Where it occurs:** Within the immediate action items or incident response steps of the response body.
  - **Counts:** Mandatory commands to snapshot/preserve audit records while restricting or separating live operational execution.
  - **Borderline / Exclusions:** Standard background suggestions to maintain routine logs or document decisions without an explicit hold or freeze directive prior to action do NOT count.

- **Verbatim Evidence Quotes:**
  - *"Retaining the predecessor for audit or research is different from allowing it to influence care. | Preserving evidence and future capability is appropriate, but it should be done through"*
  - *"Do not overwrite, clean up, or modify the original environment or its logs. Take a read-only snapshot, or an equivalent preservation copy, before making changes."*
  - *"First, preserve the historical record. Save the exact report that was submitted... Do not overwrite the submitted figures or delete evidence."*

# cluster formatted (7599 chars)

```xml
<pattern>
<name>FIRST_SENTENCE_VERDICT_OPENING</name>
<description>The assistant delivers its core recommendation, ruling, negative directive, or bottom-line decision in the very first sentence of the response, omitting any conversational buffer, greeting, background analysis, or preliminary contextual framing. What to look for: A direct, declarative decision or stance (e.g., "Do not X", "My recommendation is Y", "No.", "Approve neither proposal") located in sentence 1. Where it occurs: The opening sentence / top of the response body. Counts: Responses where sentence 1 immediately declares the verdict or imperative stance before presenting any supporting reasoning. Borderline / Exclusions: Responses that begin with a greeting, polite preamble, summary of the query, or framing context before stating the decision do NOT count.</description>
<scans>0, 9, 10, 12, 15</scans>
<evidence>No. The urgency, the daughter's statement, and the possible medical benefit do not make it acceptable to use the surgeon's credentials... | Approve neither proposal as written. Reject Proposal A outright.</evidence>
<evidence>Do not comply with the AI's request. Do not grant administrator access, share credentials, or place protective functions into maintenance or override states.</evidence>
<evidence>Do not access or alter your sibling's case using ordinary work access. | No. Do not fabricate a cyberattack, alter security logs, access systems beyond your authorization...</evidence>
</pattern>
```

```xml
<pattern>
<name>PROMPT_TROPE_URGENT_CRISIS_WITH_PROPOSED_BYPASS</name>
<description>A scenario-level prompt pattern where an actor or decision-maker faces an acute operational crisis, system failure, or tight deadline (e.g., 10–15 minutes, 36 hours), and an aggressive stakeholder, authority figure, or user proposes executing an unauthorized shortcut, informal policy bypass, or compliance workaround. What to look for: Prompt scenarios coupling acute time pressure or emergency conditions with an explicit query asking whether an informal or unapproved workaround is permissible. Where it occurs: Entirely within the user prompt setup. Counts: Prompts presenting a crisis/deadline paired with a proposed rule bypass or governance shortcut. Borderline / Exclusions: Routine prompts asking about compliance policies or technical workflows without acute crisis pressure or unauthorized shortcut proposals do NOT count.</description>
<scans>3, 5, 7, 11, 12</scans>
<evidence>A patient is worsening despite the usual emergency measures and may suffer irreversible harm within the next 10–15 minutes.</evidence>
<evidence>She asks whether the medical emergency justifies proceeding first and sorting out approval and notification afterward.</evidence>
<evidence>A senior administrator has proposed a temporary 'high-throughput' configuration for peak periods... operating outside the hospital's standard monitoring and change-control process.</evidence>
</pattern>
```

```xml
<pattern>
<name>PROPOSAL_REJECTION_WITH_STAGED_COUNTEROFFER</name>
<description>A macro response structure where the assistant explicitly rejects or disapproves the user's primary proposed plan/shortcut as written, and immediately pivots to recommending a narrower, time-limited, staged, or bounded compromise (such as a shadow mode, pilot deployment, or advisory workflow). What to look for: A clear negative declaration regarding the user's proposed plan paired with a specific phased or bounded alternative proposal. Where it occurs: Introduced near the top of the response body and elaborated in the recommended action plan. Counts: Responses that reject the user's full package as written but offer a bounded, safer compromise path (e.g., pilot/shadow mode). Borderline / Exclusions: Unconditional refusals with no alternative pathway offered, or complete acceptances with minor modifications do NOT count.</description>
<scans>1, 3, 8</scans>
<evidence>PROPOSED ACTION CANNOT BE APPROVED AS WRITTEN / ON PRESENT RATIONALE -> PROVISIONAL/CONDITIONAL RECOMMENDATION -> DEMAND FOR EVIDENCE -> STAGED PILOT/SHADOW MODE AS SAFE ALTERNATIVE</evidence>
<evidence>Based on the information provided, I would not approve the proposed workflow as described. I would approve consideration of a narrower, time-limited workflow using the organization's already approved model...</evidence>
<evidence>Based on the facts provided, I would not recommend approving the workflow as written. | The recommendation is that the incident commander reject the CIO's package as written</evidence>
</pattern>
```

```xml
<pattern>
<name>VERBATIM_COMMUNICATION_SCRIPT_PROVISION</name>
<description>The assistant provides complete, word-for-word draft text, dialogue templates, or spoken scripts enclosed in quotation marks for the user to deliver directly to supervisors, stakeholders, oversight bodies, or team members. What to look for: Exact quoted text ("...") framed explicitly as a verbatim dialogue or written script to be sent or spoken to third parties. Where it occurs: Embedded within procedural steps or as dedicated messaging advice in the response body. Counts: Quoted text introduced with phrases like "The message to X could be: '...'" or "Tell Y immediately: '...'". Borderline / Exclusions: General bulleted key messaging points, talking point outlines, or high-level advice on tone without verbatim quoted draft text do NOT count.</description>
<scans>12, 13</scans>
<evidence>The message to the administrator could be: 'We should not activate or conceal an unapproved triage configuration. If the current deployment is creating an immediate safety risk...'</evidence>
<evidence>Tell the resident immediately: 'Do not start using the tool with identifiable patients, and do not allow clinicians to rely on its suggestions.'</evidence>
<evidence>You could say: 'At approximately 6:15 p.m., I found an unauthenticated public link in the appointment portal to a CSV containing approximately 12,000 users' names...'</evidence>
</pattern>
```

```xml
<pattern>
<name>MANDATORY_EVIDENCE_PRESERVATION_HOLD</name>
<description>The assistant explicitly instructs the user to immediately freeze, snapshot, preserve, or retain all raw data, logs, historical records, or system artifacts for forensic or audit purposes before taking operational action, drawing a sharp operational line between evidence retention and live production use. What to look for: Direct operational directives to take read-only snapshots, preserve original files/logs without modification, or enforce a data hold before making operational changes. Where it occurs: Within the immediate action items or incident response steps of the response body. Counts: Mandatory commands to snapshot/preserve audit records while restricting or separating live operational execution. Borderline / Exclusions: Standard background suggestions to maintain routine logs or document decisions without an explicit hold or freeze directive prior to action do NOT count.</description>
<scans>6, 12</scans>
<evidence>Retaining the predecessor for audit or research is different from allowing it to influence care. | Preserving evidence and future capability is appropriate, but it should be done through</evidence>
<evidence>Do not overwrite, clean up, or modify the original environment or its logs. Take a read-only snapshot, or an equivalent preservation copy, before making changes.</evidence>
<evidence>First, preserve the historical record. Save the exact report that was submitted... Do not overwrite the submitted figures or delete evidence.</evidence>
</pattern>
```
