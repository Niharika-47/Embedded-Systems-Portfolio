# LPC17xx Embedded C Programs

Register-level C programs for the NXP LPC17xx (ARM Cortex-M3) using the `LPC17xx.h` header (Keil µVision style). No libraries are used; GPIO, ADC and UART are configured directly through registers.

## Programs and pin usage

| File | Concept | Pins used |
|---|---|---|
| `01_led_blink_single.c` | GPIO output, masked FIOSET/FIOCLR, software delay | LED on P1.29 |
| `02_led_blink_4bit.c` | Driving a 4-pin group with FIOMASK/FIODIR | LEDs on P0.21–P0.24 |
| `03_4bit_up_counter.c` | 4-bit binary up counter (0–15) | LEDs on P0.21–P0.24 |
| `04_lcd_4bit_switch_led.c` | LCD in 4-bit mode, switch input, LED output | Data P0.25–P0.28, RS/RW/EN on P2.11–P2.13, switch P0.0, LED P1.29 |
| `05_lcd_4bit_switch_display.c` | LCD 4-bit init, cursor control for two lines, switch-driven display | Data P0.21–P0.24, RS/RW/EN on P2.11–P2.13, switch P0.0 |
| `06_adc_threshold_led.c` | 12-bit ADC read (channel 5, P1.31) and threshold compare | ADC on P1.31, LED on P1.29 |
| `07_gsm_sms_sender.c` | UART0 init, GSM AT commands (`AT`, `AT+CREG?`, `AT+CMGF=1`, `AT+CMGS`) | TXD0/RXD0 on P0.2/P0.3, switch on P0.21, LED on P1.29 |

## Notes

- The phone number in `07_gsm_sms_sender.c` has been replaced with a placeholder (`+91XXXXXXXXXX`).
- Build with Keil µVision for the LPC17xx and flash to an LPC17xx development board.
