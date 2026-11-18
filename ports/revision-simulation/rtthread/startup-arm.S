.syntax unified
.thumb
.section .isr_vector,"a"
.global vectors
vectors:
    .word _estack
    .word Reset_Handler
    .word Default_Handler
    .word HardFault_Handler
    .rept 10
    .word Default_Handler
    .endr
    .word PendSV_Handler
    .word SysTick_Handler
    .rept 128
    .word Default_Handler
    .endr
.text
.thumb_func
.global Reset_Handler
Reset_Handler:
    ldr r0, =_sidata
    ldr r1, =_sdata
    ldr r2, =_edata
1:  cmp r1, r2
    bcs 2f
    ldr r3, [r0]
    str r3, [r1]
    adds r0, #4
    adds r1, #4
    b 1b
2:  ldr r1, =_sbss
    ldr r2, =_ebss
    movs r3, #0
3:  cmp r1, r2
    bcs 4f
    str r3, [r1]
    adds r1, #4
    b 3b
4:  bl simulation_start
5:  b 5b
.thumb_func
Default_Handler:
    b Default_Handler
