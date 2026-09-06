       IDENTIFICATION DIVISION.
       PROGRAM-ID. REPORT-GEN.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCOUNT-FILE ASSIGN TO 'ACCOUNTS.DAT'
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ACCOUNT-FILE.
       01 ACCOUNT-REC.
          05 REC-ACC-NUMBER   PIC 9(10).
          05 REC-ACC-NAME     PIC X(30).
          05 REC-ACC-BALANCE  PIC S9(13)V99.
          05 REC-ACC-STATUS   PIC X(1).

       WORKING-STORAGE SECTION.
       01 WS-EOF-FLAG         PIC X                  VALUE 'N'.
       01 WS-TOTAL-BAL        PIC S9(15)V99          VALUE 0.
       01 WS-COUNT            PIC 9(5)               VALUE 0.
       01 PRINT-LINE          PIC X(60)              VALUE ALL '-'.
       01 WS-FORMATTED-BAL    PIC $ZZ,ZZZ,ZZZ,ZZ9.99.

       PROCEDURE DIVISION.
       MAIN-PROCEDURE.
           OPEN INPUT ACCOUNT-FILE
           DISPLAY ' '
           DISPLAY '--- ACCOUNT BALANCE SUMMARY REPORT ---'
           DISPLAY PRINT-LINE
           DISPLAY 'NUM | NAME | BALANCE'
           DISPLAY PRINT-LINE

           PERFORM UNTIL WS-EOF-FLAG = 'Y'
                   READ ACCOUNT-FILE
                   AT END
                      MOVE 'Y' TO WS-EOF-FLAG
                   NOT AT END
                       MOVE REC-ACC-BALANCE TO WS-FORMATTED-BAL
                       DISPLAY REC-ACC-NUMBER
                       DISPLAY REC-ACC-NAME
                       DISPLAY WS-FORMATTED-BAL
                       DISPLAY ' '
                       ADD REC-ACC-BALANCE TO WS-TOTAL-BAL
                       ADD 1 TO WS-COUNT
                   END-READ
           END-PERFORM.

           CLOSE ACCOUNT-FILE.
           DISPLAY PRINT-LINE
           MOVE WS-TOTAL-BAL TO WS-FORMATTED-BAL
           DISPLAY 'TOTAL ACCOUNTS: ' WS-COUNT
           DISPLAY 'BANK BALANCE: ' WS-FORMATTED-BAL
           DISPLAY PRINT-LINE.

           STOP RUN.
