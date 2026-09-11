"""In-memory COBOL source mutation test suite.

Proves that SourceFactExtractor and SourceSupportIndex dynamically derive facts
from source text rather than relying on fixture answers.
Zero modifications to real legacy files — all mutations are performed in memory.
"""

from pathlib import Path

import pytest

from src.cobol.fact_extractor import SourceFactExtractor

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def base_source_lines() -> list[str]:
    path = REPO_ROOT / "legacy" / "core-banking-system" / "BANK-MAIN.CBL"
    return path.read_text(encoding="utf-8").splitlines()


class TestSourceFactExtractorMutations:
    """Validate dynamic source extraction under in-memory mutations."""

    def test_rename_program_id(self, base_source_lines):
        mutated = list(base_source_lines)
        mutated[1] = "       PROGRAM-ID. MUTATED-MODULE."
        extractor = SourceFactExtractor(mutated)
        res = extractor.extract()

        assert res.program_id == "MUTATED-MODULE"
        prog_facts = [occ for occ in res.occurrences if occ.fact.kind == "PROGRAM"]
        assert len(prog_facts) == 1
        assert prog_facts[0].fact.subject == "MUTATED-MODULE"

        # CALL caller must dynamically follow the renamed PROGRAM-ID
        call_facts = [occ for occ in res.occurrences if occ.fact.kind == "CALL"]
        assert len(call_facts) == 3
        for cf in call_facts:
            assert cf.fact.subject == "MUTATED-MODULE"

    def test_swap_call_targets(self, base_source_lines):
        mutated = list(base_source_lines)
        # Line 24 is CALL 'INIT-DB'
        mutated[23] = "           CALL 'CUSTOM-PROC'"
        extractor = SourceFactExtractor(mutated)
        res = extractor.extract()

        call_targets = {occ.fact.object for occ in res.occurrences if occ.fact.kind == "CALL"}
        assert "CUSTOM-PROC" in call_targets
        assert "INIT-DB" not in call_targets

    def test_change_menu_branch_action(self, base_source_lines):
        mutated = list(base_source_lines)
        # Change WHEN '1' action from CALL 'INIT-DB' to DISPLAY 'Hello'
        mutated[23] = "               DISPLAY 'Hello'"
        extractor = SourceFactExtractor(mutated)
        res = extractor.extract()

        menu_1 = [
            occ
            for occ in res.occurrences
            if occ.fact.kind == "MENU_OPTION" and occ.fact.subject == "1"
        ]
        assert len(menu_1) == 1
        assert menu_1[0].fact.predicate == "DISPLAYS"
        assert menu_1[0].fact.object == "Hello"

    def test_inserted_blank_lines_shift_spans_dynamically(self, base_source_lines):
        mutated = list(base_source_lines)
        # Insert 5 blank lines right before line 22 (EVALUATE)
        mutated = mutated[:21] + ["", "", "", "", ""] + mutated[21:]
        extractor = SourceFactExtractor(mutated)
        res = extractor.extract()

        # In original, EVALUATE starts at line 22; with 5 inserted lines it must start at 27
        eval_facts = [
            occ
            for occ in res.occurrences
            if occ.fact.kind == "CONTROL_FLOW" and occ.fact.subject == "EVALUATE"
        ]
        assert len(eval_facts) == 1
        assert eval_facts[0].line_start == 27
        assert eval_facts[0].line_end == 33 + 5

    def test_comment_containing_call_is_ignored(self, base_source_lines):
        mutated = list(base_source_lines)
        # Insert a fixed-format comment line with CALL at col 7
        mutated.insert(20, "      *CALL 'FAKE-COMMENT-CALL'")
        extractor = SourceFactExtractor(mutated)
        res = extractor.extract()

        call_targets = {occ.fact.object for occ in res.occurrences if occ.fact.kind == "CALL"}
        assert "FAKE-COMMENT-CALL" not in call_targets

    def test_inline_comment_containing_call_is_ignored(self, base_source_lines):
        mutated = list(base_source_lines)
        mutated[23] = "           CALL 'INIT-DB' *> CALL 'FAKE-INLINE-CALL'"
        extractor = SourceFactExtractor(mutated)
        res = extractor.extract()

        call_targets = {occ.fact.object for occ in res.occurrences if occ.fact.kind == "CALL"}
        assert "FAKE-INLINE-CALL" not in call_targets
        assert "INIT-DB" in call_targets

    def test_call_keyword_inside_display_literal_is_ignored(self, base_source_lines):
        mutated = list(base_source_lines)
        # Line 15 is DISPLAY '1. Init Database' -> change to DISPLAY 'CALL FAKE-SUBPROGRAM'
        mutated[14] = "           DISPLAY 'CALL FAKE-SUBPROGRAM'"
        extractor = SourceFactExtractor(mutated)
        res = extractor.extract()

        call_targets = {occ.fact.object for occ in res.occurrences if occ.fact.kind == "CALL"}
        assert "FAKE-SUBPROGRAM" not in call_targets

    def test_data_division_section_tracking(self, base_source_lines):
        mutated = list(base_source_lines)
        # Change WORKING-STORAGE SECTION to FILE SECTION
        mutated[6] = "       FILE SECTION."
        extractor = SourceFactExtractor(mutated)
        res = extractor.extract()

        # Should not extract ws fields if not in working-storage
        ws_fields = [occ for occ in res.occurrences if occ.fact.kind == "DATA_FIELD"]
        assert len(ws_fields) == 0

    def test_positive_copy_statement_is_extracted(self, base_source_lines):
        mutated = list(base_source_lines)
        mutated.insert(5, "       COPY ACCOUNTS-CPY.")
        extractor = SourceFactExtractor(mutated)
        res = extractor.extract()

        copy_facts = [occ for occ in res.occurrences if occ.fact.kind == "DEPENDENCY_SCAN"]
        assert any(
            cf.fact.predicate == "DEPENDENCY_FOUND" and cf.fact.object == "ACCOUNTS-CPY"
            for cf in copy_facts
        )
        assert not any(cf.fact.predicate == "DEPENDENCY_COUNT" for cf in copy_facts)

    def test_unsupported_malformed_copy_fails_closed(self, base_source_lines):
        """Amendment 2: Unrecognized/ambiguous COPY syntax must fail closed and NOT emit count=0."""
        mutated = list(base_source_lines)
        # Malformed COPY without target identifier
        mutated.insert(5, "       COPY ???.")
        extractor = SourceFactExtractor(mutated)
        res = extractor.extract()

        assert res.parse_complete is False
        assert res.unsupported_statement_count >= 1
        # Must NOT emit authoritative negative absence fact
        assert not any(
            occ.fact.kind == "DEPENDENCY_SCAN" and occ.fact.predicate == "DEPENDENCY_COUNT"
            for occ in res.occurrences
        )
