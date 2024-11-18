# Colmi R02 raw data logging

This Python script, `ring.py`, logs raw sensor data from a [Colmi R02 ring](https://www.colmi.info/products/colmi-r02-smart-ring). It collects data such as accelerometer values, PPG (photoplethysmogram) readings, SpO2 (oxygen saturation) levels remotely using the Bluetooth data streaming. The script is designed to run on Python 3.11. It is recommended to updgrade the ring firmware for higher data streaming capabilities.

## Prerequisites

1. **Python Version**: Ensure you have Python 3.11 installed. Using `pyenv` is recommended for managing Python versions:
   ```bash
   pyenv install 3.11.0
   pyenv local 3.11.0
   ```

2. **Firmware Upgrade (optional but highly recommended)**:

    To support higher data streaming, it is highly recommended to upgrade the ring firmware. You can flash the new firmware using the following website: [ATC_RF03 Firmware Writer](https://atc1441.github.io/ATC_RF03_Writer.html)

    The firmware is located at the root of the repository: `R02_3.00.06_FasterRawValuesMOD.bin`

3. **Dependencies**: Install the required Python packages:
   ```bash
   pip install bleak pandas requests matplotlib
   ```

## Usage

1. Clone this repository
2. Run the script with the following command:
    
```bash
python ring.py --duration <duration_in_seconds>
```

*Notes: When running the script for the first time, it will ask you to select your ring. The address will be stored in a `config.json` file.*

```
> python ring.py --duration 60
0: SPEAKERS [B4095B2B-XXX-XXXX-XXXX-A5F4BEE8C7D8]
1: None [A7060F05-XXXX-XXXX-XXXX-B635A1BCCCE8]
2: R02_2182 [BBF33765-XXXX-XXXX-XXXX-DD487BF7717C]
Select a device by entering its number: 2
```

**If you don't see your device, make sure the ring is disconnected from previous connections** (QRing app for example).

### Optional arguments

You can also set a label, select which sensor to use, resample the data at a desired frequency, create graphs from the collected data or upload your data directly to Edge Impulse after the data collection.


```bash
python ring.py --duration <duration_in_seconds> --label idle --axis accX,accY,accZ,ppg --resample 20 --plot --ei_upload
```

* `--label <label>`: Label for the data item. Files will be prefixed with this label.
* `--axis <columns>`: Which columns (sensor data) to plot, resample and upload to Edge Impulse. Separate multiple columns with commas. If not set the following values will be used: `accX,accY,accZ,ppg,spO2`. Note that spO2 is spelled with a capital `O` not the number `0`.
* `--resample <milliseconds>`: Resampling rate in milliseconds
* `--plot`: Plot the selected axis
* `--ei_upload`: The script will prompt you for your Edge Impulse API Key if it's not already saved in `config.json`. You need to configure the [CSV Wizard](https://docs.edgeimpulse.com/docs/edge-impulse-studio/data-acquisition/csv-wizard) for you project. See below for more info.

## Explanation of the script

The `ring.py` script performs the following steps:

1. **Bluetooth Device Discovery**: Scans for nearby Bluetooth devices, allowing the user to select the Colmi R02 ring. Once selected, the device address is saved to `config.json` for automatic reconnection in future runs.
   
2. **Connect to the Ring**: Establishes a Bluetooth connection to the selected Colmi R02 ring.

3. **Enable Data Streaming**: Configures the ring to stream data by sending the appropriate commands to enable raw sensor data and set measurement units.

4. **Collect Sensor Data**: Retrieves and parses various sensor data packets from the ring, including:
   - **Accelerometer** readings (`accX`, `accY`, `accZ`)
   - **PPG** readings (`ppg_raw`, `ppg_max`, `ppg_min`, `ppg_diff`)
   - **SpO2** readings (`spO2_raw`, `spO2_max`, `spO2_min`, `spO2_diff`)

5. **Save Data to CSV**: Logs the collected data into a CSV file in the `raw_data` folder with a timestamped filename (e.g., `ring_data_YYYYMMDD_HHMMSS.csv`). If a `--label` is provided, the filename will be prefixed with the specified label.

6. **Resampling**: The data are resampled, by default at 50Hz, and saved in the resampled folder. The missing values are linearly interpolated.

7. **Graphing (optional)**: One graph per axis can be optionally ploted with Matplotlib.

![graph](/docs/graph.png)

8. **Upload to Edge Impulse (optional)**: The script can optionally upload the collected data to Edge Impulse using [Edge Impulse Ingestion API](https://docs.edgeimpulse.com/reference/data-ingestion/ingestion-api).

![EI Upload](/docs/ring-data-collection.gif)

## Raw data output format

Each CSV file contains the following columns:

| Column       | Description                                                |
|--------------|------------------------------------------------------------|
| `timestamp`  | ISO 8601 formatted timestamp                               |
| `payload`    | Hexadecimal string representation of the raw data payload  |
| `accX`, `accY`, `accZ` | Accelerometer readings (X, Y, Z axes)          |
| `ppg_raw`, `ppg_max`, `ppg_min`, `ppg_diff` | PPG sensor readings         |
| `spO2_raw`, `spO2_max`, `spO2_min`, `spO2_diff` | SpO2 sensor data       |

### Example CSV output

```csv
timestamp,payload,accX,accY,accZ,ppg_raw,ppg_max,ppg_min,ppg_diff,ppg,spO2_raw,spO2_max,spO2_min,spO2_diff
2024-11-06T13:45:22.087859,a10100a000c20072009501000000000c,,,,,,,,,160,194,114,149
2024-11-06T13:45:22.088225,a10229812acd29c1010c01000000003c,,,,10625,10957,10689,268,,,,,
2024-11-06T13:45:22.088273,a10312030b0d170400000000000000ec,372,291,-1859,,,,,,,,,
2024-11-06T13:45:22.328776,a101009900c200720095010000000005,,,,,,,,,153,194,114,149
2024-11-06T13:45:22.329075,a10229942acd29c1010c01000000004f,,,,10644,10957,10689,268,,,,,
2024-11-06T13:45:22.329126,a103110a0b01160800000000000000e9,360,282,-1871,,,,,,,,,
2024-11-06T13:45:22.567010,a101009900c200720095010000000005,,,,,,,,,153,194,114,149
2024-11-06T13:45:22.567513,a10229932acd29c1010c01000000004e,,,,10643,10957,10689,268,,,,,
2024-11-06T13:45:22.567588,a10312010c00160e00000000000000e7,366,289,-1856,,,,,,,,,
2024-11-06T13:45:22.806217,a101009900c200720095010000000005,,,,,,,,,153,194,114,149
2024-11-06T13:45:22.806648,a10229962acd29c1010c010000000051,,,,10646,10957,10689,268,,,,,
2024-11-06T13:45:22.806750,a10312010c00160e00000000000000e7,366,289,-1856,,,,,,,,,
2024-11-06T13:45:23.046104,a101009900c200720095010000000005,,,,,,,,,153,194,114,149
2024-11-06T13:45:23.046931,a10229972acd29c1010c010000000052,,,,10647,10957,10689,268,,,,,
2024-11-06T13:45:23.047054,a10312010c00160e00000000000000e7,366,289,-1856,,,,,,,,,
2024-11-06T13:45:23.286366,a101009900c200720095010000000005,,,,,,,,,153,194,114,149
2024-11-06T13:45:23.286761,a10229962acd29c1010c010000000051,,,,10646,10957,10689,268,,,,,
2024-11-06T13:45:23.287225,a10312010c00160e00000000000000e7,366,289,-1856,,,,,,,,,
2024-11-06T13:45:23.526652,a101009800c200720095010000000004,,,,,,,,,152,194,114,149
2024-11-06T13:45:23.527101,a10229942acd29c1010c01000000004f,,,,10644,10957,10689,268,,,,,
2024-11-06T13:45:23.527264,a10312010c00160e00000000000000e7,366,289,-1856,,,,,,,,,
2024-11-06T13:45:23.767238,a101000000c20072009501000000006c,,,,,,,,,0,194,114,149
2024-11-06T13:45:23.767739,a10200002acd29c1010c010000000092,,,,0,10957,10689,268,,,,,
2024-11-06T13:45:23.767887,a10312010c00160e00000000000000e7,366,289,-1856,,,,,,,,,
2024-11-06T13:45:24.007569,a101009800c200720095010000000004,,,,,,,,,152,194,114,149
2024-11-06T13:45:24.008782,a10229952acd29c1010c010000000050,,,,10645,10957,10689,268,,,,,
2024-11-06T13:45:24.008965,a10312010c00160e00000000000000e7,366,289,-1856,,,,,,,,,
2024-11-06T13:45:24.246474,a101009800c200720095010000000004,,,,,,,,,152,194,114,149
2024-11-06T13:45:24.247007,a10229932acd29c1010c01000000004e,,,,10643,10957,10689,268,,,,,
2024-11-06T13:45:24.247156,a10312010c00160e00000000000000e7,366,289,-1856,,,,,,,,,
```

## Upload to Edge Impulse

To automatically upload your data samples to Edge Impulse, you first need to configure the CSV Wizard for your project.
A default configuration file for the CSV Wizard is located at the root of this repository: `csv-wizard.json`. Feel free to upload your own CSV and configure it according to your needs.

To upload the configuration file, go to your project. In the **Data acquisition** view, navigate the the **CSV Wizard** tab and upload the `csv-wizard.json` file.

When first running the script with the `-ei_upload` argument, the script will ask your for your Edge Impulse project API KEY. It will then be saved in a config.json with your ring bluetooth address:

```
Data saved to raw_data/ring_data_20241118_154734.csv
Resampled data saved to resampled/idle.ring_data_20241118_154734.csv
Graph saved to graphs/idle.ring_data_20241118_154734_accX.png
Graph saved to graphs/idle.ring_data_20241118_154734_accY.png
Graph saved to graphs/idle.ring_data_20241118_154734_accZ.png
Graph saved to graphs/idle.ring_data_20241118_154734_ppg.png
Graph saved to graphs/idle.ring_data_20241118_154734_spO2.png
Please enter your Edge Impulse API Key: ei_xxxxx
Data successfully uploaded to Edge Impulse.
```

## Extract Heart Rates

See [Processing PPG input with HR/HRV Features Block](https://docs.edgeimpulse.com/docs/tutorials/end-to-end-tutorials/hr-hrv-block-example) for a complete tutorial.

![Extract HR](/docs/extract_HR.png)

## Resources

To build this script, I have used the following resources:

**OTA flasher:**

* [ATC RF03 Ring OTA Flasher](https://atc1441.github.io/ATC_RF03_Writer.html)

**Github Repositories:**

* [ATC_RF03_Ring](https://github.com/atc1441/)
* [colmi_r06_fbp](https://github.com/CitizenOneX/colmi_r06_fbp)
* [colmi_r02_client](https://github.com/tahnok/colmi_r02_client)

**Articles:**

* [2024-07-07 Smart Ring Hacking](https://notes.tahnok.ca/blog/2024-07-07+Smart+Ring+Hacking)