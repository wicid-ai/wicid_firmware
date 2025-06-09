import time
import board
import neopixel
import digitalio
import secrets
import supervisor

from weather import Weather
import modes

try:
    pixels = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.3, auto_write=True)

    button = digitalio.DigitalInOut(board.BUTTON)
    button.switch_to_input(pull=digitalio.Pull.UP)

    weather = Weather()

    modes_list = [
        modes.run_current_weather_mode,
        modes.run_temp_demo_mode,
        modes.run_precip_demo_mode
    ]
    mode_index = 0

    UPDATE_INTERVAL = secrets.secrets["update_interval"]

    while True:
        # Call the selected mode function (runs until user presses button)
        if modes_list[mode_index] == modes.run_current_weather_mode:
            modes_list[mode_index](pixels, button, weather, UPDATE_INTERVAL)
        elif modes_list[mode_index] == modes.run_temp_demo_mode:
            modes_list[mode_index](pixels, button)
        else:
            modes_list[mode_index](pixels, button)

        # Once the mode function returns, we move on to the next
        mode_index = (mode_index + 1) % len(modes_list)

        # Brief delay so we don't bounce immediately into next mode
        time.sleep(0.1)


except Exception as e:
    print("Restarting feather due to uncaught exception:", e)

    # Pause for operator to read message
    time.sleep(5)
    supervisor.reload()


