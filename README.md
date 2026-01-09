# 💧 Apavital Water Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/mirzacmarius/homeassistant-apavital.svg)](https://github.com/mirzacmarius/homeassistant-apavital/releases)
[![License](https://img.shields.io/github/license/mirzacmarius/homeassistant-apavital.svg)](LICENSE)

Home Assistant integration for monitoring water consumption from [Apavital](https://my.apavital.ro) smart water meters.

## ✨ Features

- 📊 **Energy Dashboard Compatible** - Works with HA Energy Dashboard for water tracking
- 📈 **Real-time Data** - Hourly updates from your smart water meter
- 🔔 **Multiple Sensors**:
  - Water Index (total consumption) - `sensor.apavital_water_index`
  - Daily Consumption - `sensor.apavital_water_daily`
  - Last Reading Time - `sensor.apavital_last_reading`
  - Meter Serial Number - `sensor.apavital_meter_serial`
- 🌍 **Multi-language** - English and Romanian translations
- ⚙️ **Config Flow** - Easy setup through Home Assistant UI

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
3. Select `sensor.apavital_water_meter_water_index`
4. Save

## 📊 Sensors

| Sensor | Description | Unit | Device Class |
|--------|-------------|------|--------------|
| `sensor.apavital_*_water_index` | Total water consumption (meter reading) | m³ | water |
| `sensor.apavital_*_water_daily_consumption` | Consumption in last 24h | m³ | water |
| `sensor.apavital_*_last_reading` | Timestamp of last reading | - | - |
| `sensor.apavital_*_meter_serial` | Water meter serial number | - | - |

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

The JWT token expires periodically. When your sensors show "unavailable":

1. Log in to https://my.apavital.ro
2. Get a new JWT token from Developer Tools
3. Go to **Settings** → **Devices & Services** → **Apavital**
4. Click **Configure** and update the token

## 🐛 Troubleshooting

### Sensors show "unavailable"

- Check if your JWT token has expired
- Verify your Client Code is correct
- Check Home Assistant logs for errors

### No data in Energy Dashboard

- Make sure the sensor has `state_class: total_increasing`
- Wait for at least one hour for data to appear
- Check if the sensor has historical data in Developer Tools → States

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
