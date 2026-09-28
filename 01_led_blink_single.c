#include <LPC17xx.H>
void delay(unsigned long int x);
int main()
{ 	
	SystemInit();
	
	
	LPC_GPIO1->FIOMASK3 = 0xDF;   //  31 20 29 28 27 26 25 24   P1.29- 11011111 -DF       //  FIOMASK gpio pin func : 0 - enable & 1- disable 
	LPC_GPIO1->FIODIR3= 0x20;     //  0  0  1  0  0  0  0  0    TO SET LED AS O/P = 1 high   
	
	while(1)
	{
		LPC_GPIO1->FIOSET3 =0x20;                        // u will use FIOPIN register only when u want to directly set the LED as High and LoW 
		delay(5000000);                                                          
		LPC_GPIO1->FIOCLR3 =0x20;
		delay(5000000);
		}
}

void delay(unsigned long int x)
{
	unsigned long int i;
	
	for(i=0;i<x;i++);
}
