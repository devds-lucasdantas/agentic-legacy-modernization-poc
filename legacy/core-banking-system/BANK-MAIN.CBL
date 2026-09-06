       IDENTIFICATION DIVISION.
       PROGRAM-ID. BANK-MAIN.

       ENVIRONMENT DIVISION.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CHOICE  PIC X.

       PROCEDURE DIVISION.
       MAIN-MENU.
           PERFORM UNTIL WS-CHOICE = '4'
                   DISPLAY ' '
                   DISPLAY '=== CORE BANKING SYSTEM ==='
                   DISPLAY '1. Init Database'
                   DISPLAY '2. Transaction'
                   DISPLAY '3. Report'
                   DISPLAY '4. Exit'
                   DISPLAY 'Option: ' WITH NO ADVANCING
                   ACCEPT WS-CHOICE

                   EVALUATE WS-CHOICE
                   WHEN '1'
                        CALL 'INIT-DB'
                   WHEN '2'
                        CALL 'TRANS-PROC'
                   WHEN '3'
                        CALL 'REPORT-GEN'
                   WHEN '4'
                        DISPLAY 'Bye.'
                   WHEN OTHER
                        DISPLAY 'Invalid.'
                   END-EVALUATE
           END-PERFORM.

           STOP RUN.
