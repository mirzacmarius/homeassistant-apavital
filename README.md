# 💧 Apavital Water Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/mirzacmarius/homeassistant-apavital.svg)](https://github.com/mirzacmarius/homeassistant-apavital/releases)
[![License](https://img.shields.io/github/license/mirzacmarius/homeassistant-apavital.svg)](LICENSE)

Home Assistant integration for monitoring water consumption from [Apavital](https://my.apavital.ro) smart water meters.

## ✨ Features

- 📊 **Energy Dashboard Compatible** - Imports hourly history as long-term statistics, placed at the hour the water was used
- 📈 **Real-time Data** - Configurable update interval (15 min - 24 hours)
- 🚰 **Leak Detection** - Automatic alerts when consumption exceeds threshold
- 🔔 **Multiple Sensors**:
  - Water Index (total consumption)
  - Hourly/Daily/Weekly/Monthly Consumption
  - Last Reading Time
  - Meter Serial Number
  - Leak Detection Binary Sensor
- 🌍 **Multi-language** - English and Romanian translations
- ⚙️ **Config Flow** - Easy setup through Home Assistant UI
- 🔄 **Options Flow** - Update token and settings without removing integration
- 🔧 **Diagnostics** - Debug info accessible via HA diagnostics
- 📡 **Services** - Force data refresh on demand

## 📦 Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on **Integrations**
3. Click the **⋮** menu (top right) → **Custom repositories**
4. Add repository URL: `https://github.com/mirzacmarius/homeassistant-apavital`
5. Select category: **Integration**
6. Click **Add**
7. Search for "Apavital" and install
8. Restart Home Assistant

### Manual Installation

1. Download the latest release from GitHub
2. Copy `custom_components/apavital` to your Home Assistant `/config/custom_components/` directory
3. Restart Home Assistant

## ⚙️ Configuration

### Step 1: Get Your Credentials

You need two pieces of information from your Apavital account:

#### Client Code (GRUPMAS_COD)

1. Log in to https://my.apavital.ro
2. Open browser Developer Tools (F12)
3. Go to Network tab
4. Find a request to `/api/locuriCons`
5. Look for `GRUPMAS_COD` in the response (e.g., `416943`)

#### JWT Token

1. In the same Network tab
2. Find any API request
3. Look at Request Headers → `Authorization: Bearer ...`
4. Copy the entire token (starts with `eyJ...`)

### Step 2: Add Integration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for **Apavital**
4. Enter your Client Code and JWT Token
5. Click **Submit**

### Step 3: Add to Energy Dashboard

1. Go to **Settings** → **Dashboards** → **Energy**
2. Under **Water consumption**, click **Add water source**
3. Select **Apavital &lt;client code&gt; water consumption** (statistic `apavital:<client_code>_water_consumption`)
4. Save

This statistic is imported hour by hour from the meter readings, so every liter is
shown at the hour it was actually used. On the first update the integration imports
the full history the portal provides (usually several years). Apavital publishes
readings with a delay of several hours, and Home Assistant may be offline at times;
neither moves consumption onto the wrong day.

The statistic is stored in litres, so the Energy dashboard shows water in litres.
Upgrading from 1.3.x converts the existing history from m³ automatically; the
first update after the upgrade only converts, and new hours follow on the next one.

> Upgrading from 1.1.x: switch your Energy dashboard water source from
> `sensor.apavital_water_meter_water_index` to the new statistic. The old sensor
> keeps working, but it records usage at the moment Home Assistant receives it.

## 📊 Sensors

| Sensor | Description | Unit | Device Class |
|--------|-------------|------|--------------|
| `sensor.apavital_*_water_index` | Total water consumption (meter reading) | m³ | water |
| `sensor.apavital_*_hourly_consumption` | Consumption in last hour | L | volume |
| `sensor.apavital_*_daily_consumption` | Consumption since midnight | L | water |
| `sensor.apavital_*_weekly_consumption` | Consumption in last 7 days | m³ | water |
| `sensor.apavital_*_monthly_consumption` | Consumption in last 30 days | m³ | water |
| `sensor.apavital_*_last_reading` | Timestamp of last reading | - | - |
| `sensor.apavital_*_meter_serial` | Water meter serial number | - | - |
| `binary_sensor.apavital_*_leak_detected` | Water leak detection | - | moisture |

## 🚰 Leak Detection

The leak sensor scores the last 12 hours of consumption (50 of 90 points means a suspected leak):

| Signal | Points |
|--------|--------|
| 6+ consecutive hours above 5 L/h (leaks don't stop) | up to 30 |
| Constant flow (low coefficient of variation) | up to 25 |
| Consumption between 01:00 and 05:00 | 20 |
| Average flow above the leak threshold | 15 |

A suspected leak only turns the sensor on once a **newer meter reading confirms it**. After an outage the Apavital portal can serve estimated readings that spread the missing usage evenly over the gap. That looks exactly like a leak and is replaced by real readings later, so it no longer raises false alarms. While waiting, the sensor's `awaiting_confirmation` attribute is `true`.

Hours the portal revises within the last 7 days are also rewritten in the long-term statistics, so the Energy dashboard shows the real readings instead of the estimates.

To configure the threshold (default: 0.1 m³/hour ≈ 100 L/hour):
1. Go to **Settings** → **Devices & Services** → **Apavital**
2. Click **Configure**
3. Adjust "Leak detection threshold"

## 🧾 Price and Invoices

Every 6 hours the integration reads your invoices and the official meter readings of **every meter on your contract**. One invoice covers all the consumption places of a contract, so the integration works out the price of water and applies it to **your own meter** (the smart meter it reads, or else the contract's first place):

- **Price per m³** – the latest invoice divided by the water it billed (all meters), sewage and VAT included
- **Cost This Month** – this month's consumption × price per m³
- **Last Invoice** – your part of the latest invoice: your meter's billed water × price per m³ (the whole invoice is in the `contract_amount` attribute)
- **Next Invoice Estimate** – your part of the next invoice

Apavital reads all meters around the same day each month and bills that water the following month: an invoice issued in October bills the water read in September. The next invoice uses your meter's latest official reading; until that exists it uses the average of your recent months (attribute `based_on: recent_average`). If the invoices can't be read, these sensors stay unknown and the water sensors keep working.

The water statistic is also kept as a copy in m³ (`apavital:<client_code>_water_consumption_m3`), for statistics graphs of months and years, which can't convert units themselves.

## 🔧 Services

### `apavital.refresh_data`

Force an immediate data refresh from the Apavital API.

```yaml
service: apavital.refresh_data
data:
  entry_id: "optional_specific_entry_id"  # Leave empty to refresh all
```

## ⚙️ Options

After setup, you can modify settings without removing the integration:

1. Go to **Settings** → **Devices & Services** → **Apavital**
2. Click **Configure**
3. Available options:
   - **New JWT Token** - Update expired token
   - **Update interval** - How often to fetch data (15-1440 minutes)
   - **Leak threshold** - Consumption that triggers leak alert (m³/hour)

## 📱 Dashboard Cards

### Simple Entities Card

```yaml
type: entities
title: 💧 Apavital Water
entities:
  - entity: sensor.apavital_water_meter_water_index
    name: Index Contor
  - entity: sensor.apavital_water_meter_water_daily_consumption
    name: Consum 24h
  - entity: sensor.apavital_water_meter_last_reading
    name: Ultima Citire
```

### ApexCharts Card (requires HACS)

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: 💧 Consum Apă
  show_states: true
graph_span: 7d
series:
  - entity: sensor.apavital_water_meter_water_index
    type: area
    name: Index
    color: "#2196F3"
    stroke_width: 2
```

## 🔐 Token Expiration

The JWT token expires periodically (usually after 1 year). When your sensors show "unavailable":

### Option 1: Via UI (Recommended)
1. Go to **Settings** → **Devices & Services** → **Apavital**
2. Click **Configure**
3. Paste your new JWT token
4. Click **Submit**

### Option 2: Via Reauth Flow
When the token expires, Home Assistant will show a notification:
1. Click "Reconfigure"
2. Enter your new JWT token
3. Done!

### How to get a new token:
1. Log in to https://my.apavital.ro
2. Open Developer Tools (F12)
3. Go to Network tab
4. Find any API request
5. Copy the `Authorization: Bearer ...` token

## 🐛 Troubleshooting

### Sensors show "unavailable"

- Check if your JWT token has expired
- Verify your Client Code is correct
- Check Home Assistant logs for errors
- Download diagnostics: **Settings** → **Devices & Services** → **Apavital** → **⋮** → **Download diagnostics**

### No data in Energy Dashboard

- Make sure the sensor has `state_class: total_increasing`
- Wait for at least one hour for data to appear
- Check if the sensor has historical data in Developer Tools → States

### Check diagnostics

The integration provides detailed diagnostics:
1. Go to **Settings** → **Devices & Services**
2. Click on **Apavital**
3. Click ⋮ (three dots) → **Download diagnostics**

This includes:
- API call count
- Last successful update
- Error history
- Current configuration (redacted)

## 📝 API Information

This integration uses the Apavital API:

- **Endpoint**: `POST https://my.apavital.ro/api/get_usage`
- **Content-Type**: `multipart/form-data`
- **Authentication**: Bearer JWT token
- **Parameters**:
  - `clientCode`: GRUPMAS_COD from your location
  - `ctrAdmin`: "false"
  - `ctrEmail`: "" (empty)

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⚠️ Disclaimer

This is an unofficial integration. It is not affiliated with, endorsed by, or connected to Apavital in any way.
