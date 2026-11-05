cmake_minimum_required(VERSION 3.20)
project(DualSenseRDR2 CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if (NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif ()

# Everything static: the .asi must only depend on Windows DLLs and ScriptHookRDR2.dll.
add_compile_options(-Wall -Wno-unknown-pragmas -Wno-missing-field-initializers)
add_link_options(-static -static-libgcc -static-libstdc++)

set(CORE_SOURCES
    src/log.cpp src/config.cpp src/ds5.cpp src/dsp.cpp src/gameaudio.cpp src/haptics.cpp
    src/audio.cpp src/catalog.cpp src/engine.cpp src/input.cpp src/features.cpp src/core.cpp src/surfaces.cpp src/voice.cpp src/settings_menu.cpp src/game_files.cpp src/awc.cpp src/gamemem.cpp src/dialogue.cpp)
set(SYSTEM_LIBS setupapi hid ole32 uuid avrt winmm)

# Import library for ScriptHookRDR2.dll from the .def (maps plain names to its MSVC exports)
find_program(DLLTOOL dlltool REQUIRED)
set(SHV_LIB ${CMAKE_BINARY_DIR}/libScriptHookRDR2.a)
add_custom_command(OUTPUT ${SHV_LIB}
    COMMAND ${DLLTOOL} -d ${CMAKE_SOURCE_DIR}/scripthook/ScriptHookRDR2.def -l libScriptHookRDR2.a -m i386:x86-64
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}     # relative name: dlltool puts it into the stub symbols
    DEPENDS ${CMAKE_SOURCE_DIR}/scripthook/ScriptHookRDR2.def)
add_custom_target(shv_import DEPENDS ${SHV_LIB})

add_library(DualSenseRDR2 SHARED ${CORE_SOURCES} src/world.cpp src/settings_ui.cpp src/text_inject.cpp src/io_probe.cpp src/main.cpp)
add_dependencies(DualSenseRDR2 shv_import)
set_target_properties(DualSenseRDR2 PROPERTIES PREFIX "" SUFFIX ".asi")
target_link_options(DualSenseRDR2 PRIVATE -s)     # no symbols in the shipped .asi
target_link_libraries(DualSenseRDR2 PRIVATE ${SHV_LIB} ${SYSTEM_LIBS})

add_executable(dsr2_test ${CORE_SOURCES} src/world_stub.cpp src/standalone.cpp src/selftest.cpp)
target_link_libraries(dsr2_test PRIVATE ${SYSTEM_LIBS})

# the test program reads the same data the mod ships (tools/trigger_lab/data), synced on every build
set(LAB_DATA ${CMAKE_SOURCE_DIR}/../tools/trigger_lab/data)
add_custom_target(test_data ALL
    COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_BINARY_DIR}/DualSenseRDR2
    COMMAND ${CMAKE_COMMAND} -E copy_if_different ${LAB_DATA}/haptics.json ${LAB_DATA}/weapons.json
            ${LAB_DATA}/sound_labels.json ${LAB_DATA}/speech_voices.txt ${CMAKE_BINARY_DIR}/DualSenseRDR2/)
add_dependencies(dsr2_test test_data)
