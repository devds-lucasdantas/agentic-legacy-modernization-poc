      * ACCOUNTS.CPY - Account Record Structure
       01  ACCOUNT-RECORD.
           05  ACC-NUMBER          PIC 9(10).
           05  ACC-CUSTOMER-NAME   PIC X(30).
           05  ACC-BALANCE         PIC S9(13)V99 COMP-3.
           05  ACC-STATUS          PIC X(1).
               88  ACC-ACTIVE      VALUE 'A'.
               88  ACC-CLOSED      VALUE 'C'.
               88  ACC-SUSPENDED   VALUE 'S'.
