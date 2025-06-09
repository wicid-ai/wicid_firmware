import wifi
import socketpool
import ssl
import adafruit_requests
import json
import time

try:
    import secrets
except ImportError:
    print("WiFi and ZIP code are kept in secrets.py, please add them there!")
    raise

class Weather:
    def __init__(self):
        """
        Initializes Wi-Fi, sets up a requests session, and
        retrieves latitude/longitude for the target ZIP code
        using Open-Meteo's geocoding API.
        """
        max_time = 60 * 60 * 4 # 4 hours
        attempts = 0
        while True:
            try:
                attempts = attempts + 1
                wifi.radio.connect(secrets.secrets["ssid"], secrets.secrets["password"])
                pool = socketpool.SocketPool(wifi.radio)
                self.session = adafruit_requests.Session(pool, ssl.create_default_context())
            except ConnectionError as ce:
                print(f"Connection Error #{attempts}: {ce} ")
                wait_time = attempts**1.3
                print("Wait (s):", wait_time)

                if wait_time < max_time:
                    time.sleep(wait_time)
                else:
                    raise SystemExit()
            else:
                break


        self.zip_code = secrets.secrets["weather_zip"]
        # Pull timezone from secrets, URL-encode slash for Open-Meteo
        raw_tz = secrets.secrets["weather_timezone"]
        self.timezone = raw_tz.replace("/", "%2F")

        self.lat, self.lon = self._get_lat_lon()

    def get_current_temperature(self):
        """
        Returns the current temperature in degrees Fahrenheit.
        """
        if self.lat is None or self.lon is None:
            return None
        url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current_weather=true&temperature_unit=fahrenheit&timezone={self.timezone}&models=dmi_seamless"
        response = self.session.get(url)
        data = response.json()
        response.close()

        return data["current_weather"]["temperature"]

    def get_daily_high(self):
        """
        Returns the forecasted high temperature (in °F) for the current day.
        """
        if self.lat is None or self.lon is None:
            return None
        url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&daily=temperature_2m_max&forecast_days=1&temperature_unit=fahrenheit&timezone={self.timezone}&models=dmi_seamless"
        response = self.session.get(url)
        data = response.json()
        response.close()

        return data["daily"]["temperature_2m_max"][0]

    def get_daily_precip_chance(self):
        """
        Returns the daily probability of precipitation (in %) for the current day.
        """
        if self.lat is None or self.lon is None:
            return None
        url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&daily=precipitation_probability_max&forecast_days=1&timezone={self.timezone}&models=dmi_seamless"
        response = self.session.get(url)
        data = response.json()
        response.close()
        return data["daily"]["precipitation_probability_max"][0]

    def get_precip_chance_in_window(self, start_time_offset, forecast_window_duration):
        """
        Returns the maximum precipitation probability (%) from the hourly data array,
        by matching the hour in 'current_weather.time' to the hour entries in 'hourly.time'.
        For example, if current_weather.time is '2025-02-06T14:15', it will look for
        '2025-02-06T14:00' in hourly.time.

        :param start_time_offset: (int or float) hours from 'current hour' to start
        :param forecast_window_duration: (int or float) hours to include
        :return: the maximum precipitation probability in that window (0-100), or 0 if no data
        """
        if self.lat is None or self.lon is None:
            return None

        # Single-line f-string for the URL:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current_weather=true&hourly=precipitation_probability&forecast_days=3&timezone={self.timezone}&models=dmi_seamless"
        response = self.session.get(url)
        data = response.json()
        response.close()

        #print(data)

        times = data["hourly"]["time"]                  # e.g., ["2025-02-06T14:00", ...]
        probs = data["hourly"]["precipitation_probability"]
        current_time_str = data["current_weather"]["time"]  # e.g. "2025-02-06T14:15"

        # Extract just the "YYYY-MM-DDTHH"
        hour_str = current_time_str[:13]  # e.g. "2025-02-06T14"
        #print(hour_str)

        # Match against the first 13 chars of each entry in 'times'
        current_index = None
        for i, t in enumerate(times):
            if t[:13] == hour_str:
                current_index = i
                break

        #print(current_index)

        if current_index is None:
            print("Warning: Could not match current_weather hour in hourly data.")
            return 0

        start_hour = current_index + int(start_time_offset)
        end_hour = start_hour + int(forecast_window_duration)

        #print(start_hour)

        # Clamp to array bounds
        if start_hour >= len(probs):
            return 0
        if end_hour > len(probs):
            end_hour = len(probs)
        if start_hour < 0:
            start_hour = 0

        window_probs = probs[start_hour:end_hour]
        if not window_probs:
            return 0

        return max(window_probs)

    def _get_lat_lon(self):
        """
        Attempts to find the latitude and longitude via Open-Meteo's geocoding API,
        using the ZIP code. Returns (None, None) if no result is found.
        """
        geocode_url = f"https://geocoding-api.open-meteo.com/v1/search?name={self.zip_code}&count=1"
        response = self.session.get(geocode_url)
        data = response.json()
        response.close()

        if "results" not in data or len(data["results"]) == 0:
            print("No geocoding results found for ZIP code:", self.zip_code)
            return None, None

        lat = data["results"][0]["latitude"]
        lon = data["results"][0]["longitude"]
        return lat, lon

# Example usage:
# weather = Weather()
# print("Current Temp (°F):", weather.get_current_temperature())
# print("Today's High (°F):", weather.get_daily_high())
# print("Chance of Precip (%):", weather.get_daily_precip_chance())
