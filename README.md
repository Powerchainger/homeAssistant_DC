# Powerchainger Home Assistant Custom Integration

This repository contains only a Home Assistant custom integration:

- `custom_components/powerchainger`

Use it with an existing Home Assistant installation (HA OS, Supervised, Container, or Core).

## Install

1. Locate your Home Assistant config directory (the folder that contains `configuration.yaml`).
2. Create this path if it does not exist:
   - `custom_components/powerchainger`
3. Copy this repository folder into your HA config:
   - source: `custom_components/powerchainger`
   - destination: `<HA_CONFIG>/custom_components/powerchainger`
4. Restart Home Assistant.

## Configuration in Home Assistant UI

No YAML setup is required.

Open:
- `Settings` -> `Devices & Services` -> `Add Integration`
- Search for `Powerchainger`

The setup flow will ask for:
- Send data (off by default)
- Which entities to send

The assigned random username is shown in the setup/options text and used to link incoming data.

Entity selection is filtered to electricity power entities only.

You can later change all settings from the integration `Configure` / `Options` page.

## Notes

- The integration uses a random generated username (not editable).
- WebSocket URL is fixed to `ws://146.190.226.254:5000`.
- Scan interval is fixed to `1` second.
- Keep `Send data` off while validating setup. Data is collected but not sent.
- Turn `Send data` on only when you are ready to send data to your backend.
- Payload format is compatible with the existing datacollection Socket.IO event `json`:
  - `UserId`, `Timestamp`, `Serial`, `Wattage`
