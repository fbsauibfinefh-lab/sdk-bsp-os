from bspforge.semantic_feasibility import semantic_feasibility_penalty


def candidate(symbol: str, file: str, source_role: str = "sdk-driver", **features):
    defaults = {
        "opposite-action": 0.0,
        "semantic-conflict": 0.0,
        "reverse-os-adapter": 0.0,
        "test-example": 0.0,
        "hw-example-likelihood": 0.0,
        "hw-internal-callback-likelihood": 0.0,
    }
    defaults.update(features)
    return {
        "symbol": symbol,
        "file": file,
        "source_role": source_role,
        "features": defaults,
    }


def test_rejects_incompatible_cmsis_architecture():
    group = {"operation_id": "interrupt.initialize"}
    item = candidate("IRQ_Initialize", "Drivers/CMSIS/Core_A/Source/irq_ctrl_gic.c")
    assert semantic_feasibility_penalty(
        group, item, target_architecture="armv7-m-cortex-m3"
    ) == 1.0


def test_rejects_device_private_interrupt_and_accepts_controller_api():
    group = {"operation_id": "interrupt.enable"}
    private = candidate("USBD_X_EnableInterrupt", "components/usb/usbd_config.c")
    controller = candidate("__NVIC_EnableIRQ", "Drivers/CMSIS/Core/Include/core_cm3.h")
    assert semantic_feasibility_penalty(group, private) == 1.0
    assert semantic_feasibility_penalty(group, controller) == 0.0


def test_register_contract_requires_binding_action():
    group = {"operation_id": "interrupt.register"}
    pending = candidate("HAL_NVIC_SetPendingIRQ", "Drivers/hal_cortex.c")
    vector = candidate("__NVIC_SetVector", "Drivers/CMSIS/Core/Include/core_cm3.h")
    assert semantic_feasibility_penalty(group, pending) == 1.0
    assert semantic_feasibility_penalty(group, vector) == 0.0


def test_rejects_example_callback_but_keeps_public_driver():
    group = {"operation_id": "timer.set_interval"}
    callback = candidate(
        "HAL_TIM_PeriodElapsedCallback",
        "Projects/Examples/TIM/main.c",
        source_role="example-test",
        **{"hw-internal-callback-likelihood": 1.0},
    )
    public = candidate("HAL_TIM_Base_Init", "Drivers/hal_tim.c", source_role="public-hal")
    assert semantic_feasibility_penalty(group, callback) == 1.0
    assert semantic_feasibility_penalty(group, public) == 0.0


def test_non_registration_operation_rejects_callback_entities():
    group = {"operation_id": "timer.set_interval"}
    callback = candidate(
        "HAL_TIM_PeriodElapsedCallback",
        "Drivers/hal_tim.c",
        source_role="public-hal",
    )
    assert semantic_feasibility_penalty(group, callback) == 1.0


def test_interrupt_operations_require_controller_semantics():
    enable_group = {"operation_id": "interrupt.enable"}
    initialize_group = {"operation_id": "interrupt.initialize"}
    timer_event = candidate("mtb_hal_lptimer_enable_event", "drivers/lptimer.c")
    pending = candidate("HAL_NVIC_SetPendingIRQ", "Drivers/hal_cortex.c")
    priority = candidate("HAL_NVIC_SetPriority", "Drivers/hal_cortex.c")
    assert semantic_feasibility_penalty(enable_group, timer_event) == 1.0
    assert semantic_feasibility_penalty(initialize_group, pending) == 1.0
    assert semantic_feasibility_penalty(initialize_group, priority) == 0.0
