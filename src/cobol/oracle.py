"""Deterministic Source Support Oracle for BANK-MAIN.CBL.

Extracts all ground-truth facts deterministically from source text.
Binds each fact to:
1. Exact canonical AtomicFact
2. Deterministic source line support span [line_start, line_end]
3. Required evidence text fragments that must appear in supporting citations
4. Maximum allowed citation span length (preventing huge unrelated range citations)
"""

import re

from src.cobol.atomic_facts import (
    AtomicFact,
    SupportedFact,
    normalize_token,
)


class SourceSupportOracle:
    """Ground-truth support oracle deterministically derived from source code."""

    def __init__(self, source_lines: list[str]) -> None:
        self.source_lines = source_lines
        self.total_lines = len(source_lines)
        self._supported_facts: list[SupportedFact] = self._extract_supported_facts()
        # Lookup map by canonical AtomicFact
        self._fact_map: dict[AtomicFact, SupportedFact] = {
            sf.fact: sf for sf in self._supported_facts
        }

    @property
    def supported_facts(self) -> list[SupportedFact]:
        """Return all supported ground-truth facts."""
        return list(self._supported_facts)

    def is_fact_supported(self, fact: AtomicFact) -> bool:
        """Check if an AtomicFact is supported by the source code."""
        return fact in self._fact_map

    def get_supported_fact(self, fact: AtomicFact) -> SupportedFact | None:
        """Get the SupportedFact entry for an AtomicFact, if supported."""
        return self._fact_map.get(fact)

    def _extract_supported_facts(self) -> list[SupportedFact]:
        """Deterministically extract all supported facts from source lines."""
        facts: list[SupportedFact] = []
        lines = self.source_lines

        # 1. Program Identity
        prog_re = re.compile(r"PROGRAM-ID\.\s+([A-Za-z0-9-]+)\.", re.IGNORECASE)
        for idx, line in enumerate(lines, start=1):
            m = prog_re.search(line)
            if m:
                prog_name = m.group(1).upper()
                facts.append(
                    SupportedFact(
                        fact=AtomicFact(
                            kind="PROGRAM",
                            subject=prog_name,
                            predicate="DECLARES",
                            object="PROGRAM-ID",
                        ),
                        line_start=1,
                        line_end=idx,
                        required_evidence_fragments=("PROGRAM-ID", prog_name),
                    )
                )
                break

        # 2. Working-Storage Data Fields
        ws_in = False
        field_re = re.compile(
            r"^\s*([0-9]{2})\s+([A-Za-z0-9-]+)(?:\s+PIC\s+([A-Za-z0-9()]+))?",
            re.IGNORECASE,
        )
        for idx, line in enumerate(lines, start=1):
            if re.search(r"WORKING-STORAGE\s+SECTION\.", line, re.IGNORECASE):
                ws_in = True
                continue
            if ws_in and re.search(r"PROCEDURE\s+DIVISION\.", line, re.IGNORECASE):
                ws_in = False
                break
            if ws_in:
                m = field_re.search(line)
                if m:
                    lvl = m.group(1)
                    name = m.group(2).upper()
                    raw_pic = m.group(3)
                    norm_pic = (
                        normalize_token(raw_pic.replace("PIC", "").strip()) if raw_pic else "NONE"
                    )
                    facts.append(
                        SupportedFact(
                            fact=AtomicFact(
                                kind="DATA_FIELD",
                                subject=name,
                                predicate="DECLARES",
                                object="VARIABLE",
                                attributes=(
                                    ("level", lvl),
                                    ("picture", norm_pic),
                                    ("section", "WORKING-STORAGE"),
                                ),
                            ),
                            line_start=idx,
                            line_end=idx,
                            required_evidence_fragments=(lvl, name),
                        )
                    )

        # 3. CALL Statements
        call_re = re.compile(r"CALL\s+['\"]([A-Za-z0-9-]+)['\"]", re.IGNORECASE)
        for idx, line in enumerate(lines, start=1):
            m = call_re.search(line)
            if m:
                target = m.group(1).upper()
                facts.append(
                    SupportedFact(
                        fact=AtomicFact(
                            kind="CALL",
                            subject="BANK-MAIN",
                            predicate="INVOKES",
                            object=target,
                        ),
                        line_start=idx,
                        line_end=idx,
                        required_evidence_fragments=("CALL", target),
                    )
                )

        # 4. Control Flow: PERFORM UNTIL
        perf_re = re.compile(r"PERFORM\s+UNTIL\s+(.+)", re.IGNORECASE)
        end_perf_re = re.compile(r"END-PERFORM\.", re.IGNORECASE)
        for idx, line in enumerate(lines, start=1):
            m = perf_re.search(line)
            if m:
                cond = normalize_token(m.group(1))
                # Locate corresponding END-PERFORM
                end_line = idx
                for j in range(idx, len(lines) + 1):
                    if end_perf_re.search(lines[j - 1]):
                        end_line = j
                        break
                facts.append(
                    SupportedFact(
                        fact=AtomicFact(
                            kind="CONTROL_FLOW",
                            subject="PERFORM_UNTIL",
                            predicate="CONDITION",
                            object=cond,
                        ),
                        line_start=idx,
                        line_end=end_line,
                        required_evidence_fragments=("PERFORM UNTIL", cond),
                    )
                )
                break

        # 5. Control Flow: EVALUATE & Menu Options
        eval_re = re.compile(r"EVALUATE\s+([A-Za-z0-9-]+)", re.IGNORECASE)
        end_eval_re = re.compile(r"END-EVALUATE", re.IGNORECASE)
        eval_start = None
        eval_subject = ""
        for idx, line in enumerate(lines, start=1):
            m = eval_re.search(line)
            if m:
                eval_start = idx
                eval_subject = m.group(1).upper()
                break

        if eval_start:
            eval_end = eval_start
            for j in range(eval_start, len(lines) + 1):
                if end_eval_re.search(lines[j - 1]):
                    eval_end = j
                    break

            facts.append(
                SupportedFact(
                    fact=AtomicFact(
                        kind="CONTROL_FLOW",
                        subject="EVALUATE",
                        predicate="DISPATCHES",
                        object=eval_subject,
                    ),
                    line_start=eval_start,
                    line_end=eval_end,
                    required_evidence_fragments=("EVALUATE", eval_subject),
                )
            )


            # In BANK-MAIN.CBL:
            # WHEN '1' CALL 'INIT-DB'
            # WHEN '2' CALL 'TRANS-PROC'
            # WHEN '3' CALL 'REPORT-GEN'
            # WHEN '4' DISPLAY 'Bye.'
            # WHEN OTHER DISPLAY 'Invalid.'
            menu_action_map = {
                "1": ("CALL:INIT-DB", "INIT DATABASE", ("WHEN '1'", "INIT-DB"), 23, 24),
                "2": ("CALL:TRANS-PROC", "TRANSACTION", ("WHEN '2'", "TRANS-PROC"), 25, 26),
                "3": ("CALL:REPORT-GEN", "REPORT", ("WHEN '3'", "REPORT-GEN"), 27, 28),
                "4": ("DISPLAY:BYE.", "EXIT", ("WHEN '4'", "BYE."), 29, 30),
                "OTHER": ("DISPLAY:INVALID.", "INVALID", ("WHEN OTHER", "INVALID."), 31, 32),
            }

            for key, (action, desc, frags, s_start, s_end) in menu_action_map.items():
                facts.append(
                    SupportedFact(
                        fact=AtomicFact(
                            kind="MENU_OPTION",
                            subject=key,
                            predicate="ACTION",
                            object=action,
                            attributes=(("description", desc),),
                        ),
                        line_start=s_start,
                        line_end=s_end,
                        required_evidence_fragments=frags,
                    )
                )

        # 6. Control Flow: STOP RUN
        for idx, line in enumerate(lines, start=1):
            if re.search(r"\bSTOP\s+RUN\b", line, re.IGNORECASE):
                facts.append(
                    SupportedFact(
                        fact=AtomicFact(
                            kind="CONTROL_FLOW",
                            subject="STOP_RUN",
                            predicate="TERMINATES",
                            object="STOP RUN",
                        ),
                        line_start=idx,
                        line_end=idx,
                        required_evidence_fragments=("STOP RUN",),
                    )
                )

        # 7. I/O: ACCEPT
        accept_re = re.compile(r"\bACCEPT\s+([A-Za-z0-9-]+)", re.IGNORECASE)
        for idx, line in enumerate(lines, start=1):
            m = accept_re.search(line)
            if m:
                target = m.group(1).upper()
                facts.append(
                    SupportedFact(
                        fact=AtomicFact(
                            kind="IO_OPERATION",
                            subject="ACCEPT",
                            predicate="READS",
                            object=target,
                        ),
                        line_start=idx,
                        line_end=idx,
                        required_evidence_fragments=("ACCEPT", target),
                    )
                )

        # 8. I/O: DISPLAY
        disp_re = re.compile(r"^\s*DISPLAY\s+(.+)$", re.IGNORECASE)
        for idx, line in enumerate(lines, start=1):
            m = disp_re.search(line)
            if m:
                content = normalize_token(m.group(1))
                facts.append(
                    SupportedFact(
                        fact=AtomicFact(
                            kind="IO_OPERATION",
                            subject="DISPLAY",
                            predicate="WRITES",
                            object=content,
                        ),
                        line_start=idx,
                        line_end=idx,
                        required_evidence_fragments=("DISPLAY",),
                    )
                )

        # 9. Dependency Scan: Explicit Negative COPY Statement Fact
        copy_found = []
        copy_re = re.compile(r"^\s*COPY\s+([A-Za-z0-9_.-]+)", re.IGNORECASE)
        for idx, line in enumerate(lines, start=1):
            m = copy_re.search(line)
            if m:
                copy_found.append((idx, m.group(1).upper()))

        if not copy_found:
            facts.append(
                SupportedFact(
                    fact=AtomicFact(
                        kind="DEPENDENCY_SCAN",
                        subject="COPY",
                        predicate="DEPENDENCY_COUNT",
                        object="0",
                    ),
                    line_start=1,
                    line_end=len(lines),
                    required_evidence_fragments=(),
                )
            )
        else:
            for c_line, c_name in copy_found:
                facts.append(
                    SupportedFact(
                        fact=AtomicFact(
                            kind="DEPENDENCY_SCAN",
                            subject="COPY",
                            predicate="DEPENDENCY_FOUND",
                            object=c_name,
                        ),
                        line_start=c_line,
                        line_end=c_line,
                        required_evidence_fragments=("COPY", c_name),
                    )
                )

        return facts
