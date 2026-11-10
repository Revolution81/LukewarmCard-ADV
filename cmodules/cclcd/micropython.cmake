add_library(usermod_cclcd INTERFACE)
target_sources(usermod_cclcd INTERFACE ${CMAKE_CURRENT_LIST_DIR}/modlcd.c)
target_include_directories(usermod_cclcd INTERFACE ${CMAKE_CURRENT_LIST_DIR})
target_link_libraries(usermod INTERFACE usermod_cclcd)
