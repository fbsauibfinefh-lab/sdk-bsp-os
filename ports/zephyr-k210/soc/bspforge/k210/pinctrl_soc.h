#ifndef BSPFORGE_K210_PINCTRL_SOC_H_
#define BSPFORGE_K210_PINCTRL_SOC_H_

#include <stdint.h>

/* FPIOA is initialized during PRE_KERNEL_1, so the UART has no DT pin states. */
typedef uint32_t pinctrl_soc_pin_t;

#define Z_PINCTRL_STATE_PINS_INIT(node_id, prop) {}

#endif /* BSPFORGE_K210_PINCTRL_SOC_H_ */
