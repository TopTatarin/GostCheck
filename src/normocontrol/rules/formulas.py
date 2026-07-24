"""MTH-01 formula numbering rule."""

from __future__ import annotations

import re

from normocontrol.domain import FindingStatus, RuleLayer
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules._class_text import class_file_text
from normocontrol.rules._rule_outcomes import combine_class_script, rule_outcome
from normocontrol.rules.base import RuleRunOutcome
from normocontrol.rules.context import ExecutionContext, SourceKind
from normocontrol.rules.latex_source import LatexProjectReader
from normocontrol.rules.latex_symbols import contains_unnumbered_display_math

_MATH_SECTION = "Математическая модель"


class Mth01NumberedEquationsRule:
    rule_id = "MTH-01"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        assert context.latex is not None
        cls_text = class_file_text(context)
        reader = LatexProjectReader.load(context.latex.root, context.latex.main_tex)
        class_ok = cls_text is not None and (
            re.search(r"\\RequirePackage\{amsmath\}|\\usepackage\{amsmath\}", cls_text) is not None
            or re.search(r"\\begin\{equation\}", cls_text) is not None
        )
        section_body = reader.section_body(_MATH_SECTION)
        if section_body is None:
            return rule_outcome(
                rule,
                layer=RuleLayer.CLASS_SCRIPT,
                status=FindingStatus.NOT_APPLICABLE,
                message=f"раздел «{_MATH_SECTION}» не найден",
            )
        script_ok = not contains_unnumbered_display_math(section_body)
        return combine_class_script(
            rule,
            class_ok=class_ok,
            script_ok=script_ok,
            pass_message="формулы в разделе 6 пронумерованы",
            class_fail_message="класс не включает amsmath/нумерацию equation",
            script_fail_message="в разделе обнаружены \\[ \\], $$ или equation*",
            class_missing_message="защищённый .cls недоступен",
            script_missing_message="раздел «Математическая модель» не найден",
        )


def formula_rules() -> tuple[Mth01NumberedEquationsRule,]:
    return (Mth01NumberedEquationsRule(),)
