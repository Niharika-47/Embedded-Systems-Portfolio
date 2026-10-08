/* =========================================================================
   RFID-Based Door Access Control with GSM SMS Alerts
   Target: LPC1768 (ARM Cortex-M3)

   - UART0  -> RFID reader   (P0.2 = TXD0, P0.3 = RXD0)
   - UART1  -> SIM900 GSM    (P0.15 = TXD1, P0.16 = RXD1)
   - LCD    -> RS = P0.4, EN = P0.5, D0-D7 = P1.19-P1.26
   - P0.29  -> Status/Lock LED (also doubles as alarm indicator)
   - P0.30  -> Magnetic door contact sensor (input)

   Behaviour:
   1. Waits for an RFID tag scan on UART0.
   2. If the tag matches the authorized card -> unlocks door, shows
      "ACCESS GRANTED" on the LCD, and texts the owner.
   3. If the tag does not match -> keeps the door locked, shows
      "ACCESS DENIED", and texts the owner an unauthorized-attempt alert.
   4. Independently watches the magnetic door sensor: if the door is
      opened without a valid RFID scan immediately before it, it is
      treated as a forced/intrusion event and triggers an SMS alert.

   Set PHONE_NUMBER below to the number that should receive alerts.
   ========================================================================= */

#include <LPC17xx.h>
#include <string.h>

/* ---------------- UART0 (RFID Reader) ---------------- */
void uart0_init(void);
char uart0_rx(void);
void uart0_tx(char c);
void uart0_tx_string(char *str);

/* ---------------- UART1 (GSM SIM900) ---------------- */
void uart1_init(void);
void uart1_tx(char c);
void uart1_tx_string(char *str);
void gsm_send_sms(char *number, char *message);

/* ---------------- LCD ---------------- */
void lcd_init(void);
void lcd_cmd(unsigned char cmd);
void lcd_data(unsigned char data);
void lcd_string(char *str);
void lcd_clear(void);
void lcd_goto(unsigned char row, unsigned char column);

/* ---------------- Delay ---------------- */
void delay(unsigned long int x);

/* ---------------- Configuration ---------------- */
#define PHONE_NUMBER "+91XXXXXXXXXX"   /* <-- set the alert recipient's number */


int main(void)
{
    char authorized_card[13] = "09008206BE33";
    char input_buffer[13];

    int i;
    int match_found;

    SystemInit();


    /* =================================================
       UART0 - RFID Reader

       P0.2 = TXD0
       P0.3 = RXD0
       ================================================= */

    LPC_PINCON->PINSEL0 |= 0x00000050;


    /* =================================================
       UART1 - GSM SIM900 Module

       P0.15 = TXD1
       P0.16 = RXD1
       ================================================= */

    LPC_PINCON->PINSEL0 |= (1UL << 30);   /* P0.15 -> TXD1 */
    LPC_PINCON->PINSEL1 |= (1UL << 0);    /* P0.16 -> RXD1 */


    /* =================================================
       P0.29 AS GPIO (Status / Lock LED)
       ================================================= */

    LPC_PINCON->PINSEL1 &= ~(3 << 26);

    LPC_GPIO0->FIODIR |= (1 << 29);

    /* Initial LED ON = door locked */
    LPC_GPIO0->FIOSET = (1 << 29);


    /* =================================================
       P0.30 AS GPIO INPUT (Magnetic door contact sensor)
       ================================================= */

    LPC_PINCON->PINSEL1 &= ~(3 << 28);

    LPC_GPIO0->FIODIR &= ~(1 << 30);


    /* =================================================
       LCD

       RS = P0.4
       EN = P0.5
       RW = GND

       D0 = P1.19
       D1 = P1.20
       D2 = P1.21
       D3 = P1.22
       D4 = P1.23
       D5 = P1.24
       D6 = P1.25
       D7 = P1.26
       ================================================= */

    LPC_GPIO0->FIODIR |= (1 << 4);
    LPC_GPIO0->FIODIR |= (1 << 5);

    LPC_GPIO1->FIODIR |= (0xFF << 19);


    /* LCD initialization */

    lcd_init();


    /* UART initialization */

    uart0_init();
    uart1_init();


    /* Give the GSM module time to register on the network */

    delay(3000000);


    /* Initial LCD display */

    lcd_clear();

    lcd_goto(0,0);
    lcd_string("SCAN RFID TAG");


    while(1)
    {

        /* Terminal */

        uart0_tx_string("\r\nScan RFID Tag: ");


        /* LCD */

        lcd_clear();

        lcd_goto(0,0);
        lcd_string("SCAN RFID TAG");


        /* =============================================
           RECEIVE RFID
           ============================================= */

        for(i = 0; i < 12; i++)
        {
            input_buffer[i] = uart0_rx();

            uart0_tx(input_buffer[i]);
        }

        input_buffer[12] = '\0';


        /* =============================================
           COMPARE RFID
           ============================================= */

        match_found = 0;

        if(strcmp(input_buffer, authorized_card) == 0)
        {
            match_found = 1;
        }


        /* =============================================
           CORRECT RFID
           ============================================= */

        if(match_found == 1)
        {

            /* UART */

            uart0_tx_string("\r\nDOOR OPEN");


            /* LCD */

            lcd_clear();

            lcd_goto(0,0);
            lcd_string("DOOR OPEN");

            lcd_goto(1,0);
            lcd_string("ACCESS GRANTED");


            /* P0.29 LOW = LED OFF -> door unlocked */

            LPC_GPIO0->FIOCLR = (1 << 29);


            /* SMS: authorized access */

            gsm_send_sms(PHONE_NUMBER, "Door accessed: authorized RFID tag scanned.");


            /* Door open for approximately 4 sec */

            delay(4000000);


            /* P0.29 HIGH = LED ON -> door locked */

            LPC_GPIO0->FIOSET = (1 << 29);


            /* UART */

            uart0_tx_string("\r\nDOOR CLOSED");


            /* LCD */

            lcd_clear();

            lcd_goto(0,0);
            lcd_string("DOOR CLOSED");


            delay(100000);
        }


        /* =============================================
           WRONG RFID
           ============================================= */

        else
        {

            /* UART */

            uart0_tx_string("\r\nACCESS DENIED");


            /* LCD */

            lcd_clear();

            lcd_goto(0,0);
            lcd_string("ACCESS DENIED");

            lcd_goto(1,0);
            lcd_string("INVALID TAG");


            /* P0.29 HIGH = LED ON -> stays locked */

            LPC_GPIO0->FIOSET = (1 << 29);


            /* SMS: unauthorized attempt */

            gsm_send_sms(PHONE_NUMBER, "ALERT: unauthorized RFID access attempt detected.");


            delay(100000);
        }


        /* =============================================
           INTRUSION CHECK

           If the magnetic contact sensor shows the door
           open but the last scan was NOT a valid tag,
           treat it as a forced / unauthorized door opening.
           ============================================= */

        if((match_found == 0) && (LPC_GPIO0->FIOPIN & (1 << 30)))
        {
            /* LCD */

            lcd_clear();

            lcd_goto(0,0);
            lcd_string("INTRUSION!");

            lcd_goto(1,0);
            lcd_string("DOOR FORCED");


            /* UART */

            uart0_tx_string("\r\nINTRUSION ALERT");


            /* SMS */

            gsm_send_sms(PHONE_NUMBER, "INTRUSION ALERT: door opened without authorization!");


            delay(2000000);
        }
    }
}


/* =====================================================
   UART0 INITIALIZATION (RFID Reader)
   ===================================================== */

void uart0_init(void)
{
    LPC_UART0->LCR = 0x83;

    LPC_UART0->DLM = 0x00;
    LPC_UART0->DLL = 0x75;

    LPC_UART0->FDR = 0x10;

    LPC_UART0->LCR = 0x03;
}


/* =====================================================
   UART0 RECEIVE
   ===================================================== */

char uart0_rx(void)
{
    while((LPC_UART0->LSR & 0x01) == 0);

    return LPC_UART0->RBR;
}


/* =====================================================
   UART0 TRANSMIT
   ===================================================== */

void uart0_tx(char c)
{
    while((LPC_UART0->LSR & 0x20) == 0);

    LPC_UART0->THR = c;
}


/* =====================================================
   UART0 STRING
   ===================================================== */

void uart0_tx_string(char *str)
{
    while(*str != '\0')
    {
        uart0_tx(*str);

        str++;
    }
}


/* =====================================================
   UART1 INITIALIZATION (GSM SIM900)
   ===================================================== */

void uart1_init(void)
{
    LPC_UART1->LCR = 0x83;

    LPC_UART1->DLM = 0x00;
    LPC_UART1->DLL = 0x75;

    LPC_UART1->FDR = 0x10;

    LPC_UART1->LCR = 0x03;
}


/* =====================================================
   UART1 TRANSMIT
   ===================================================== */

void uart1_tx(char c)
{
    while((LPC_UART1->LSR & 0x20) == 0);

    LPC_UART1->THR = c;
}


/* =====================================================
   UART1 STRING
   ===================================================== */

void uart1_tx_string(char *str)
{
    while(*str != '\0')
    {
        uart1_tx(*str);

        str++;
    }
}


/* =====================================================
   GSM SEND SMS (AT command sequence, text mode)
   ===================================================== */

void gsm_send_sms(char *number, char *message)
{
    /* Set SMS text mode */

    uart1_tx_string("AT+CMGF=1\r\n");

    delay(500000);


    /* Recipient number */

    uart1_tx_string("AT+CMGS=\"");
    uart1_tx_string(number);
    uart1_tx_string("\"\r\n");

    delay(500000);


    /* Message body */

    uart1_tx_string(message);


    /* Ctrl+Z (0x1A) sends the message */

    uart1_tx(0x1A);

    delay(1000000);
}


/* =====================================================
   LCD COMMAND
   ===================================================== */

void lcd_cmd(unsigned char cmd)
{
    /* RS = 0 */

    LPC_GPIO0->FIOCLR = (1 << 4);


    /* Put command on P1.19-P1.26 */

    LPC_GPIO1->FIOCLR = (0xFF << 19);

    LPC_GPIO1->FIOSET = ((unsigned long)cmd << 19);


    /* EN = 1 */

    LPC_GPIO0->FIOSET = (1 << 5);

    delay(1000);


    /* EN = 0 */

    LPC_GPIO0->FIOCLR = (1 << 5);

    delay(2000);
}


/* =====================================================
   LCD DATA
   ===================================================== */

void lcd_data(unsigned char data)
{
    /* RS = 1 */

    LPC_GPIO0->FIOSET = (1 << 4);


    /* Put data on P1.19-P1.26 */

    LPC_GPIO1->FIOCLR = (0xFF << 19);

    LPC_GPIO1->FIOSET = ((unsigned long)data << 19);


    /* EN = 1 */

    LPC_GPIO0->FIOSET = (1 << 5);

    delay(1000);


    /* EN = 0 */

    LPC_GPIO0->FIOCLR = (1 << 5);

    delay(2000);
}


/* =====================================================
   LCD STRING
   ===================================================== */

void lcd_string(char *str)
{
    while(*str != '\0')
    {
        lcd_data(*str);

        str++;
    }
}


/* =====================================================
   LCD CLEAR
   ===================================================== */

void lcd_clear(void)
{
    lcd_cmd(0x01);

    delay(5000);
}


/* =====================================================
   LCD GOTO
   ===================================================== */

void lcd_goto(unsigned char row, unsigned char column)
{
    if(row == 0)
    {
        lcd_cmd(0x80 + column);
    }
    else
    {
        lcd_cmd(0xC0 + column);
    }
}


/* =====================================================
   LCD INITIALIZATION
   ===================================================== */

void lcd_init(void)
{
    /* RS */

    LPC_GPIO0->FIODIR |= (1 << 4);


    /* EN */

    LPC_GPIO0->FIODIR |= (1 << 5);


    /* D0-D7 */

    LPC_GPIO1->FIODIR |= (0xFF << 19);


    /* Initial states */

    LPC_GPIO0->FIOCLR = (1 << 4);
    LPC_GPIO0->FIOCLR = (1 << 5);

    LPC_GPIO1->FIOCLR = (0xFF << 19);


    delay(20000);


    /* 8-bit, 2-line, 5x8 font */

    lcd_cmd(0x38);


    /* Display ON, cursor OFF */

    lcd_cmd(0x0C);


    /* Entry mode */

    lcd_cmd(0x06);


    /* Clear */

    lcd_cmd(0x01);

    delay(5000);
}


/* =====================================================
   DELAY
   ===================================================== */

void delay(unsigned long int x)
{
    unsigned long int j;

    for(j = 0; j < x; j++)
    {
    }
}