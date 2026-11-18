#include "target.h"
.section .text.start,"ax"
.globl __start
__start:
    .option push
    .option norelax
    la gp, __global_pointer$
    .option pop
    la sp, __rt_rvstack
    la t0, _sidata
    la t1, _sdata
    la t2, _edata
4:  bgeu t1, t2, 5f
    lw t3, 0(t0)
    sw t3, 0(t1)
    addi t0, t0, 4
    addi t1, t1, 4
    j 4b
5:
    la t0, _sbss
    la t1, _ebss
1:  bgeu t0, t1, 2f
    sw zero, 0(t0)
    addi t0, t0, 4
    j 1b
2:
#if TARGET_OPENTITAN
    la t0, bsp_trap_vectors
    ori t0, t0, 1
#else
    la t0, SW_handler
#endif
    csrw mtvec, t0
    csrw mscratch, sp
    call simulation_start
3:  j 3b
#if TARGET_OPENTITAN
.balign 256
bsp_trap_vectors:
.option push
.option norvc
.rept 32
    j SW_handler
.endr
.option pop
#endif
.section .bss.stack,"aw",@nobits
.balign 16
.space 2048
.globl __rt_rvstack
__rt_rvstack:
