#include <stdio.h>

void SystemInit(void)
{
}

int main()
{
    unsigned int value = 25;
    int n = 3;

    if((value & (1 << n)) != 0)
    {
        printf("Bit is set\n");

        value = value & ~(1 << n);

        printf("After reset = %u", value);
    }
    else
    {
        printf("Bit is not set\n");

        value = value ^ 1;

        printf("After toggle first bit = %u", value);
    }

    return 0;
}
