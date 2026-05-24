---
name: Run rollup <% tp.file.title.replace(/^run_/, "") %>
description: Daily rollup of all hybrid runs on <% tp.file.title.replace(/^run_/, "") %>
type: rollup
run_date: <% tp.file.title.replace(/^run_/, "") %>
originSessionId: 118ca0c9-42ac-4086-a3dd-2345f48e563c
---
# Sequential test session — <% tp.file.title.replace(/^run_/, "") %>

## Services tested today

```dataview
TABLE service AS "Service", tcs AS "TCs", passes AS "P", fails AS "F", blocked AS "B", pass_rate + "%" AS "Pass %", worst_cluster AS "Worst cluster"
FROM "" AND -"_templates"
WHERE run_date = date("<% tp.file.title.replace(/^run_/, "") %>") AND service
SORT pass_rate DESC
```

## Linked memories from today

```dataview
LIST description
FROM "" AND -"_templates"
WHERE run_date = date("<% tp.file.title.replace(/^run_/, "") %>") AND type = "project"
SORT file.name ASC
```

## Day summary

- Highest pass rate:
- Lowest pass rate:
- Net trend vs last run:
- Catastrophic tier (services with <20% pass):
- Healthy tier (services with >50% pass):

## Cross-service themes

_Shared root causes, repeating cluster patterns, platform-level defects:_

-

## Action items

- [ ]

## Notes
