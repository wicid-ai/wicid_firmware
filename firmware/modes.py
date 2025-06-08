import time

def temperature_color(temp_f):
    """
    Returns an (R, G, B) color biased toward warmer hues,
    clamped between 0°F and 100°F (white->purple->blue->green->yellow->orange->red).
    """
    color_steps = [
        (0,   (55, 55, 55)),   # really cold: white
        (15,  (54,   1,   63)),   # cold: purple
        (35,  (0,    0,   220)),  # cool: blue
        (50,  (0,    100, 220)),  # lighter blue
        (60,  (0,    160, 100)),  # teal
        (70,  (10,   220,  10)),  # greenish
        (80,  (255,  135,  0)),   # yellow
        (90,  (255,  60,   0)),   # orange
        (100, (235,  0,    0)),   # red
    ]

    if temp_f is None:
        return (128, 128, 128)  # neutral gray if unknown

    if temp_f <= color_steps[0][0]:
        return color_steps[0][1]
    if temp_f >= color_steps[-1][0]:
        return color_steps[-1][1]

    for i in range(len(color_steps) - 1):
        lower_temp, lower_color = color_steps[i]
        upper_temp, upper_color = color_steps[i + 1]
        if lower_temp <= temp_f <= upper_temp:
            span = upper_temp - lower_temp
            ratio = (temp_f - lower_temp) / span
            r = int(lower_color[0] + ratio * (upper_color[0] - lower_color[0]))
            g = int(lower_color[1] + ratio * (upper_color[1] - lower_color[1]))
            b = int(lower_color[2] + ratio * (upper_color[2] - lower_color[2]))
            return (r, g, b)

    return color_steps[-1][1]

def blink_for_precip(pixels, color, precip_percent, button=None):
    """
    Blinks the NeoPixel according to the 'rounded to nearest 10%' precipitation probability.
      - Example: 27% => 30% => 3 blinks, then hold color for a few seconds.
      - If a button is provided, check it inside the blink to exit mid-cycle.
    """
    fast_blink_on = 0.3
    fast_blink_off = 0.2
    post_blink_pause = 3.0

    if precip_percent is None:
        # No data: just hold color for a short time
        pixels.fill(color)
        for _ in range(int(1 / 0.05)):  # ~1 second, checking button
            if button and not button.value:
                return False
            time.sleep(0.05)
        return True

    blink_count = round(precip_percent / 10.0)
    if blink_count > 10:
        blink_count = 10
    if blink_count < 0:
        blink_count = 0

    for _ in range(blink_count):
        pixels.fill(color)
        # Break the on/off into small increments, so we can detect button press
        for _ in range(int(fast_blink_on / 0.05)):
            if button and not button.value:
                return False
            time.sleep(0.05)

        pixels.fill((0, 0, 0))
        for _ in range(int(fast_blink_off / 0.05)):
            if button and not button.value:
                return False
            time.sleep(0.05)

    # After blinking, hold color
    pixels.fill(color)
    for _ in range(int(post_blink_pause / 0.05)):
        if button and not button.value:
            return False
        time.sleep(0.05)

    return True

def run_current_weather_mode(pixels, button, weather, update_interval=600):
    """
    The default 'current_weather_mode':
      - Periodically fetches current temperature & near-future precip chance.
      - Continuously shows blink_for_precip based on that data.
      - Returns to code.py when the user presses the button.
    """
    # Ensure button is released before starting
    while not button.value:
        time.sleep(0.05)

    last_update = None
    current_temp = None
    precip_chance_in_window = None

    while True:
        now = time.monotonic()

        if last_update is None or (now - last_update) >= update_interval:
            print("Updating weather data (current_weather_mode)")
            current_temp = weather.get_current_temperature()
            precip_chance_in_window = weather.get_precip_chance_in_window(0, 4)
            last_update = now
            print("Current temp (°F):", current_temp)
            print("Precip chance next 4h (%):", precip_chance_in_window)

        current_color = temperature_color(current_temp)

        # If blink_for_precip returns False, user pressed button
        if not blink_for_precip(pixels, current_color, precip_chance_in_window, button):
            break

        # Also check for button press after each blink cycle
        if not button.value:
            while not button.value:
                time.sleep(0.01)
            break

        time.sleep(0.05)

def run_temp_demo_mode(pixels, button):
    """
    Continuously cycles 0°F->100°F, slower pacing,
    then goes dark 2s, repeats.
    Returns when user presses button.
    """
    # Ensure button is released before starting
    while not button.value:
        time.sleep(0.05)

    while True:
        print("Temp Demo Mode: 0->100°F cycle")

        # Slower step time
        step_time = 0.15
        for temp_f in range(101):
            color = temperature_color(temp_f)
            pixels.fill(color)

            # Check button in small increments
            for _ in range(int(step_time / 0.05)):
                if not button.value:  # pressed
                    while not button.value:
                        time.sleep(0.01)
                    return  # Return to code.py
                time.sleep(0.05)

        # After 100°F, turn LED off and pause
        pixels.fill((0, 0, 0))
        pause_time = 2.0
        for _ in range(int(pause_time / 0.05)):
            if not button.value:
                while not button.value:
                    time.sleep(0.01)
                return
            time.sleep(0.05)


def run_precip_demo_mode(pixels, button):
    """
    Forces a color corresponding to 10°F, uses blink_for_precip with 30%,
    loops continuously until the user presses button to exit.
    """
    # Ensure button is released before starting
    while not button.value:
        time.sleep(0.05)

    while True:
        print("Precip Demo Mode: color=10°F, precip=30%")

        color_for_10f = temperature_color(10)
        # If the user presses button mid-blink, exit
        if not blink_for_precip(pixels, color_for_10f, 30, button):
            break

        if not button.value:  # pressed
            while not button.value:
                time.sleep(0.01)
            break
