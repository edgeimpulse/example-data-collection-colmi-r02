# Colmi R02 raw data logging

This Python script, `ring.py`, logs raw sensor data from a Colmi R02 ring. It collects data such as accelerometer values, PPG (photoplethysmogram) readings, SpO2 (oxygen saturation) levels. The script is designed to run on Python 3.11, and it requires a specific firmware upgrade for higher data streaming capabilities.

## Prerequisites

1. **Python Version**: Ensure you have Python 3.11 installed. Using `pyenv` is recommended for managing Python versions:
   ```bash
   pyenv install 3.11.0
   pyenv local 3.11.0
   ```

2. Firmware Upgrade:
The ring requires a firmware upgrade to support higher data streaming. You can flash the new firmware using the following website: [ATC_RF03 Firmware Writer](https://atc1441.github.io/ATC_RF03_Writer.html)