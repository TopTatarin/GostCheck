# Rubric rule coverage

This matrix is the machine-checked coverage inventory for the 64 rules in
`rubric.yaml`. `pending_decision` is deliberately not PASS: no rule is classified
as `manual_required` or `excluded_scope` until a responsible norm-control reviewer
records a written decision.

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
| TSK-02 | script+llm | semantic | semantic suite | implemented | Semantic portion is implemented; formal heuristic is pending. |
| TSK-03 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| ARC-01 | script+llm | formal + semantic | formal + semantic suites | implemented | Section-scoped figure presence plus advisory as-is/to-be rationale. |
| ARC-02 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| MTH-01 | class+script | formal | formal suite | implemented | Registered deterministic check. |
| MTH-02 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| MTH-03 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| ALG-01 | script+llm | formal + semantic | formal + semantic suites | implemented | Section-scoped figure/algorithm presence plus advisory suitability. |
| ALG-02 | vision | — | — | pending_decision | Vision/manual scope needs a signed reviewer decision. |
| ALG-03 | script+llm | formal + semantic | formal + semantic suites | implemented | Section-scoped «Блок N.» regex plus advisory completeness. |
| IMP-01 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| IMP-02 | vision | — | — | pending_decision | Vision/manual scope needs a signed reviewer decision. |
| RES-01 | script+llm | formal + semantic | formal + semantic suites | implemented | Section-scoped table/figure presence plus advisory result checklist. |
| CON-01 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| APP-01 | script | formal | formal suite | implemented | Deterministic Git repository URL check limited to appendix sections. |
| GEN-01 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| GEN-02 | llm | semantic | semantic suite | implemented | Strict advisory RuleSpec and evidence contract. |
| DEP-01 | script | — | — | pending_decision | Implementation requires approved oral-norm scope. |

## Decisions required

No written reviewer decisions are present for `ALG-02` or `IMP-02`; therefore they
remain `pending_decision`, not `manual_required` or `excluded_scope`. `DEP-01`
requires written approval of the oral norm before implementation. The incomplete
formal portion of `TSK-02` is also recorded above and is not silently treated as
covered by its semantic implementation.
