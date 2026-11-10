// mdns.h - deliberately empty.
//
// This board has no network stack (MICROPY_PY_NETWORK=0, no WLAN, no LAN),
// so tools/build_device.sh drops MicroPython's espressif/mdns dependency.
// MicroPython's network_wlan.c / network_lan.c / modsocket.c still
// #include "mdns.h" outside their feature guards, without using anything
// from it once the network modules are compiled out.
//
// Nothing is declared here on purpose: if any compiled code ever calls an
// mdns function, the build fails with an undeclared-function error instead
// of linking something unexpected.
#pragma once
