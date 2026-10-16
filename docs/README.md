# Wall Polargraph Documentation

| File | Contents |
| --- | --- |
| [Project brief](PROJECT_BRIEF.md) | Requirements and decisions |
| [Firmware audit](FIRMWARE_AUDIT.md) | Architecture and ESP32 gaps |
| [Roadmap](IMPLEMENTATION_ROADMAP.md) | Safety-first implementation plan |
| [Progress](PROGRESS.md) | Findings and current state |
| [ESP32 wiring and setup](ESP32_WIRING_AND_SETUP.md) | WROOM pin map, power, upload, calibration, and commissioning |
| [PCB hardware specification](PCB_HARDWARE_SPEC.md) | Component inventory, circuit/net definitions, power and protection, connectors, BOM and PCB release gates |
| [User paper calibration](USER_CALIBRATION.md) | Switch-free belt jogs, four-corner calibration, saved paper placement and explicit reboot recovery |
| [Stored plots](STORED_PLOTS.md) | Complete upload, flash capacity, independent drawing, reconnect and power-loss safety |
| [Wireless control](WIRELESS_CONTROL.md) | Wi-Fi setup, protocol, disconnect recovery, and verification |
| [Computer controller](../controller/README.md) | Browser UI, SVG preparation, job queue, and local startup |

ESP32-WROOM firmware support is implemented and builds successfully. Hardware wiring, geometry measurements, and physical commissioning remain; start with the wiring/setup guide.
