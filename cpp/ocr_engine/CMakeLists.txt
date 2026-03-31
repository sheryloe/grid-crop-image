cmake_minimum_required(VERSION 3.20)
project(ocr_trt_runner LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(USE_TENSORRT "Build with TensorRT support" ON)

add_executable(ocr_trt_runner
    src/main.cpp
    src/ocr_pipeline.cpp
)

target_include_directories(ocr_trt_runner PRIVATE include)

if(USE_TENSORRT)
    target_compile_definitions(ocr_trt_runner PRIVATE USE_TENSORRT=1)
endif()

if(MSVC)
    target_compile_options(ocr_trt_runner PRIVATE /W4 /permissive-)
else()
    target_compile_options(ocr_trt_runner PRIVATE -Wall -Wextra -Wpedantic)
endif()
