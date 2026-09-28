#include <LPC17xx.H>

void delay(unsigned long int x);

int main()
{
    SystemInit();
    LPC_SC->PCONP |= 0x00000000;
    
    LPC_GPIO0->FIOMASK = ~(0x01E00000);  
    LPC_GPIO0->FIODIR  =  (0x01E00000);   

    while(1)
    {
        LPC_GPIO0->FIOSET = (0x01E00000);  
        delay(5000000);
        LPC_GPIO0->FIOCLR = (0x01E00000);  
        delay(5000000);
    }
}

void delay(unsigned long int x)
{
    unsigned long int i;
    for(i = 0; i < x; i++);
}