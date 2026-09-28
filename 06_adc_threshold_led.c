#include <LPC17xx.H>
unsigned short int adc=0;
int main()
{
SystemInit();
//---------------P0.29 (LED)--------------------
LPC_GPIO1->FIOMASK3=0XDF; //p0.29
LPC_GPIO1->FIODIR3=0X20; // p0.29
//----------------ADC---------------------------
LPC_SC->PCONP|=0X00001000; 
LPC_PINCON->PINSEL3|=0XC0000000; //p1.31 as ad05
LPC_ADC->ADCR=0X00210320; 

while(1) 		
{                         
while((LPC_ADC->ADSTAT&0X00000020)!=0X00000020)
	{
	}
adc=((LPC_ADC->ADDR5>>4)& 0x00000fff); // shift it and take least 12 bits
if (adc > 0x9B2) // Comparing MV with RV
	{
		LPC_GPIO1->FIOSET3=0X20; // p0.22 
	}
else  
	{
		LPC_GPIO1->FIOCLR3=0X20; // p0.22
	}
}			
}