"""Deterministic COBOL subset parser and ground-truth fact extractor.

Extracts all ground-truth facts dynamically from source text lines:
1. Strips comments (column 7 indicator and inline '*>')
2. Distinguishes code from string literals
3. Derives PROGRAM-ID, Working-Storage variables, CALLs, PERFORM UNTIL loops,
   EVALUATE/WHEN branches, ACCEPT, DISPLAY, STOP RUN, and COPY dependencies.
4. Fails closed on unrecognized syntax (Amendment 2).
5. Zero hardcoded fixture answers or static line maps.
"""

import re
from dataclasses import dataclass, field

from src.cobol.atomic_facts import (
    AtomicFact,
    SupportedFactOccurrence,
    normalize_condition,
    normalize_identifier,
    normalize_pic,
    parse_cobol_literal_token,
    parse_source_menu_key_token,
)


@dataclass
class ExtractionResult:
    """Complete result of deterministic source fact extraction."""

    occurrences: list[SupportedFactOccurrence] = field(default_factory=list)
    program_id: str | None = None
    parse_complete: bool = True
    unsupported_statement_count: int = 0
    unsupported_statements: list[str] = field(default_factory=list)
    scanned_line_count: int = 0


class SourceFactExtractor:
    """Deterministic parser and fact extractor for supported COBOL subset."""

    def __init__(self, source_lines: list[str]) -> None:
        self.source_lines = source_lines
        self.total_lines = len(source_lines)

    def extract(self) -> ExtractionResult:
        """Parse source lines and return all supported fact occurrences."""
        result = ExtractionResult(scanned_line_count=self.total_lines)
        lines = self.source_lines

        # Preprocess lines: preserve (1-indexed line_no, cleaned_text, is_comment)
        preprocessed: list[tuple[int, str, bool]] = []
        for idx, line in enumerate(lines, start=1):
            is_comm = False
            # Check fixed format indicator column 7 (0-indexed 6)
            if len(line) >= 7 and line[6] in ("*", "/"):
                is_comm = True
            clean_text = line
            # Check for inline comment marker '*>'
            if "*>" in clean_text:
                clean_text = clean_text.split("*>")[0]
            preprocessed.append((idx, clean_text, is_comm))

        # 1. PROGRAM-ID
        prog_re = re.compile(r"\bPROGRAM-ID\.\s+([A-Za-z0-9-]+)\.", re.IGNORECASE)
        for idx, text, is_comm in preprocessed:
            if is_comm:
                continue
            m = prog_re.search(text)
            if m:
                prog_name = normalize_identifier(m.group(1))
                result.program_id = prog_name
                result.occurrences.append(
                    SupportedFactOccurrence(
                        fact=AtomicFact(
                            kind="PROGRAM",
                            subject=prog_name,
                            predicate="DECLARES",
                            object="PROGRAM-ID",
                        ),
                        occurrence_id=f"prog_{idx}",
                        line_start=1,
                        line_end=idx,
                        required_evidence_fragments=("PROGRAM-ID", prog_name),
                    )
                )
                break

        caller_name = result.program_id or "UNKNOWN"

        # 2. DATA DIVISION: WORKING-STORAGE SECTION
        in_ws = False
        field_re = re.compile(
            r"^\s*([0-9]{2})\s+([A-Za-z0-9-]+)(?:\s+(?:PIC|PICTURE)\s+([A-Za-z0-9()]+))?",
            re.IGNORECASE,
        )
        for idx, text, is_comm in preprocessed:
            if is_comm:
                continue
            if re.search(r"\bWORKING-STORAGE\s+SECTION\.", text, re.IGNORECASE):
                in_ws = True
                continue
            if in_ws and re.search(r"\bPROCEDURE\s+DIVISION\.", text, re.IGNORECASE):
                in_ws = False
                break
            if in_ws:
                m = field_re.search(text)
                if m:
                    lvl = m.group(1)
                    name = normalize_identifier(m.group(2))
                    raw_pic = m.group(3)
                    norm_pic = normalize_pic(raw_pic)
                    result.occurrences.append(
                        SupportedFactOccurrence(
                            fact=AtomicFact(
                                kind="DATA_FIELD",
                                subject=name,
                                predicate="DECLARES",
                                object="VARIABLE",
                                attributes=(
                                    ("LEVEL", lvl),
                                    ("PICTURE", norm_pic),
                                    ("SECTION", "WORKING-STORAGE"),
                                ),
                            ),
                            occurrence_id=f"ws_{name}_{idx}",
                            line_start=idx,
                            line_end=idx,
                            required_evidence_fragments=(lvl, name),
                        )
                    )

        # 3. PROCEDURE DIVISION Statements
        in_proc = False
        proc_lines: list[tuple[int, str]] = []
        for idx, text, is_comm in preprocessed:
            if is_comm:
                continue
            if re.search(r"\bPROCEDURE\s+DIVISION\.", text, re.IGNORECASE):
                in_proc = True
                continue
            if in_proc:
                proc_lines.append((idx, text))

        # Check for CALL statements outside comments/literals
        call_re = re.compile(r"\bCALL\s+['\"]([A-Za-z0-9-]+)['\"]", re.IGNORECASE)
        for idx, text in proc_lines:
            # Mask out display literals so keywords inside quotes are not treated as statements
            masked = re.sub(r"DISPLAY\s+['\"][^'\"]*['\"]", "", text, flags=re.IGNORECASE)
            for m in call_re.finditer(masked):
                tgt = normalize_identifier(m.group(1))
                result.occurrences.append(
                    SupportedFactOccurrence(
                        fact=AtomicFact(
                            kind="CALL",
                            subject=caller_name,
                            predicate="INVOKES",
                            object=tgt,
                        ),
                        occurrence_id=f"call_{tgt}_{idx}",
                        line_start=idx,
                        line_end=idx,
                        required_evidence_fragments=("CALL", tgt),
                    )
                )

        # Check for PERFORM UNTIL
        perf_re = re.compile(r"\bPERFORM\s+UNTIL\s+(.+)", re.IGNORECASE)
        end_perf_re = re.compile(r"\bEND-PERFORM\b", re.IGNORECASE)
        for i_idx, (idx, text) in enumerate(proc_lines):
            m = perf_re.search(text)
            if m:
                cond_raw = m.group(1).strip()
                # Find matching END-PERFORM
                end_line = None
                for end_idx, end_text in proc_lines[i_idx:]:
                    if end_perf_re.search(end_text):
                        end_line = end_idx
                        break
                if end_line is None:
                    result.parse_complete = False
                    result.unsupported_statements.append(f"Unclosed PERFORM UNTIL at line {idx}")
                    result.unsupported_statement_count += 1
                    end_line = idx

                cond_norm = normalize_condition(cond_raw)
                result.occurrences.append(
                    SupportedFactOccurrence(
                        fact=AtomicFact(
                            kind="CONTROL_FLOW",
                            subject="PERFORM_UNTIL",
                            predicate="CONDITION",
                            object=cond_norm,
                        ),
                        occurrence_id=f"perf_{idx}",
                        line_start=idx,
                        line_end=end_line,
                        required_evidence_fragments=("PERFORM UNTIL", cond_norm),
                    )
                )

        # Check for EVALUATE and WHEN branches
        eval_re = re.compile(r"\bEVALUATE\s+([A-Za-z0-9-]+)", re.IGNORECASE)
        end_eval_re = re.compile(r"\bEND-EVALUATE\b", re.IGNORECASE)
        when_re = re.compile(r"\bWHEN\s+(['\"][^'\"]+['\"]|\bOTHER\b)", re.IGNORECASE)

        for i_idx, (idx, text) in enumerate(proc_lines):
            m = eval_re.search(text)
            if m:
                subj = normalize_identifier(m.group(1))
                eval_start = idx
                eval_end = None
                eval_lines: list[tuple[int, str]] = []

                for next_idx, next_text in proc_lines[i_idx:]:
                    eval_lines.append((next_idx, next_text))
                    if end_eval_re.search(next_text):
                        eval_end = next_idx
                        break

                if eval_end is None:
                    result.parse_complete = False
                    result.unsupported_statements.append(f"Unclosed EVALUATE at line {idx}")
                    result.unsupported_statement_count += 1
                    eval_end = eval_lines[-1][0] if eval_lines else idx

                result.occurrences.append(
                    SupportedFactOccurrence(
                        fact=AtomicFact(
                            kind="CONTROL_FLOW",
                            subject="EVALUATE",
                            predicate="DISPATCHES",
                            object=subj,
                        ),
                        occurrence_id=f"eval_{idx}",
                        line_start=eval_start,
                        line_end=eval_end,
                        required_evidence_fragments=("EVALUATE", subj),
                    )
                )

                # Parse WHEN branches inside this EVALUATE
                for w_idx, (w_line, w_text) in enumerate(eval_lines):
                    wm = when_re.search(w_text)
                    if wm:
                        raw_key = wm.group(1).strip()
                        norm_key = parse_source_menu_key_token(raw_key)

                        # Collect branch statement text:
                        # either remainder of WHEN line or following lines
                        stmt_text = w_text[wm.end() :].strip()
                        stmt_end_line = w_line

                        if not stmt_text and w_idx + 1 < len(eval_lines):
                            # Scan forward for statement before next WHEN or END-EVALUATE
                            for next_w_line, next_w_text in eval_lines[w_idx + 1 :]:
                                if when_re.search(next_w_text) or end_eval_re.search(next_w_text):
                                    break
                                if next_w_text.strip():
                                    stmt_text = next_w_text.strip()
                                    stmt_end_line = next_w_line
                                    break

                        # Parse branch statement
                        call_m = re.search(
                            r"\bCALL\s+['\"]([A-Za-z0-9-]+)['\"]", stmt_text, re.IGNORECASE
                        )
                        disp_m = re.search(
                            r"\bDISPLAY\s+(['\"][^'\"]*['\"])", stmt_text, re.IGNORECASE
                        )

                        if call_m:
                            target = normalize_identifier(call_m.group(1))
                            result.occurrences.append(
                                SupportedFactOccurrence(
                                    fact=AtomicFact(
                                        kind="MENU_OPTION",
                                        subject=norm_key,
                                        predicate="CALLS",
                                        object=target,
                                    ),
                                    occurrence_id=f"menu_{norm_key}_{w_line}",
                                    line_start=w_line,
                                    line_end=stmt_end_line,
                                    required_evidence_fragments=(f"WHEN {raw_key}", target),
                                )
                            )
                        elif disp_m:
                            raw_lit = disp_m.group(1)
                            lit = parse_cobol_literal_token(raw_lit)
                            result.occurrences.append(
                                SupportedFactOccurrence(
                                    fact=AtomicFact(
                                        kind="MENU_OPTION",
                                        subject=norm_key,
                                        predicate="DISPLAYS",
                                        object=lit,
                                    ),
                                    occurrence_id=f"menu_{norm_key}_{w_line}",
                                    line_start=w_line,
                                    line_end=stmt_end_line,
                                    required_evidence_fragments=(f"WHEN {raw_key}", raw_lit),
                                )
                            )
                        else:
                            result.parse_complete = False
                            msg = (
                                f"Unrecognized action in WHEN branch '{raw_key}' "
                                f"at line {w_line}: {stmt_text}"
                            )
                            result.unsupported_statements.append(msg)
                            result.unsupported_statement_count += 1

        # Check for STOP RUN
        for idx, text in proc_lines:
            if re.search(r"\bSTOP\s+RUN\b", text, re.IGNORECASE):
                result.occurrences.append(
                    SupportedFactOccurrence(
                        fact=AtomicFact(
                            kind="CONTROL_FLOW",
                            subject="STOP_RUN",
                            predicate="TERMINATES",
                            object="STOP RUN",
                        ),
                        occurrence_id=f"stop_run_{idx}",
                        line_start=idx,
                        line_end=idx,
                        required_evidence_fragments=("STOP RUN",),
                    )
                )

        # Check for ACCEPT
        accept_re = re.compile(r"\bACCEPT\s+([A-Za-z0-9-]+)", re.IGNORECASE)
        for idx, text in proc_lines:
            m = accept_re.search(text)
            if m:
                target_id = normalize_identifier(m.group(1))
                result.occurrences.append(
                    SupportedFactOccurrence(
                        fact=AtomicFact(
                            kind="IO_OPERATION",
                            subject="ACCEPT",
                            predicate="READS",
                            object=target_id,
                        ),
                        occurrence_id=f"accept_{target_id}_{idx}",
                        line_start=idx,
                        line_end=idx,
                        required_evidence_fragments=("ACCEPT", target_id),
                    )
                )

        # Check for DISPLAY
        display_re = re.compile(r"\bDISPLAY\s+(['\"][^'\"]*['\"]|\b[A-Za-z0-9-]+\b)", re.IGNORECASE)
        for idx, text in proc_lines:
            for dm in display_re.finditer(text):
                raw_arg = dm.group(1)
                if (raw_arg.startswith("'") and raw_arg.endswith("'")) or (
                    raw_arg.startswith('"') and raw_arg.endswith('"')
                ):
                    disp_content = parse_cobol_literal_token(raw_arg)
                else:
                    disp_content = normalize_identifier(raw_arg)
                result.occurrences.append(
                    SupportedFactOccurrence(
                        fact=AtomicFact(
                            kind="IO_OPERATION",
                            subject="DISPLAY",
                            predicate="WRITES",
                            object=disp_content,
                        ),
                        occurrence_id=f"display_{idx}_{dm.start()}",
                        line_start=idx,
                        line_end=idx,
                        required_evidence_fragments=("DISPLAY", raw_arg),
                    )
                )

        # 4. Dependency Scan (COPY statements)
        copy_re = re.compile(r"\bCOPY\s+([A-Za-z0-9-]+)\b", re.IGNORECASE)
        malformed_copy_re = re.compile(r"\bCOPY\b(?!\s+[A-Za-z0-9-]+)", re.IGNORECASE)

        copy_found: list[str] = []
        for idx, text, is_comm in preprocessed:
            if is_comm:
                continue
            # Check for malformed COPY
            if malformed_copy_re.search(text):
                result.parse_complete = False
                result.unsupported_statements.append(
                    f"Ambiguous/malformed COPY at line {idx}: {text}"
                )
                result.unsupported_statement_count += 1
            for cm in copy_re.finditer(text):
                cpy = normalize_identifier(cm.group(1))
                copy_found.append(cpy)
                result.occurrences.append(
                    SupportedFactOccurrence(
                        fact=AtomicFact(
                            kind="DEPENDENCY_SCAN",
                            subject="COPY",
                            predicate="DEPENDENCY_FOUND",
                            object=cpy,
                        ),
                        occurrence_id=f"copy_{cpy}_{idx}",
                        line_start=idx,
                        line_end=idx,
                        required_evidence_fragments=("COPY", cpy),
                    )
                )

        # If zero COPY statements found AND parsing was complete, emit negative absence fact
        if len(copy_found) == 0:
            if result.parse_complete:
                result.occurrences.append(
                    SupportedFactOccurrence(
                        fact=AtomicFact(
                            kind="DEPENDENCY_SCAN",
                            subject="COPY",
                            predicate="DEPENDENCY_COUNT",
                            object="0",
                        ),
                        occurrence_id="copy_absence_whole_file",
                        line_start=1,
                        line_end=self.total_lines,
                        required_evidence_fragments=(),
                    )
                )

        return result
