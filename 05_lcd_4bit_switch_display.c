#include <LPC17xx.h>

void delay(long int x)
{
    int i;
    for(i=0;i<x;i++);
}

void lcd_4(unsigned char chr)
{
    unsigned char chr1, chr2;

    // Upper nibble
    chr1 = chr & 0xF0;
    LPC_GPIO0->FIOPINH = chr1 << 1;

    LPC_GPIO2->FIOSET1 = 0x20;   // EN=1
    delay(500);
    LPC_GPIO2->FIOCLR1 = 0x20;   // EN=0
    delay(50000);

    // Lower nibble
    chr2 = chr & 0x0F;
    LPC_GPIO0->FIOPINH = chr2 << 5;

    LPC_GPIO2->FIOSET1 = 0x20;   // EN=1
    delay(500);
    LPC_GPIO2->FIOCLR1 = 0x20;   // EN=0
    delay(50000);
}

int main()
{
    int i;
    unsigned char cmd[]  = {0x02,0x28,0x0E,0x06,0x01,0x80};
    unsigned char str1[] = "4 BIT LCD";
    unsigned char str2[] = "SWITCH MODE";
    unsigned char var;

    SystemInit();
    delay(500000);

    // LCD control pins P2.11, P2.12, P2.13
    LPC_GPIO2->FIOMASK1 = 0xC7;
    LPC_GPIO2->FIODIR1  = 0x38;

    // LCD data pins P0.21-P0.24
    LPC_GPIO0->FIOMASKH = 0xFE1F;
    LPC_GPIO0->FIODIRH  = 0x01E0;

    // Switch P0.0
    LPC_GPIO0->FIOMASK0 = 0xFE;
    LPC_GPIO0->FIODIR0  = 0x00;

    // LCD Initialization
    LPC_GPIO2->FIOCLR1 = 0x08;   // RS=0
    LPC_GPIO2->FIOCLR1 = 0x10;   // RW=0

    for(i=0;i<6;i++)
        lcd_4(cmd[i]);

    while(1)
    {
        var = LPC_GPIO0->FIOPIN0 & 0x01;

        if(var == 1)
        {
            // Clear LCD
            LPC_GPIO2->FIOCLR1 = 0x08;
            lcd_4(0x01);

            // First line
            LPC_GPIO2->FIOCLR1 = 0x08;
            lcd_4(0x80);

            LPC_GPIO2->FIOSET1 = 0x08;
            for(i=0; str1[i] != '\0'; i++)
                lcd_4(str1[i]);

            // Second line
            LPC_GPIO2->FIOCLR1 = 0x08;
            lcd_4(0xC0);

            LPC_GPIO2->FIOSET1 = 0x08;
            for(i=0; str2[i] != '\0'; i++)
                lcd_4(str2[i]);
        }
        else
        {
            LPC_GPIO2->FIOCLR1 = 0x08;
            lcd_4(0x01);     // Clear display
        }

        delay(100000);
    }
}
