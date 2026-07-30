# Rubric rule coverage

This matrix is the machine-checked coverage inventory for the 64 rules in
`rubric.yaml`: 61 `implemented` and 3 `manual_required`, with no
`pending_decision` left. `manual_required` is deliberately not PASS — it is
coverage metadata, not a verification result for any document.

| rule_id | layer | implementation | test | status | rationale |
| --- | --- | --- | --- | --- | --- |
| SYS-01 | script | formal | formal suite | implemented | Registered deterministic check. |
| SYS-02 | script | formal | formal suite | implemented | Registered deterministic check. |
| SYS-03 | script | formal | formal suite | implemented | Registered deterministic check. |
| FMT-01 | class | formal | formal suite | implemented | Registered deterministic check. |
| FMT-02 | class | formal | formal suite | implemented | Registered deterministic check. |
| FMT-03 | class | formal | formal suite | implemented | Registered deterministic check. |
| FMT-04 | class | formal | formal suite | implemented | Registered deterministic check. |
| FMT-05 | class | formal | formal suite | implemented | Registered deterministic check. |
| FIG-01 | script | formal | formal suite | implemented | Registered deterministic check. |
| FIG-02 | script | formal | formal suite | implemented | Registered deterministic check. |
| FIG-03 | class+script | formal | formal suite | implemented | Registered deterministic check. |
| FIG-04 | class | formal | formal suite | implemented | Registered deterministic check. |
| FIG-05 | class | formal | formal suite | implemented | Registered deterministic check. |
| FIG-06 | class | formal | formal suite | implemented | Registered deterministic check. |
| FIG-07 | class | formal | formal suite | implemented | Registered deterministic check. |
| TAB-01 | class | formal | formal suite | implemented | Registered deterministic check. |
| TAB-02 | class+script | formal | formal suite | implemented | Registered deterministic check. |
| TAB-03 | script | formal | formal suite | implemented | Registered deterministic check. |
| CAP-01 | script | formal | formal suite | implemented | Registered deterministic check. |
| BIB-01 | script | formal | formal suite | implemented | Registered deterministic check. |
| BIB-02 | class+script | formal | formal suite | implemented | Registered deterministic check. |
| BIB-03 | class+script | formal | formal suite | implemented | Registered deterministic check. |
| BIB-04 | script | formal | formal suite | implemented | Registered deterministic check. |
| BIB-05 | script | formal | formal suite | implemented | Registered deterministic check. |
| STR-01 | script | formal | formal suite | implemented | Registered deterministic check. |
| STR-02 | class | formal | formal suite | implemented | Registered deterministic check. |
| STR-03 | script | formal | formal suite | implemented | Registered deterministic check. |
| STR-04 | script | formal | formal suite | implemented | Registered deterministic check. |
| STR-05 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| ANN-01 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| ANN-02 | script | formal | formal suite | implemented | Registered deterministic check. |
| ANN-03 | script | formal | formal suite | implemented | Declared pages/figures/tables/appendices are compared with compiled/source counters. |
| INT-01 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| INT-02 | script | formal | formal suite | implemented | Registered deterministic check. |
| REV-01 | script | formal | formal suite | implemented | Registered deterministic check. |
| REV-02 | script+llm | formal + semantic | formal + semantic suites | implemented | Heuristic plus strict advisory classification of edge cases. |
| REV-03 | script | formal | formal suite | implemented | Registered deterministic check. |
| REV-04 | script+llm | formal + semantic | formal + semantic suites | implemented | Blacklist plus strict advisory classification of edge cases. |
| REV-05 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| REV-06 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| REV-07 | script | formal | formal suite | implemented | Registered deterministic check. |
| SSA-01 | script+llm | formal + semantic | formal + semantic suites | implemented | Section-scoped figure presence plus advisory model/notation contract. |
| SSA-02 | llm | semantic | semantic suite | implemented | Conditional software applicability and integration contract. |
| SSA-03 | llm | semantic | semantic suite | implemented | Conditional computational applicability and data-table contract. |
| SSA-04 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| TSK-01 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| TSK-02 | script+llm | formal + semantic | formal + semantic suites | implemented | Section-scoped task-item length heuristic plus advisory expansion check. |
| TSK-03 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| ARC-01 | script+llm | formal + semantic | formal + semantic suites | implemented | Section-scoped figure presence plus advisory as-is/to-be rationale. |
| ARC-02 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| MTH-01 | class+script | formal | formal suite | implemented | Registered deterministic check. |
| MTH-02 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| MTH-03 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| ALG-01 | script+llm | formal + semantic | formal + semantic suites | implemented | Section-scoped figure/algorithm presence plus advisory suitability. |
| ALG-02 | manual | none (no automated check) | coverage matrix metadata test | manual_required | Text sufficiency inside flowchart blocks needs human visual review; decided in docs/rule-decisions/ALG-02-IMP-02-DEP-01.md. |
| ALG-03 | script+llm | formal + semantic | formal + semantic suites | implemented | Section-scoped «Блок N.» regex plus advisory completeness. |
| IMP-01 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| IMP-02 | manual | none (no automated check) | coverage matrix metadata test | manual_required | Screenshot content classification needs human visual judgement; decided in docs/rule-decisions/ALG-02-IMP-02-DEP-01.md. |
| RES-01 | script+llm | formal + semantic | formal + semantic suites | implemented | Section-scoped table/figure presence plus advisory result checklist. |
| CON-01 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| APP-01 | script | formal | formal suite | implemented | Deterministic Git repository URL check limited to appendix sections. |
| GEN-01 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| GEN-02 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| DEP-01 | manual | none (no automated check) | coverage matrix metadata test | manual_required | First-person usage and its exceptions need an editorial reviewer decision; decided in docs/rule-decisions/ALG-02-IMP-02-DEP-01.md. |

## Manual-only rules

`ALG-02`, `IMP-02` and `DEP-01` are `manual_required` by the written decision in
[docs/rule-decisions/ALG-02-IMP-02-DEP-01.md](rule-decisions/ALG-02-IMP-02-DEP-01.md).
They are checked by a norm-control reviewer outside GostCheck, which runs no
formal, semantic, vision, OCR or heuristic check for them.

`manual_required` is not `excluded_scope` and is not counted as implemented. The
absence of an automatic finding for these rules is not a PASS, and they never
affect the formal gate, `severity_final` or the exit code. GostCheck neither
collects nor stores the outcome of that manual review.
