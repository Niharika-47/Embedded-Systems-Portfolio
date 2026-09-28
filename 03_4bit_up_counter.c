#include <LPC17xx.H>

void delay(unsigned long int x);

int main()
{
    unsigned int i;

    SystemInit();
	  LPC_SC-> PCONP |= 0X00000000;
    LPC_GPIO0->FIOMASK = ~(0x01E00000);
    LPC_GPIO0->FIODIR = 0x01E00000;

    for(i = 0; i < 16; i++)
    {
        LPC_GPIO0->FIOCLR = 0x01E00000;
        LPC_GPIO0->FIOSET = (i<<21);
        delay(5000000);
    }
}

void delay(unsigned long int x)
{
    unsigned long int i;
    for(i = 0; i < x; i++);
}
