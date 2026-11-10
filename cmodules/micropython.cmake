# Top-level user C modules for the Cardputer ADV build (ESP32 port uses CMake).
#   make BOARD=M5STACK_CARDPUTER_ADV USER_C_MODULES=<this file>

include(${CMAKE_CURRENT_LIST_DIR}/cclcd/micropython.cmake)
include(${CMAKE_CURRENT_LIST_DIR}/mpy-qr/micropython.cmake)
include(${CMAKE_CURRENT_LIST_DIR}/libngu.cmake)

# ESP32-only hardware helpers
add_library(usermod_cardputer INTERFACE)
target_sources(usermod_cardputer INTERFACE ${CMAKE_CURRENT_LIST_DIR}/cardputer_hw/modcardputer.c)
target_link_libraries(usermod INTERFACE usermod_cardputer)
