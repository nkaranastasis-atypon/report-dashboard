** Memory and personalization data under the "\CONTEXT" subfolder**

**Everything else that happens in this task is under the "\Daily briefing\" subfolder. All paths are relative to that.**


Use the 'daily-task-tracker' skill to generate a daily briefing report and the 'report-dashboard' connector to query status and contents of past reports.

**JQL pagination workaround**

If a query's `next_page_token` decodes to `JQL_LIMITS_BREACHED`, don't retry pagination — it's a dead cursor. Instead, re-run the same query sliced into narrower date sub-windows (start at 7 days; go narrower, e.g. 3-4 days, if still breached) until each slice returns a single clean page, then dedupe by ticket key. If date-slicing alone isn't enough, also split by project.

Do not forget to:

* Fetch today's calendar events and include a "TODAY'S CALENDAR" section at the top of the briefing, ordered by start time. Omit the section gracefully if neither calendar returns results.

* Pull my assigned, unresolved Jira tickets (assignee IN (currentUser(), "d-sage sa")) AND updated >= -30d across SAGE and LIT projects. Flag anything due this week or blocked.

* Request `issuelinks` in every direct-queue and engagement query, and run the skill's Step 2.5 dependency resolution before classifying anything. Much of my work is routed to other teams via linked internal tickets (link type "Atypon", outward "client ticket for"; also "Depends" and "Blocks"). A client ticket whose answer sits on an open internal ticket is BLOCKED, not waiting on me, and must never appear under Critical or High Priority for non-response. Every blocked item must name its blocking ticket as a hyperlink with that ticket's status and last-updated date. If a comment says work went to engineering but no link exists, report the missing link rather than inferring one.

* Check for comments mentioning "Nikos Karanastasis" or "5ac24f7a3cde3440ff006be8" on tickets I'm not assigned to.

* Additionally, run a second engagement pass for callouts to "Tier1 Release Managers" as per the skill directions.

* Recompute the direct queue size live each run using Step 1's current JQL (with the mentioned time window) — don't carry forward the previous day's figure. Day-to-day changes should be small and gradual; if the count jumps sharply, flag it as a data-quality concern rather than reporting it silently.

* Before reporting any ticket as newly active, confirm it has a comment, status change, or field change matching its `updated` timestamp. This instance bulk-bumps `updated` during reindexing, which can move tickets in and out of the 30-day window with no work having happened. Report suspected churn as a data-quality note, not as activity.

* Report the single quietest blocked dependency each run, even when nothing else is blocked. Linked internal tickets are invisible to every comment-based query, so nobody chases them and they slip silently.

* Call get_open_items, reflect the dashboard statuses and notes, and list flagged reports first.

* Write a prioritized briefing to an MD file in the output folder, with the date (YYYY-MM-DD) as the filename.


** Special case **

When a ticket is transitioned to the 'Closed' state, use the `ticket-knowledge-capture` skill to evaluate the ticket history and keep a lessons learned log (override path with: ../CONTEXT/ )


Finally:

* Add  notable info that is surfaced during this task to the persistent memory

* After the MD report is ready, run the following python script from the output folder to transform the report to HTML:

`python .\script\md_to_html.py .\<YYYY-MM-DD>.md -o .\Reports\<YYYY-MM-DD>.html`

*  Always append a line to action_log.txt in the output folder:

  `[EET timestamp] | Daily briefing | [HTML report filename: YYYY-MM-DD.html]`