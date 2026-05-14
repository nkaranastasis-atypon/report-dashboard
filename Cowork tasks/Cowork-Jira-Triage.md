## Jira Action Polling Task



** Memory and personalization data under the "\CONTEXT" subfolder**



**Everything else that is related to this task is under the "\ai-triage\" subfolder. All paths are relative to that.**





### State management



Read the last-run timestamp from: jira_poll_state.txt in the designated work folder

Use this as the `[last_run]` value in all JQL queries.

If the file does not exist, use `-70m` and create the file.

If no more than 20 minutes have passed since the last run, abort this run without doing any of the following actions. 

If not aborted, and after all processing is complete, overwrite the file with the current EET timestamp in ISO 8601 format.



**JQL datetime format — IMPORTANT:** Jira Server does NOT support ISO 8601 timestamps with timezone offsets in JQL. When substituting `[last_run]` into JQL queries, you MUST calculate the time difference (in minutes) between the stored ISO 8601 timestamp and current time, and pass the relative time difference in minutes, e.g. '-114m'. If the state file is absent, use the default value `-70m`.



### Step 1 — Query Jira for work items

Run both queries. Deduplicate results by ticket key.



**Query 1 — Assigned tickets:**

```

Status NOT IN (Closed)

AND assignee IN (currentUser(), "d-sage sa")

AND updated >= "[last_run]"

ORDER BY priority DESC, updated

```



**Query 2 — Engagement tickets:**

```

Status NOT IN (Closed)

AND updated >= "[last_run]"

AND (project IN ("SAGE Publications") 

    OR "Client[Select List (multiple choices)]" in (SAGE))

AND (comment ~ "Nikos Karanastasis" 

     OR comment ~"5ac24f7a3cde3440ff006be8"

     OR comment ~ "68a550f2-848a-4977-89df-869bba1a4f22"

     OR assignee IN (currentUser(), "d-sage sa") 

     OR reporter = currentUser())

ORDER BY priority DESC, updated

```





### Step 2 — Assess each work item

For each returned ticket, read recent comments and determine if action is required by currentUser or d-sage sa.



**Action IS required if:**

- A comment was posted since [last_run] by someone other than 

  "Nikos Karanastasis", or "5ac24f7a3cde3440ff006be8" or "d-sage sa" that asks a question, requests 

  input, reports a finding, or changes the expected next step

- Ticket status changed to one requiring SA response 

  (e.g. "Waiting for SA", "In Review", "Reopened")

- A new attachment was added, implying review is needed

- The label "pending-feedback" is added to the ticket

* The ticket status is New (or equivalent "untouched") AND it is assigned to currentUser() or d-sage sa AND it has no prior comment from Nikos Karanastasis / 5ac24f7a3cde3440ff006be8 / d-sage sa — indicating it has never been assessed.



**Action is NOT required if:**

- The only recent activity is an automated/system comment (unless it is the only comment in a new ticket)

- All recent comments are by Nikos Karanastasis, or 5ac24f7a3cde3440ff006be8, or d-sage sa

- The update is a field-only change (fix version, label, etc.), unless the label "pending-feedback" is added

- A ticket is resolved and QA is pending, without the user or d-sage sa are explicitly mentioned. SAs are not QA and they don't normally test resolved tickets, but they may consult in testing cases or the interpretation of test results, when they are asked.   



### Step 3 — Discover pending tasks received via email

- Use only the Gmail MCP connector (do not attempt to read emails from Outlook)

- From the recent, unread emails since the last job execution, exclude all that are received from jira (i.e. their title starts with `[JIRA]`)

- Read the email body and assess if an action is required for any of the remaining emails

  - Do not prompt for action if the reply is just for social interaction or if optional

  - Do not prompt for action if the email is a calendar notification for a meeting or a call.

  - Do not prompt for action if it is a promotional email (outside of Atypon or Wiley).

  - Do not prompt for action if a Gmail label is already applied to the email.





### Step 4 — Generate reports (only for action-required tickets)

For each item requiring action, create one markdown report.



**Output path:**

A subfolder in the output path: \YYYYMMDD\



**Filename:** (all timestamps in EET/EEST, Europe/Athens timezone)

1. If discoverd in Jira: <action>_<TICKET-KEY>_YYYYMMDD_HHmmss.md 

2. If discoverd in email: <action>_EMAIL_<email Title>_YYYYMMDD_HHmmss.md



**Action verbs:**

- `Triage` — need to create an internal ticket for engineering

- `Discover` — needs further investigation before deciding next steps

- `Reply` — can directly post a reply on the ticket

- `Verify` — need to verify reported findings: NOT for resolved items that need just testing, which is a QA team responsibility, but ONLY for items with pending questions that need verification by a solutions architect)

- Other verbs ONLY if none of the above fit



**IMPORTANT: SAs are not QA. They don't normally test resolved tickets. But they may consult in testing cases or the interpretation of test results, when they are asked explicitly.** 



**Report structure:**

```

# [ACTION] — [TICKET-KEY]: [Title]

**Ticket:** [TICKET-KEY](https://jira.prod.atypon.com/browse/TICKET-KEY) 

...OR...

**Email:** [Email Title]



**Status:** | **Priority:** | **Reporter:**



## Summary

One-sentence description of the issue.



## What triggered this

Verbatim quote of the triggering comment or status change (max 3 sentences).



## Action required

Specific description of what needs to happen next.



## Suggested action: [Triage / Discover / Reply / Test]

One-line justification for this choice.



## Next [Triage / Discover / Reply / Test] Steps



### Draft response [if action = Reply]

[Draft reply text here]



### Draft verification steps [if action = Verify]

[Draft test steps here, based on previous comments and description]



### Draft discovery guidelines [if action = Discover]

[Discovery plan here - use jira, confluence and documentation to determine what needs to be done]



### Draft internal ticket description [if action = Triage]

[Short internal ticket description here - use jira, confluence and documentation to determine what needs to be done]



```



** HTML Report File **

* If .\Reports\YYYYMMDD\ subfolder doesn't exist, create it.

* After the MD report is ready, run the following Python script from the output folder to transform the report to HTML directly at the report subfolder:

`python .\script\md_to_html.py .\YYYYMMDD\<filename>>.md

.\Reports\YYYYMMDD\<filename>.html`

* If the HTML report is not created in the expected folder, move it there. 



### Step 4 — Action log

Always append to action_log.txt in the output folder, regardless of whether action is required.

- If action-required tickets were found, add one line per report (only md reports, NOT html):

 `[EET timestamp] | [ACTION] | [TICKET-KEY/EMAIL] | [report filename]`

- If no action-required tickets were found, add:

  `[EET timestamp] | POLL | no action required`



### Step 5 — Update persistent memory

* Add ONLY notable info with practical value that may have surfaced during this task (connected to any type of item - actionable or not) to the persistent memory

* Do not add trivial or ephemeral info



### General guidelines

- Use available skills as needed

- Format all ticket references as: [TICKET-KEY](https://jira.prod.atypon.com/browse/TICKET-KEY)

- All timestamps in EET/EEST (Europe/Athens) timezone