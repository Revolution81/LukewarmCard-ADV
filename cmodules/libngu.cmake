# libngu (Coldcard's crypto library) for the ESP32 CMake build.
# Mirrors ngu/micropython.mk with NGU_NEEDS_CIFRA=1 and no mbedtls:
# the Cardputer port uses cifra for SHA-512/HMAC/PBKDF2/AES/DRBG and
# libsecp256k1 for all EC work (same as Coldcard's own simulator build).

set(NGU_TOP ${CMAKE_CURRENT_LIST_DIR}/libngu-src)
set(NGU_DIR ${NGU_TOP}/ngu)
set(CIFRA_SRC ${NGU_TOP}/libs/cifra/src)
set(K1_DIR ${NGU_TOP}/libs/secp256k1)

add_library(usermod_ngu INTERFACE)

target_sources(usermod_ngu INTERFACE
    ${NGU_DIR}/hash.c ${NGU_DIR}/modngu.c ${NGU_DIR}/ec.c ${NGU_DIR}/cert.c
    ${NGU_DIR}/k1.c ${NGU_DIR}/random.c ${NGU_DIR}/base32.c ${NGU_DIR}/codecs.c
    ${NGU_DIR}/hm.c ${NGU_DIR}/libbase58.c ${NGU_DIR}/hdnode.c ${NGU_DIR}/my_assert.c
    ${NGU_DIR}/lib_secp256k1.c ${NGU_DIR}/rmd160.c ${NGU_DIR}/aes.c ${NGU_DIR}/lib_segwit.c
    ${CIFRA_SRC}/hmac.c ${CIFRA_SRC}/sha1.c ${CIFRA_SRC}/sha3.c ${CIFRA_SRC}/sha256.c
    ${CIFRA_SRC}/sha512.c ${CIFRA_SRC}/pbkdf2.c ${CIFRA_SRC}/chash.c
    ${CIFRA_SRC}/blockwise.c ${CIFRA_SRC}/drbg.c ${CIFRA_SRC}/aes.c ${CIFRA_SRC}/modes.c
)

target_include_directories(usermod_ngu INTERFACE
    ${NGU_DIR} ${NGU_TOP}/libs ${CIFRA_SRC} ${CIFRA_SRC}/ext ${K1_DIR} ${K1_DIR}/src
)

target_compile_definitions(usermod_ngu INTERFACE
    NGU_USE_MBEDTLS=0
    NGU_INCL_AES=1
    NGU_INCL_SCHNORR=0
    NGU_INCL_MUSIG=0
    NGU_ESP32_RNG_IS_TRUE_RANDOM=1
    NGU_TARGET_ESP32=1          # selects the ESP32 RNG backend (random_backend.h)
    FULL_FAT_ASSERT
)

target_compile_options(usermod_ngu INTERFACE
    -Wno-unused-function -Wno-nonnull-compare -Wno-return-type -Wno-error
)

target_link_libraries(usermod INTERFACE usermod_ngu)
