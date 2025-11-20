from logging_helper import logger
from utils import get_location_data_from_zip
from connection_manager import ConnectionManager


class WeatherService:
    def __init__(self, weather_zip, session=None):
        """
        Initialize the WeatherService with an active HTTP session.
        Retrieves latitude/longitude for the target ZIP code using Open-Meteo's geocoding API.
        
        Args:
            weather_zip: ZIP code string for weather location
            session: Optional adafruit_requests.Session instance (for tests)
        """
        self.logger = logger('wicid.weather')
        self.zip_code = weather_zip

        connection_manager = ConnectionManager.get_instance()
        self.session = session or connection_manager.create_session()

        # Get coordinates first, then detect timezone from them
        self.lat, self.lon, raw_tz = get_location_data_from_zip(self.session, self.zip_code)

        if raw_tz:
            # URL-encode slash for Open-Meteo
            self.timezone = raw_tz.replace("/", "%2F")
        else:
            # Fallback to default timezone if coordinates not available
            self.logger.warning("Could not get location data, using default timezone")
            self.timezone = "America%2FNew_York"

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

        url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current_weather=true&hourly=precipitation_probability&forecast_days=3&timezone={self.timezone}&models=dmi_seamless"
        response = self.session.get(url)
        data = response.json()
        response.close()

        times = data["hourly"]["time"]                  # e.g., ["2025-02-06T14:00", ...]
        probs = data["hourly"]["precipitation_probability"]
        current_time_str = data["current_weather"]["time"]  # e.g. "2025-02-06T14:15"

        # Extract just the "YYYY-MM-DDTHH"
        hour_str = current_time_str[:13]  # e.g. "2025-02-06T14"

        # Match against the first 13 chars of each entry in 'times'
        current_index = None
        for i, t in enumerate(times):
            if t[:13] == hour_str:
                current_index = i
                break

        if current_index is None:
            self.logger.warning("Could not match current_weather hour in hourly data")
            return 0

        start_hour = current_index + int(start_time_offset)
        end_hour = start_hour + int(forecast_window_duration)

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
