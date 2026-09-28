#include<LPC17xx.h>
void delay(unsigned long int x);
void lcdWrite(unsigned char ch);
int main()
{
	unsigned char val;
	unsigned long int i;
	unsigned char cmd[] ={0X33,0x32,0x28,0x0E,0x06,0x01,0X80};
	unsigned char msg1[]= "HIGH (0_0) ";
	unsigned char msg2[]= "LOW (x_x)";
	SystemInit();
	LPC_GPIO1->FIOMASK3=0XDF;//p1.29
	LPC_GPIO0->FIODIR0=0X00;//dir of p0.0
	LPC_GPIO1->FIODIR3=0X20 ;//dir of p1.29
	
	LPC_GPIO0->FIOMASK=0xE1FFFFFE;// 25-28,p0.0
	LPC_GPIO0->FIODIR=0x1E000000;// 25-28,p0.0
	LPC_GPIO2->FIOMASK1=0xC7;//11,12,13
	LPC_GPIO2->FIODIR1=0x38;// rs,rw,EN
	LPC_GPIO2->FIOCLR1=0x18;// rs,rw=0
	for(i=0;i<5;i++)
	{
	lcdWrite(cmd[i]);
	}
	while(1)
	{  
		val=LPC_GPIO0->FIOPIN0;
		
		if(val==0X01)
		{
			LPC_GPIO1->FIOSET3=0X20 ;
			LPC_GPIO2->FIOSET1=0x08;//rs=1
			for(i=0;msg1[i]!='\0';i++)
			{
			   lcdWrite(msg1[i]);
			}
		}
		else
		{
			LPC_GPIO1->FIOCLR3=0X20 ;
			LPC_GPIO2->FIOSET1=0x08;//rs=1
			for(i=0;msg2[i]!='\0';i++)
			{
			  lcdWrite(msg2[i]);
				
			}
		}
		LPC_GPIO2->FIOCLR1=0x08;// rs=0
		lcdWrite(0X80);
		delay(50000);
		lcdWrite(0X01);
	}

}
void delay(unsigned	long int x)
{
	unsigned long int k=0;
	for(k=0;k<x;k++);
}

void lcdWrite(unsigned char ch)
{
    // HIGH nibble
    LPC_GPIO0->FIOPIN = (ch & 0xF0) << 21;  
    LPC_GPIO2->FIOSET1 = 0x20;  // EN = 1
    delay(500000);
    LPC_GPIO2->FIOCLR1 = 0x20;  // EN = 0

    // LOW nibble
    LPC_GPIO0->FIOPIN = (ch & 0x0F) << 25;  
    LPC_GPIO2->FIOSET1 = 0x20;
    delay(500000);
    LPC_GPIO2->FIOCLR1 = 0x20;

    delay(500000);
}
