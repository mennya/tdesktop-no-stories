add_executable(test_fork_update)
init_target(test_fork_update "(tests)")
target_include_directories(test_fork_update PRIVATE ${src_loc} ${CMAKE_CURRENT_BINARY_DIR}/gen)
target_compile_definitions(test_fork_update PRIVATE TDESKTOP_FORK_AUTOUPDATE)
add_dependencies(test_fork_update Telegram_update_keys)
nice_target_sources(test_fork_update ${src_loc}
PRIVATE
    core/fork_update.cpp
    core/fork_update.h
    core/update_keys.cpp
    core/update_keys.h
    core/update_verify.cpp
    core/update_verify.h
    core/update_unpack.cpp
    core/update_unpack.h
    tests/test_fork_update.cpp
)
target_link_libraries(test_fork_update PRIVATE
    desktop-app::external_qt
    desktop-app::external_openssl
    desktop-app::external_auto_updates
)
if (DESKTOP_APP_WIN7_BASELINE)
    target_link_libraries(test_fork_update PRIVATE desktop-app::lib_base)
endif()
set_target_properties(test_fork_update PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})

add_executable(test_fork_update_install)
init_target(test_fork_update_install "(tests)")
target_include_directories(test_fork_update_install PRIVATE ${src_loc})
nice_target_sources(test_fork_update_install ${src_loc}
PRIVATE
    _other/fork_update_install_win.cpp
    _other/fork_update_install_win.h
    tests/test_fork_update_install_win.cpp
)
set_target_properties(test_fork_update_install PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
