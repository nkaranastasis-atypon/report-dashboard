** Memory and personalization data under the "\CONTEXT" subfolder**

**Everything else that happens in this task is under the "\Daily briefing\" subfolder. All paths are relative to that.**



Using the 'daily-briefing' skill:

* Pull my assigned, unresolved Jira tickets (assignee IN (currentUser(), "d-sage sa")) across SAGE and LIT projects. Flag anything due this week or blocked. 

* Check for comments mentioning "Nikos Karanastasis" or "5ac24f7a3cde3440ff006be8" on tickets I'm not assigned to. 

* Additionally, run a second engagement pass for callouts to "Tier1 Release Managers" as per the skill directions.

* Write a prioritized briefing to an MD file in the output folder, with the date (YYYY-MM-DD) as the filename.



* Add  notable info that is surfaced during this task to the persistent memory

* After the MD report is ready, run the following python script from the output folder to transform the report to HTML:

`python .\script\md_to_html.py .\<YYYY-MM-DD>.md .\Reports\<YYYY-MM-DD>.html`

*  Always append a line to action_log.txt in the output folder:

  `[EET timestamp] | Daily briefing | [HTML report filename: YYYY-MM-DD.html]`