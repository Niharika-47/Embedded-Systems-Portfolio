#include <LPC17xx.h>

void delay(unsigned long int x);
void uart0_init(void);
void GSM_init(void);
void send_sms(void);

unsigned char a[] = "AT\r\n";
unsigned char b[] = "AT+CREG?\r\n";
unsigned char c[] = "AT+CMGF=1\r\n";

unsigned char i;
unsigned int  val;

int main()
{
    SystemInit();
		LPC_GPIO0->FIOMASK2=0XDF;// p0.21 is enabled
		
	  LPC_GPIO0->FIODIR2=0XDF; // P0.21
    // ---------- UART ----------
    LPC_PINCON->PINSEL0 |= 0x00000050; // P0.2=TXD0, P0.3=RXD0

    // ---------- P1.29 OUTPUT ----------
    LPC_GPIO1->FIOMASK3 = 0xDF;       
    LPC_GPIO1->FIODIR3  = 0x20;        
    LPC_GPIO1->FIOCLR3  = 0x20;        

    
    uart0_init();                       
    GSM_init();                        

    while(1)
    {
			 
        val = (LPC_GPIO0->FIOPIN >> 21) & 0x01;  
				

        if(val == 0x01)                    
        {
            LPC_GPIO1->FIOSET3 = 0x20; 
						send_sms(); 
                                
        }
        else
        {
            LPC_GPIO1->FIOCLR3 = 0x20;      
        }
    }
}

void GSM_init(void)
{
    // Send AT
    for(i = 0; a[i] != '\0'; i++)
    {
        while((LPC_UART0->LSR & 0x20) != 0x20); 
        LPC_UART0->THR = a[i];
    }
    delay(50000);                           

    // Send AT+CREG?
    for(i = 0; b[i] != '\0'; i++)
    {
        while((LPC_UART0->LSR & 0x20) != 0x20);
        LPC_UART0->THR = b[i];
    }
    delay(50000);

    // Send AT+CMGF=1
    for(i = 0; c[i] != '\0'; i++)
    {
        while((LPC_UART0->LSR & 0x20) != 0x20);
        LPC_UART0->THR = c[i];
    }
    delay(50000);
}

void send_sms(void)
{   unsigned char e[] = "Hello Sumana";
    unsigned char cmd[] = "AT+CMGS=\"+91XXXXXXXXXX\"\r\n";

    // Send AT+CMGS="
    for(i = 0; cmd[i] != '\0'; i++)
    {
        while((LPC_UART0->LSR & 0x20) != 0x20);
        LPC_UART0->THR = cmd[i];
        
    }

    delay(10000000);                           

    // Send message body
    for(i = 0; e[i] != '\0'; i++)
    {
        while((LPC_UART0->LSR & 0x20) != 0x20);
        LPC_UART0->THR = e[i];
    }

    // Send CTRL+Z
		LPC_UART0->THR = 0x1A;
    while((LPC_UART0->LSR & 0x20) != 0x20);
    
    delay(10000);                            
	}
void uart0_init(void)
{
    LPC_UART0->LCR = 0x83;
    LPC_UART0->DLM = 0x00;
    LPC_UART0->DLL = 0x75;
    LPC_UART0->FDR = 0x00000010;
    LPC_UART0->LCR = 0x03;
}

void delay(unsigned long int x)
{
    unsigned long int j;
    for(j = 0; j < x; j++);
}