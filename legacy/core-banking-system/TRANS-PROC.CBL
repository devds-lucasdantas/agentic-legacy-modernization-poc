       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRANS-PROC.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCOUNT-FILE ASSIGN TO 'ACCOUNTS.DAT'
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT TEMP-FILE ASSIGN TO 'ACCOUNTS.TMP'
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ACCOUNT-FILE.
       01 ACCOUNT-REC.
          05 REC-ACC-NUMBER    PIC 9(10).
          05 REC-ACC-NAME      PIC X(30).
          05 REC-ACC-BALANCE   PIC S9(13)V99.
          05 REC-ACC-STATUS    PIC X(1).

       FD  TEMP-FILE.
       01 TEMP-REC.
          05 TEMP-ACC-NUMBER   PIC 9(10).
          05 TEMP-ACC-NAME     PIC X(30).
          05 TEMP-ACC-BALANCE  PIC S9(13)V99.
          05 TEMP-ACC-STATUS   PIC X(1).

       WORKING-STORAGE SECTION.
       01 WS-EOF-FLAG          PIC X         VALUE 'N'.
       01 WS-FOUND-FLAG        PIC X         VALUE 'N'.
       01 WS-TRANS-TYPE        PIC X.
       01 WS-TRANS-AMOUNT      PIC 9(13)V99.
       01 WS-TARGET-ACC        PIC 9(10).
       01 WS-CMD               PIC X(100).

       PROCEDURE DIVISION.
       MAIN-PROCEDURE.
           DISPLAY '--- TRANSACTION ---'
           DISPLAY 'Account Number: ' WITH NO ADVANCING
           ACCEPT WS-TARGET-ACC
           DISPLAY 'Type (D/W): ' WITH NO ADVANCING
           ACCEPT WS-TRANS-TYPE
           DISPLAY 'Amount: ' WITH NO ADVANCING
           ACCEPT WS-TRANS-AMOUNT.

           OPEN INPUT ACCOUNT-FILE
           OPEN OUTPUT TEMP-FILE

           MOVE 'N' TO WS-EOF-FLAG
           MOVE 'N' TO WS-FOUND-FLAG

           PERFORM UNTIL WS-EOF-FLAG = 'Y'
                   READ ACCOUNT-FILE
                   AT END
                      MOVE 'Y' TO WS-EOF-FLAG
                   NOT AT END
                       IF REC-ACC-NUMBER = WS-TARGET-ACC
                          MOVE 'Y' TO WS-FOUND-FLAG
                          IF WS-TRANS-TYPE = 'D' OR 'd'
                             ADD WS-TRANS-AMOUNT TO REC-ACC-BALANCE
                             DISPLAY 'Deposit Ok.'
                          ELSE
                             IF WS-TRANS-TYPE = 'W' OR 'w'
                                IF REC-ACC-BALANCE >= WS-TRANS-AMOUNT
                                   SUBTRACT WS-TRANS-AMOUNT
                                      FROM REC-ACC-BALANCE
                                   DISPLAY 'Withdrawal Ok.'
                                ELSE
                                   DISPLAY 'No Funds.'
                                END-IF
                             ELSE
                                DISPLAY 'Invalid Type.'
                             END-IF
                          END-IF
                       END-IF
                       MOVE ACCOUNT-REC TO TEMP-REC
                       WRITE TEMP-REC
                   END-READ
           END-PERFORM.

           CLOSE ACCOUNT-FILE
           CLOSE TEMP-FILE.

           IF WS-FOUND-FLAG = 'Y'
              DISPLAY 'Saving...'
              MOVE 'cmd /c del ACCOUNTS.DAT' TO WS-CMD
              CALL 'SYSTEM' USING WS-CMD
              MOVE 'cmd /c ren ACCOUNTS.TMP ACCOUNTS.DAT' TO WS-CMD
              CALL 'SYSTEM' USING WS-CMD
           ELSE
              DISPLAY 'Not Found.'
              MOVE 'cmd /c del ACCOUNTS.TMP' TO WS-CMD
              CALL 'SYSTEM' USING WS-CMD
           END-IF.

           STOP RUN.
