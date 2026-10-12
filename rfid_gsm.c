/* =========================================================================
   RFID-Based Door Access Control with GSM SMS Alerts
   Target: LPC1768 (ARM Cortex-M3)

   - UART0  -> RFID reader   (P0.2 = TXD0, P0.3 = RXD0)
   - UART1  -> SIM900 GSM    (P0.15 = TXD1, P0.16 = RXD1)
   - LCD    -> RS = P0.4, EN = P0.5, D0-D7 = P1.19-P1.26 (RW tied to GND)
   - P0.29  -> Status/Lock LED (LOW = unlocked, HIGH = locked)
   - P0.30  -> Magnetic door contact sensor, wired as EINT3 (interrupt input)

   Behaviour:
   1. Waits for an RFID tag scan on UART0 (non-blocking, with timeout).
   2. Matching tag  -> unlocks door, LCD "ACCESS GRANTED", SMS to owner.
   3. Wrong tag     -> stays locked, LCD "ACCESS DENIED", SMS alert.
   4. The door-contact sensor on P0.30 is wired to EINT3 and fires an
      interrupt the instant the door is opened. The ISR checks a flag
      that is only set true for a short window right after a valid
      RFID unlock; if the door opens outside that window, it is a
      forced/intrusion event and an SMS alert is queued -- independent
      of whatever the main loop is doing (including while it is
      sitting in the blocking RFID read).

   Set PHONE_NUMBER below to the number that should receive alerts.
   ========================================================================= */

#include <LPC17xx.h>
#include <string.h>

/* ---------------- UART0 (RFID Reader) ---------------- */
void uart0_init(void);
int  uart0_rx_timeout(char *out, unsigned long timeout_loops);
void uart0_tx(char c);
void uart0_tx_string(char *str);

/* ---------------- UART1 (GSM SIM900) ---------------- */
void uart1_init(void);
void uart1_tx(char c);
void uart1_tx_string(char *str);
int  uart1_wait_response(char *expect, unsigned long timeout_loops);
int  gsm_send_sms(char *number, char *message);

/* ---------------- LCD ---------------- */
void lcd_init(void);
void lcd_cmd(unsigned char cmd);
void lcd_data(unsigned char data);
void lcd_string(char *str);
void lcd_clear(void);
void lcd_goto(unsigned char row, unsigned char column);

/* ---------------- Door sensor / intrusion ---------------- */
void eint3_setup(void);
void EINT3_IRQHandler(void);

/* ---------------- Delay (timer-backed, NOT optimized away) ---------------- */
void delay_ms(unsigned int ms);

/* ---------------- Configuration ---------------- */
#define PHONE_NUMBER "+91XXXXXXXXXX"   /* <-- set the alert recipient's number */

/* Set true while a valid unlock is in progress, so the door-open
   interrupt that naturally follows a granted access is not flagged
   as an intrusion. Declared volatile because it is written in the
   ISR and read in main(). */
volatile unsigned char access_window_open = 0;

/* Set by the ISR, cleared by main() after it has handled the event.
   volatile for the same reason as above. */
volatile unsigned char intrusion_flag = 0;


int main(void)
{
    char authorized_card[13] = "09008206BE33";
    char input_buffer[13];
    int  match_found;
    int  got_tag;

    SystemInit();

    /* =================================================
       Peripheral clocks: run UART0 and UART1 at CCLK/4
       (PCLK = 25 MHz on a 100 MHz SystemInit) so the
       DLL/FDR values below give a correct 9600 baud.
       PCLKSEL0 bits [7:6] = UART1, [5:4] = UART0.
       00 = CCLK/4 (the reset default, set explicitly
       here so the baud rate math is never ambiguous).
       ================================================= */
    LPC_SC->PCLKSEL0 &= ~((3UL << 4) | (3UL << 6));

    /* =================================================
       UART0 - RFID Reader : P0.2 = TXD0, P0.3 = RXD0
       ================================================= */
    LPC_PINCON->PINSEL0 |= 0x00000050;

    /* =================================================
       UART1 - GSM SIM900 : P0.15 = TXD1, P0.16 = RXD1
       ================================================= */
    LPC_PINCON->PINSEL0 |= (1UL << 30);   /* P0.15 -> TXD1 */
    LPC_PINCON->PINSEL1 |= (1UL << 0);    /* P0.16 -> RXD1 */

    /* =================================================
       P0.29 AS GPIO (Status / Lock LED)
       ================================================= */
    LPC_PINCON->PINSEL1 &= ~(3 << 26);
    LPC_GPIO0->FIODIR   |= (1 << 29);
    LPC_GPIO0->FIOSET    = (1 << 29);     /* locked on boot */

    /* LCD pins */
    LPC_GPIO0->FIODIR |= (1 << 4);
    LPC_GPIO0->FIODIR |= (1 << 5);
    LPC_GPIO1->FIODIR |= (0xFF << 19);

    lcd_init();
    uart0_init();
    uart1_init();
    eint3_setup();                        /* door sensor -> interrupt, not polling */

    /* Give the GSM module time to register on the network.
       3 s is a minimum; real registration can take 10-30 s,
       so the first SMS attempt after boot may need a retry
       in practice -- see note in gsm_send_sms(). */
    delay_ms(3000);

    lcd_clear();
    lcd_goto(0, 0);
    lcd_string("SCAN RFID TAG");

    while (1)
    {
        uart0_tx_string("\r\nScan RFID Tag: ");

        lcd_clear();
        lcd_goto(0, 0);
        lcd_string("SCAN RFID TAG");

        /* =============================================
           RECEIVE RFID (bounded wait, not an infinite
           block -- if nothing arrives within the timeout
           the loop just re-prompts instead of hanging
           the whole system forever)
           ============================================= */
        got_tag = uart0_rx_timeout(input_buffer, 5000000UL);

        if (!got_tag)
        {
            continue;   /* no tag presented in this window, try again */
        }

        input_buffer[12] = '\0';
        uart0_tx_string(input_buffer);

        match_found = (strcmp(input_buffer, authorized_card) == 0) ? 1 : 0;

        if (match_found)
        {
            uart0_tx_string("\r\nDOOR OPEN");

            lcd_clear();
            lcd_goto(0, 0);
            lcd_string("DOOR OPEN");
            lcd_goto(1, 0);
            lcd_string("ACCESS GRANTED");

            /* Tell the ISR a legitimate door-open is expected now,
               so it does not get flagged as an intrusion. */
            access_window_open = 1;

            LPC_GPIO0->FIOCLR = (1 << 29);   /* unlock */

            gsm_send_sms(PHONE_NUMBER, "Door accessed: authorized RFID tag scanned.");

            delay_ms(4000);                  /* door stays unlocked */

            access_window_open = 0;          /* back to "any opening = intrusion" */

            LPC_GPIO0->FIOSET = (1 << 29);   /* re-lock */

            uart0_tx_string("\r\nDOOR CLOSED");

            lcd_clear();
            lcd_goto(0, 0);
            lcd_string("DOOR CLOSED");

            delay_ms(100);
        }
        else
        {
            uart0_tx_string("\r\nACCESS DENIED");

            lcd_clear();
            lcd_goto(0, 0);
            lcd_string("ACCESS DENIED");
            lcd_goto(1, 0);
            lcd_string("INVALID TAG");

            LPC_GPIO0->FIOSET = (1 << 29);   /* stays locked */

            gsm_send_sms(PHONE_NUMBER, "ALERT: unauthorized RFID access attempt detected.");

            delay_ms(100);
        }

        /* =============================================
           INTRUSION EVENT -- this is set asynchronously
           by EINT3_IRQHandler() the instant the door
           sensor trips outside a valid access window, so
           it is caught even if it happens while this loop
           is elsewhere (e.g. waiting on the next RFID
           scan). The flag is just picked up and acted on
           here so SMS sending stays out of the ISR.
           ============================================= */
        if (intrusion_flag)
        {
            intrusion_flag = 0;

            lcd_clear();
            lcd_goto(0, 0);
            lcd_string("INTRUSION!");
            lcd_goto(1, 0);
            lcd_string("DOOR FORCED");

            uart0_tx_string("\r\nINTRUSION ALERT");

            gsm_send_sms(PHONE_NUMBER, "INTRUSION ALERT: door opened without authorization!");

            delay_ms(2000);
        }
    }
}


/* =====================================================
   DOOR SENSOR -> EINT3 (P0.30) INTERRUPT

   P0.30 is muxed to EINT3 so a door-open edge is caught
   immediately by hardware, independent of what the main
   loop is doing. The ISR only sets a flag -- it does NOT
   call gsm_send_sms() directly, since the AT-command
   sequence takes many milliseconds and has no business
   running inside an ISR.
   ===================================================== */

void eint3_setup(void)
{
    /* P0.30 -> EINT3 (function select = 10 per PINSEL1[29:28]) */
    LPC_PINCON->PINSEL1 &= ~(3UL << 28);
    LPC_PINCON->PINSEL1 |=  (2UL << 28);

    /* Falling edge = contact breaks = door opens.
       Adjust to EXTPOLAR if your reed switch is wired the other way. */
    LPC_SC->EXTMODE  |= (1 << 3);   /* edge-sensitive  */
    LPC_SC->EXTPOLAR &= ~(1 << 3);  /* falling edge    */

    LPC_SC->EXTINT = (1 << 3);      /* clear any pending flag */

    NVIC_EnableIRQ(EINT3_IRQn);
}

void EINT3_IRQHandler(void)
{
    if (!access_window_open)
    {
        intrusion_flag = 1;
    }

    LPC_SC->EXTINT = (1 << 3);      /* clear interrupt flag */
}


/* =====================================================
   UART0 INITIALIZATION (RFID Reader) -- 9600 8N1 at
   PCLK = 25 MHz (see PCLKSEL0 setup in main())
   ===================================================== */

void uart0_init(void)
{
    LPC_UART0->LCR = 0x83;   /* 8N1, DLAB = 1 */
    LPC_UART0->DLM = 0x00;
    LPC_UART0->DLL = 0xA3;   /* 25,000,000 / (16 * 9600) ~= 163 (0xA3) */
    LPC_UART0->FDR = 0x10;   /* DIVADDVAL=0, MULVAL=1 -> no fractional scaling */
    LPC_UART0->LCR = 0x03;   /* DLAB = 0 */
}

/* Reads up to 12 bytes into out[0..11]. Returns 1 if 12 bytes were
   received before the timeout, 0 otherwise. Unlike a bare blocking
   read, this can never hang the system forever on a disconnected
   or silent RFID reader. */
int uart0_rx_timeout(char *out, unsigned long timeout_loops)
{
    int i = 0;
    unsigned long waited;

    while (i < 12)
    {
        waited = 0;
        while ((LPC_UART0->LSR & 0x01) == 0)
        {
            waited++;
            if (waited > timeout_loops)
            {
                return 0;
            }
        }
        out[i] = (char)LPC_UART0->RBR;
        uart0_tx(out[i]);
        i++;
    }
    return 1;
}

void uart0_tx(char c)
{
    while ((LPC_UART0->LSR & 0x20) == 0);
    LPC_UART0->THR = c;
}

void uart0_tx_string(char *str)
{
    while (*str != '\0')
    {
        uart0_tx(*str);
        str++;
    }
}


/* =====================================================
   UART1 INITIALIZATION (GSM SIM900) -- 9600 8N1
   ===================================================== */

void uart1_init(void)
{
    LPC_UART1->LCR = 0x83;
    LPC_UART1->DLM = 0x00;
    LPC_UART1->DLL = 0xA3;
    LPC_UART1->FDR = 0x10;
    LPC_UART1->LCR = 0x03;
}

void uart1_tx(char c)
{
    while ((LPC_UART1->LSR & 0x20) == 0);
    LPC_UART1->THR = c;
}

void uart1_tx_string(char *str)
{
    while (*str != '\0')
    {
        uart1_tx(*str);
        str++;
    }
}

/* Polls UART1 RBR for up to timeout_loops iterations, looking for
   the given substring (e.g. "OK") anywhere in what it receives.
   Returns 1 if found, 0 on timeout. This is what lets the code
   actually know an AT command succeeded instead of assuming it did. */
int uart1_wait_response(char *expect, unsigned long timeout_loops)
{
    char rx_buf[64];
    unsigned int idx = 0;
    unsigned long waited = 0;
    unsigned int explen = 0;
    unsigned int k;
    char *p = expect;

    while (*p) { explen++; p++; }

    while (waited < timeout_loops)
    {
        if (LPC_UART1->LSR & 0x01)
        {
            char c = (char)LPC_UART1->RBR;
            if (idx < sizeof(rx_buf) - 1)
            {
                rx_buf[idx++] = c;
                rx_buf[idx] = '\0';
            }
            if (idx >= explen)
            {
                /* crude substring search, fine for short AT replies */
                for (k = 0; k + explen <= idx; k++)
                {
                    if (strncmp(&rx_buf[k], expect, explen) == 0)
                    {
                        return 1;
                    }
                }
            }
        }
        waited++;
    }
    return 0;
}

/* Returns 1 if the module acknowledged the message prompt and the
   send was issued, 0 if AT+CMGF or AT+CMGS never got a response
   (module not ready / not registered / wiring issue). */
int gsm_send_sms(char *number, char *message)
{
    uart1_tx_string("AT+CMGF=1\r\n");
    if (!uart1_wait_response("OK", 2000000UL))
    {
        return 0;
    }

    uart1_tx_string("AT+CMGS=\"");
    uart1_tx_string(number);
    uart1_tx_string("\"\r\n");
    if (!uart1_wait_response(">", 2000000UL))   /* module prompts '>' for the body */
    {
        return 0;
    }

    uart1_tx_string(message);
    uart1_tx(0x1A);   /* Ctrl+Z sends it */

    uart1_wait_response("OK", 5000000UL);   /* best-effort; SMS send can take a few sec */
    return 1;
}


/* =====================================================
   LCD DRIVER
   ===================================================== */

void lcd_cmd(unsigned char cmd)
{
    LPC_GPIO0->FIOCLR = (1 << 4);
    LPC_GPIO1->FIOCLR = (0xFF << 19);
    LPC_GPIO1->FIOSET = ((unsigned long)cmd << 19);
    LPC_GPIO0->FIOSET = (1 << 5);
    delay_ms(1);
    LPC_GPIO0->FIOCLR = (1 << 5);
    delay_ms(1);
}

void lcd_data(unsigned char data)
{
    LPC_GPIO0->FIOSET = (1 << 4);
    LPC_GPIO1->FIOCLR = (0xFF << 19);
    LPC_GPIO1->FIOSET = ((unsigned long)data << 19);
    LPC_GPIO0->FIOSET = (1 << 5);
    delay_ms(1);
    LPC_GPIO0->FIOCLR = (1 << 5);
    delay_ms(1);
}

void lcd_string(char *str)
{
    while (*str != '\0')
    {
        lcd_data(*str);
        str++;
    }
}

void lcd_clear(void)
{
    lcd_cmd(0x01);
    delay_ms(2);
}

void lcd_goto(unsigned char row, unsigned char column)
{
    if (row == 0) lcd_cmd(0x80 + column);
    else          lcd_cmd(0xC0 + column);
}

void lcd_init(void)
{
    LPC_GPIO0->FIODIR |= (1 << 4);
    LPC_GPIO0->FIODIR |= (1 << 5);
    LPC_GPIO1->FIODIR |= (0xFF << 19);

    LPC_GPIO0->FIOCLR = (1 << 4);
    LPC_GPIO0->FIOCLR = (1 << 5);
    LPC_GPIO1->FIOCLR = (0xFF << 19);

    delay_ms(20);

    lcd_cmd(0x38);   /* 8-bit, 2-line, 5x8 font */
    lcd_cmd(0x0C);   /* display ON, cursor OFF  */
    lcd_cmd(0x06);   /* entry mode              */
    lcd_cmd(0x01);   /* clear                   */
    delay_ms(2);
}


/* =====================================================
   DELAY -- SysTick-backed millisecond delay.

   The original project's delay() was an empty for-loop,
   which compilers are free to optimize away entirely
   since the loop variable is never observed. SysTick is
   a real hardware timer, so this cannot be optimized out
   and gives an actual, predictable millisecond delay
   regardless of compiler optimization level.
   ===================================================== */

void delay_ms(unsigned int ms)
{
    /* SystemInit() sets SystemCoreClock; SysTick reload is clock
       ticks per millisecond, so this works at any core clock. */
    SysTick->LOAD = (SystemCoreClock / 1000) - 1;
    SysTick->VAL  = 0;
    SysTick->CTRL = (1 << 0) | (1 << 2);   /* enable, use CPU clock */

    for (unsigned int i = 0; i < ms; i++)
    {
        while ((SysTick->CTRL & (1 << 16)) == 0);  /* wait for COUNTFLAG */
    }

    SysTick->CTRL = 0;   /* stop timer */
}
