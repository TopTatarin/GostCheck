"""Text-only rule specification for detailed thesis tasks."""

from __future__ import annotations

from normocontrol.semantic.batching import RuleSpec

TSK_02 = RuleSpec(
    rule_id="TSK-02",
    section_roles=("task",),
    requirement=(
        "Проверь развёрнутость задач: каждая должна быть привязана к тематике, содержать "
        "конкретное действие или метод и ожидаемый проверяемый результат. Однословные общие "
        "формулировки без контекста означают warn."
    ),
    elements=("contextualized_actions", "method_detail", "expected_outputs"),
)
