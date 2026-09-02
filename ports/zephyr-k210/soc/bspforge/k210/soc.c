#include <stdint.h>
#include <zephyr/init.h>

#define K210_SYSCTL_BASE 0x50440000UL
#define K210_SYSCTL_CLK_EN_CENT_OFFSET 0x28UL
#define K210_SYSCTL_CLK_EN_PERI_OFFSET 0x2cUL
#define K210_SYSCTL_APB0_CLK_EN (1UL << 3)
#define K210_SYSCTL_FPIOA_CLK_EN (1UL << 20)
#define K210_FPIOA_BASE 0x502B0000UL
#define K210_UARTHS_RX_PIN 4U
#define K210_UARTHS_TX_PIN 5U

/* K210 SDK defaults: function 18 is UARTHS_RX and function 19 is UARTHS_TX. */
static int k210_board_early_init(void)
{
    volatile uint32_t *clk_en_cent =
        (volatile uint32_t *)(K210_SYSCTL_BASE + K210_SYSCTL_CLK_EN_CENT_OFFSET);
    volatile uint32_t *clk_en_peri =
        (volatile uint32_t *)(K210_SYSCTL_BASE + K210_SYSCTL_CLK_EN_PERI_OFFSET);
    volatile uint32_t *fpioa = (volatile uint32_t *)K210_FPIOA_BASE;

    *clk_en_cent |= K210_SYSCTL_APB0_CLK_EN;
    *clk_en_peri |= K210_SYSCTL_FPIOA_CLK_EN;
    fpioa[K210_UARTHS_RX_PIN] = 0x00900012U;
    fpioa[K210_UARTHS_TX_PIN] = 0x00001F13U;
    return 0;
}

SYS_INIT(k210_board_early_init, PRE_KERNEL_1, 5);
